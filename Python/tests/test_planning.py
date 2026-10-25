import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv, validate_planning_settings
from test_unity_env import state
from test_unity_step import completed


def planned_reply():
    reply=completed(x=.75)
    reply["planning"]=dict(selected_index=3,selected_x=.75,
        candidates=[dict(x=x,selection_score=None if x==0 else .2) for x in (0,.25,.5,.75,1)])
    return reply


class PlanningTests(unittest.TestCase):
    def test_settings_validation(self):
        for settings in ({"candidate_count":1},{"post_drop_steps":151},{"height_bins":True},
                         {"score_scale":0},{"weight_height":-1},{"weight_danger":float("nan")},
                         {"future_rng":True},{"danger_band_fraction":0},{"uncontacted_risk_weight":2}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_planning_settings(settings)
        self.assertEqual(validate_planning_settings({"candidate_count":9})["post_drop_steps"],25)

    def test_plan_uses_selected_position_and_existing_action_ledger(self):
        with UnityEnv(local=("127.0.0.1",0)) as env:
            env._action_episode="episode1"
            with patch.object(env,"receive_state",side_effect=[state(),planned_reply()]), patch.object(env,"_send") as send:
                observation,reward,done,info=env.plan_step({"candidate_count":5})
                self.assertEqual(info["requested_x"],.75)
                self.assertEqual(reward,3)
                command=send.call_args.args[0]
                self.assertEqual(command["command"],"plan_step")
                self.assertEqual(command["planning_settings"]["post_drop_steps"],25)
                self.assertEqual(command["action_id"],1)
                self.assertEqual(env._action_id,1)
                self.assertIsNone(info["planning"]["candidates"][0]["selection_score"])
                self.assertIsNone(env._pending_step)

    def test_game_over_between_baseline_and_command_stops_cleanly(self):
        terminal=state(2); terminal["game_over"]=True
        terminal["step_result"]=dict(action_id=1,status="game_over",drop_success=False)
        with UnityEnv(local=("127.0.0.1",0)) as env:
            env._action_episode="episode1"
            with patch.object(env,"receive_state",side_effect=[state(),terminal]),patch.object(env,"_send"):
                _,reward,done,_=env.plan_step()
                self.assertTrue(done); self.assertEqual(reward,0); self.assertIsNone(env._pending_step)

    def test_plan_failure_requires_reset(self):
        bad=planned_reply();bad["planning"]["selected_index"]=-1
        bad["step_result"]["status"]="no_nonterminal_evaluated"
        with UnityEnv(local=("127.0.0.1",0)) as env:
            env._action_episode="episode1"
            with patch.object(env,"receive_state",side_effect=[state(),bad]),patch.object(env,"_send"):
                with self.assertRaises(RuntimeError): env.plan_step()
                with self.assertRaisesRegex(RuntimeError,"unknown"):env.plan_step()

    def test_invalid_settings_send_nothing(self):
        with UnityEnv(local=("127.0.0.1",0)) as env,patch.object(env,"_send") as send:
            with self.assertRaises(ValueError):env.plan_step({"candidate_count":0})
            send.assert_not_called()

    def test_autoplay_stops_at_game_over_no_repeated_reset(self):
        spec=importlib.util.spec_from_file_location("play_one_step_ai",Path(__file__).parents[1]/"play_one_step_ai.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class FakeEnv:
            resets=0;steps=0
            def reset(self):self.resets+=1;return {"game_over":False}
            def plan_step(self,settings):
                self.steps+=1
                return dict(game_over=self.steps==2,episode_id="e",score=self.steps),1,self.steps==2,dict(planning={})
        env=FakeEnv()
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"decisions.jsonl"
            final=module.play(env,{},100,output)
            self.assertTrue(final["game_over"])
            self.assertEqual(len(output.read_text().splitlines()),2)
        self.assertEqual((env.resets,env.steps),(1,2))


if __name__=="__main__":unittest.main()
