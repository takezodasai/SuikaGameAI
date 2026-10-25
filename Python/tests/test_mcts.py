import unittest
from suika_ai.unity_env import validate_planning_settings
class MctsSettingsTests(unittest.TestCase):
    def test_modes_and_scales(self):
        for mode in ('mcts','mcts_value'):
            for count in (16,32,64):
                s=validate_planning_settings(dict(ai_mode=mode,mcts_iterations=count,mcts_max_depth=3))
                self.assertEqual(s['post_drop_steps'],25)
                self.assertEqual(s['mcts_point_scale'],55.)
    def test_bad_budget_or_depth(self):
        for change in ({'mcts_iterations':4},{'mcts_iterations':257},{'mcts_iterations':True},
                       {'mcts_max_depth':0},{'mcts_max_depth':9},{'mcts_point_scale':0},
                       {'mcts_point_scale':None},{'mcts_point_scale':'55'},{'mcts_exploration':float('nan')},{'mcts_seed':-1},{'two_step_exhaustive_reward':1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_planning_settings(dict(ai_mode='mcts',**change))
    def test_reward_diagnostic_flag(self):
        self.assertTrue(validate_planning_settings({'two_step_exhaustive_reward':True})['two_step_exhaustive_reward'])
