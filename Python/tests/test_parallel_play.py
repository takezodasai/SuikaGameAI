import json
from pathlib import Path
import tempfile
import threading
import unittest
from suika_ai.parallel_play import WorkerSpec,worker_specs,DurableLog,collect_worker,player_command,check_ports,validate_run


def snapshot(score=0,go=False,episode="e"):
    return dict(protocol_version=2,game_id="game_00",stream_id="stream",episode_id=episode,state_id=1,
        score=score,game_over=go,current_fruit=dict(present=True,type=0,x=0),next_fruit_type=1,fruits=[])


class FakeEnv:
    _pending_step=None;_action_episode="e";_action_id=0;last_state=None
    def __init__(self,terminal=True):self.resets=0;self.steps=0;self.reads=0;self.terminal=terminal
    def reset(self):self.resets+=1;return snapshot()
    def receive_state(self,*args):
        self.reads+=1
        return snapshot(8,self.terminal) if self.steps else snapshot()
    def plan_step(self,settings):
        self.steps+=1;self._action_id+=1
        return snapshot(7,self.terminal),5,self.terminal,dict(action_id=self._action_id,score_before=2,status="completed")


class ParallelTests(unittest.TestCase):
    def test_unique_ports_and_seed(self):
        specs=worker_specs(4)
        self.assertEqual(len({p for s in specs for p in (s.listen_port,s.python_port)}),8)
        self.assertEqual(len({s.seed for s in specs}),4)
        for args in ((0,18000),(5,18000),(2,65534),(2,1000)):
            with self.assertRaises(ValueError):worker_specs(*args)

    def test_durable_exclusive_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"log.jsonl"
            with DurableLog(path) as log:
                row=dict(event="transition",game_id="g",stream_id="s",episode_id="e",action_id=1)
                log.write(row)
                self.assertEqual(len(path.read_text().splitlines()),1)
                with self.assertRaises(ValueError):log.write(row)
            with self.assertRaises(FileExistsError):DurableLog(path)

    def test_gaps_not_double_counted_and_final_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=FakeEnv();path=Path(tmp)/"g.jsonl"
            result=collect_worker(worker_specs(1)[0],env,{},1,100,threading.Event(),path)
            rows=[json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(result["status"],"completed")
            self.assertEqual((env.resets,env.steps),(1,1))
            self.assertEqual(rows[1]["between_steps_reward"],2)
            self.assertEqual(rows[1]["reward"],5)
            self.assertEqual(rows[-1]["tail_between_steps_reward"],1)
            self.assertEqual(rows[-1]["final_score"],8)
            self.assertTrue(rows[-1]["conserved"])

    def test_truncation_not_a_terminal_training_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"g.jsonl";env=FakeEnv(terminal=False)
            collect_worker(worker_specs(1)[0],env,{},1,1,threading.Event(),path)
            end=json.loads(path.read_text().splitlines()[-1])
            self.assertTrue(end["truncated"]);self.assertIsNone(end["final_score"])

    def test_unknown_outcome_preserves_completed_prefix(self):
        class ErrorEnv(FakeEnv):
            def plan_step(self,settings):
                self._pending_step=dict(action_id=1);raise TimeoutError("unknown")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"g.jsonl"
            result=collect_worker(worker_specs(1)[0],ErrorEnv(),{},1,10,threading.Event(),path)
            rows=[json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(result["status"],"error")
            self.assertEqual(rows[0]["event"],"episode_start")
            self.assertEqual(rows[-1]["event"],"worker_error")
            self.assertTrue(rows[-1]["outcome_unknown"])

    def test_per_game_terminal_does_not_stop_another_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop=threading.Event();a=FakeEnv(True);b=FakeEnv(False)
            ra=collect_worker(worker_specs(1)[0],a,{},1,2,stop,Path(tmp)/"a.jsonl")
            # Independent worker keeps collecting; its own score ledger is supplied per turn.
            class TwoStepEnv(FakeEnv):
                def plan_step(self,settings):
                    self.steps+=1;self._action_id+=1
                    score=7 if self.steps==1 else 8
                    return snapshot(score,False),5 if self.steps==1 else 1,False,dict(action_id=self._action_id,score_before=2 if self.steps==1 else 7,status="completed")
            b=TwoStepEnv(False)
            rb=collect_worker(worker_specs(1)[0],b,{},1,2,stop,Path(tmp)/"b.jsonl")
            self.assertEqual((ra["steps"],rb["steps"]),(1,2))
            self.assertFalse(stop.is_set())

    def test_wrong_game_packet_is_ignored_before_stream_binding(self):
        import json
        from unittest.mock import patch
        from suika_ai.unity_env import UnityEnv
        from test_unity_env import state
        a=state(1);a["game_id"]="other";b=state(2);b["game_id"]="wanted"
        with UnityEnv(local=("127.0.0.1",0),expected_game_id="wanted") as env,patch.object(env,"socket") as sock:
            sock.recvfrom.side_effect=[(json.dumps(v).encode(),("127.0.0.1",1234)) for v in (a,b)]
            self.assertEqual(env.receive_state()["game_id"],"wanted")
            self.assertEqual(env.last_state_id,2)

    def test_go_between_actions_is_not_a_duplicate_transition(self):
        class BetweenGoEnv(FakeEnv):
            def plan_step(self,settings):
                self.steps+=1
                if self.steps==1:
                    self._action_id=1
                    return snapshot(7,False),5,False,dict(action_id=1,score_before=2,status="completed")
                return snapshot(8,True),0,True,dict(status="game_over")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"g.jsonl";env=BetweenGoEnv()
            result=collect_worker(worker_specs(1)[0],env,{},1,3,threading.Event(),path)
            rows=[json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(result["status"],"completed")
            self.assertEqual([r["event"] for r in rows],["episode_start","transition","terminal_observation","episode_end"])
            self.assertEqual(rows[-1]["final_score"],8)
            self.assertEqual(result["steps"],1)

    def test_player_headless_does_not_change_clock_or_rules(self):
        cmd=player_command("game.exe",worker_specs(1)[0],"log.txt",True)
        self.assertIn("-nographics",cmd);self.assertIn("-batchmode",cmd)
        self.assertNotIn("-timescale",cmd)


if __name__=="__main__":unittest.main()


class EpisodeWallLimitTests(unittest.TestCase):
    def test_opt_in_wall_limit_is_truncation_not_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'g.jsonl';env=FakeEnv(False)
            from unittest.mock import patch
            from itertools import count
            with patch('suika_ai.parallel_play.time.monotonic',side_effect=count()):
                result=collect_worker(worker_specs(1)[0],env,{},1,10,threading.Event(),path,training_metadata=False,max_episode_seconds=.1)
            rows=[json.loads(x) for x in path.read_text().splitlines()];end=rows[-1]
            self.assertEqual(result['steps'],0);self.assertEqual(end['reason'],'wall_limit')
            self.assertFalse(end['game_over']);self.assertTrue(end['truncated']);self.assertIsNone(end['final_score'])
            self.assertGreaterEqual(end['wall_seconds'],0)
