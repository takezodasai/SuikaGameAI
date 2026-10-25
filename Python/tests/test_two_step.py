import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv,validate_planning_settings
from test_unity_env import state
from test_unity_step import completed

class TwoStepProtocolTests(unittest.TestCase):
    def test_three_leaf_evaluators_and_wait(self):
        for leaf in ('reward','heuristic','value'):
            s=validate_planning_settings(dict(ai_mode='two_step',search_leaf=leaf,inter_step_wait_ticks=3,candidate_count=2))
            self.assertEqual(s['post_drop_steps'],25);self.assertEqual(s['search_leaf'],leaf)
    def test_invalid_leaf_and_wait_rejected(self):
        for settings in ({'search_leaf':'mcts'},{'inter_step_wait_ticks':-1},{'inter_step_wait_ticks':True},{'inter_step_wait_ticks':501}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):validate_planning_settings(settings)
    def test_legacy_defaults_preserved(self):
        s=validate_planning_settings({})
        self.assertEqual(s['ai_mode'],'heuristic');self.assertEqual(s['candidate_count'],5)
        self.assertEqual(s['weight_height'],0);self.assertEqual(s['weight_danger'],0)
    def test_opt_in_probe_keeps_existing_action_identity_and_result(self):
        reply=completed(x=.25);reply['path_comparison']=dict(status='awaiting_second_action')
        with UnityEnv(local=('127.0.0.1',0)) as env:
            env._action_episode='episode1'
            with patch.object(env,'receive_state',side_effect=[state(),reply]),patch.object(env,'_send') as send:
                s,reward,done,info=env.step(.25,_path_probe=dict(path_probe_phase=1,path_second_x=.75))
                command=send.call_args.args[0]
                self.assertEqual(command['command'],'step');self.assertEqual(command['action_id'],1)
                self.assertEqual(command['path_probe_phase'],1);self.assertEqual(command['path_second_x'],.75)
                self.assertEqual(info['path_comparison']['status'],'awaiting_second_action')
                self.assertEqual(env._action_id,1);self.assertIsNone(env._pending_step)
