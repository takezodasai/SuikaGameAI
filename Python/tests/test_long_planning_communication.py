"""Long sync searches must not starve the following metadata request."""
from collections import deque
import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv
from test_unity_env import state
from test_planning import planned_reply

META = dict(schema_version=1, unity_version='2022.3.21f1', build_guid='test',
            fixed_delta_time=.02, physics_profiles=[{'id':'runtime'}], boundaries=[{}])

class LongPlanningCommunicationTests(unittest.TestCase):
    def test_long_search_then_metadata_and_lost_first_packet(self):
        for mode,lose_first in ((mode,loss) for mode in ("time","importance") for loss in (0,1,2)):
            with self.subTest(mode=mode,lose_first=lose_first), UnityEnv(local=('127.0.0.1',0)) as env:
                env._action_episode='episode1'
                clock=[1.0]; queue=deque(); sent=[]; end=[None]; finished=[False]
                def send(command):
                    sent.append((clock[0],command))
                    if len(sent)<=lose_first: return
                    if end[0] is None: end[0]=clock[0]+120
                    else: queue.append(command)
                def receive(timeout, **kwargs):
                    if end[0] is None and not kwargs: return state()
                    if not finished[0]:
                        clock[0]+=timeout
                        if end[0] is not None and clock[0]>=end[0]:
                            finished[0]=True
                            return planned_reply()
                        raise TimeoutError()
                    # One queued command per slow 750ms Unity frame after the search.
                    clock[0]+=.75
                    if queue and queue.popleft()['command']=='environment':
                        return dict(environment=META)
                    return state()
                with patch('suika_ai.unity_env.time.monotonic',side_effect=lambda:clock[0]), patch.object(env,'_send',side_effect=send), patch.object(env,'receive_state',side_effect=receive):
                    _,reward,done,_=env.plan_step(dict(ai_mode='mcts',mcts_extended_budget=True,mcts_budget_mode=mode,mcts_time_limit_seconds=120,mcts_max_iterations=32768))
                    completed_at=clock[0]
                    self.assertEqual(env.get_environment(),META)
                commands=[c for _,c in sent if c['command']=='plan_step']
                self.assertGreater(len(commands),1)
                self.assertLessEqual(len(commands),4)
                self.assertTrue(all(c==commands[0] for c in commands))
                self.assertLess(clock[0]-completed_at,5)
                self.assertEqual((reward,done,env._action_id),(3,False,1))
                self.assertIsNone(env._pending_step)

    def test_observation_burst_does_not_flood_environment_requests(self):
        clock=[1.0]
        with UnityEnv(local=('127.0.0.1',0)) as env:
            def receive(timeout):
                clock[0]+=.01
                return state()
            with patch('suika_ai.unity_env.time.monotonic',side_effect=lambda:clock[0]), patch.object(env,'receive_state',side_effect=receive), patch.object(env,'_send') as send:
                with self.assertRaisesRegex(TimeoutError,'No complete training metadata'):
                    env.get_environment(timeout=2)
                self.assertGreaterEqual(send.call_count,3)
                self.assertLessEqual(send.call_count,4)

    def test_legacy_retry_cadence_and_unknown_outcome_are_unchanged(self):
        clock=[1.0]
        with UnityEnv(local=('127.0.0.1',0)) as env:
            env._action_episode='episode1'
            def receive(timeout,**kwargs):
                if not kwargs:return state()
                clock[0]+=timeout
                raise TimeoutError()
            with patch('suika_ai.unity_env.time.monotonic',side_effect=lambda:clock[0]), patch.object(env,'receive_state',side_effect=receive), patch.object(env,'_send') as send:
                with self.assertRaisesRegex(TimeoutError,'outcome unknown'):
                    env.plan_step(timeout=2)
                self.assertEqual(send.call_count,8)
                self.assertIsNotNone(env._pending_step)
                with self.assertRaisesRegex(RuntimeError,'outcome is unknown'):
                    env.plan_step()

