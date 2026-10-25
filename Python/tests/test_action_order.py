import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
from analyze_two_step_probe import trace_search
import test_two_step_diagnostic as diagnostic
from compare_order_ai import settings

class OrderTests(unittest.TestCase):
    def test_defaults_and_opt_in(self):
        self.assertEqual(validate_planning_settings({})['action_order_policy'],'index')
        self.assertEqual(validate_planning_settings(settings('shuffle'))['expansion_policy'],'legacy')
    def test_invalid_settings(self):
        for patch in [dict(action_order_policy='bad'),dict(ai_mode='value'),dict(execution_mode='frames'),dict(tree_policy='public_open_loop'),dict(expansion_policy='chance_decision'),dict(rollout_policy='guided'),dict(candidate_policy='board-five')]:
            s=settings('shuffle');s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'fake.exe';exe.write_bytes(b'x')
            with self.assertRaises(ValueError):run_parallel(exe,p/'out',games=4,settings=settings('shuffle'))
            self.assertFalse((p/'out').exists())
    def sample(self):
        r=diagnostic.TwoStepDiagnosticTests().search();r['decision']['settings']['action_order_policy']='shuffle'
        m=r['report'];m['nodes'][0]['unvisited_order']=[1,0]
        for n in m['nodes'][1:]:n['unvisited_order']=[0,1]
        m['iterations'][0]['actions'][0]=1;m['iterations'][1]['actions'][0]=0
        return r
    def test_trace_accepts_permutation(self):self.assertEqual(trace_search(self.sample())[0]['steps'][0]['action_index'],1)
    def test_duplicate_or_missing_permutation_rejected(self):
        for order in [[0,0],[0],[0,2]]:
            r=self.sample();r['report']['nodes'][0]['unvisited_order']=order
            with self.assertRaisesRegex(ValueError,'permutation'):trace_search(r)
    def test_out_of_order_first_visit_rejected(self):
        r=self.sample();r['report']['iterations'][0]['actions'][0]=0
        with self.assertRaises(ValueError):trace_search(r)
    def test_other_settings_identical(self):
        a=settings('index');b=settings('shuffle');a.pop('action_order_policy');b.pop('action_order_policy');self.assertEqual(a,b)
    def test_legacy_trace_remains_accepted(self):trace_search(diagnostic.TwoStepDiagnosticTests().search())

    def test_long_run_is_not_enabled(self):
        from unittest.mock import patch
        import io
        from compare_order_ai import main
        with tempfile.TemporaryDirectory() as d,patch('sys.argv',['compare_order_ai.py','--output',str(Path(d)/'out')]),patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit):main()
            self.assertFalse((Path(d)/'out').exists())
