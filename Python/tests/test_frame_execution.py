import unittest
from suika_ai.unity_env import validate_planning_settings
class FrameExecutionTests(unittest.TestCase):
    def test_defaults_are_synchronous(self):
        self.assertEqual(validate_planning_settings({})['execution_mode'],'sync')
    def test_explicit_mcts_only(self):
        for mode in ('mcts','mcts_value'):
            s=validate_planning_settings(dict(ai_mode=mode,execution_mode='frames',mcts_max_depth=6,mcts_iterations=64))
            self.assertEqual((s['mcts_max_depth'],s['mcts_iterations']),(6,64))
        for mode in ('heuristic','value','two_step'):
            with self.assertRaises(ValueError):validate_planning_settings(dict(ai_mode=mode,execution_mode='frames'))
    def test_resource_and_deadline_guards(self):
        for key,value in (('frame_budget_ms',float('nan')),('frame_budget_ms',31),('frame_timeout_seconds',26),('frame_lead_ticks',501),('frame_max_attempts',4),('frame_max_attempts',True)):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_planning_settings(dict(ai_mode='mcts',execution_mode='frames',**{key:value}))

    def test_four_game_opt_in_rejected_before_launch_or_output(self):
        import tempfile
        from pathlib import Path
        from suika_ai.parallel_play import run_parallel
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'owned-test.exe';exe.write_bytes(b'not executed')
            output=Path(directory)/'output'
            with self.assertRaises(ValueError):
                run_parallel(exe,output,games=4,settings=dict(ai_mode='mcts',execution_mode='frames'))
            self.assertFalse(output.exists())

    def test_adaptive_is_opt_in_and_still_requires_full_mcts(self):
        s=validate_planning_settings(dict(execution_mode='frames_adaptive',ai_mode='mcts',mcts_iterations=32,mcts_max_depth=4))
        self.assertEqual((s['mcts_iterations'],s['mcts_max_depth']),(32,4))
        self.assertEqual(validate_planning_settings({})['execution_mode'],'sync')
        for mode in ('heuristic','value','two_step'):
            with self.assertRaises(ValueError):validate_planning_settings(dict(execution_mode='frames_adaptive',ai_mode=mode))

    def test_tick_slicing_is_explicit_and_does_not_change_mcts_budget(self):
        self.assertFalse(validate_planning_settings({})['frame_tick_slicing'])
        for depth in (4,5,6):
            s=validate_planning_settings(dict(ai_mode='mcts',execution_mode='frames',frame_tick_slicing=True,mcts_iterations=32,mcts_max_depth=depth))
            self.assertEqual((s['mcts_iterations'],s['mcts_max_depth']),(32,depth))
        with self.assertRaises(ValueError):validate_planning_settings(dict(frame_tick_slicing=1))
