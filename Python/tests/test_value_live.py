import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from suika_ai.unity_env import validate_planning_settings

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

class ValueLiveTests(unittest.TestCase):
    def test_modes_and_defaults(self):
        self.assertEqual(validate_planning_settings({})['ai_mode'],'heuristic')
        self.assertEqual(validate_planning_settings({'ai_mode':'value'})['post_drop_steps'],25)
        for s in ({'ai_mode':'not_a_mode'},{'value_model_path':42}):
            with self.assertRaises(ValueError):validate_planning_settings(s)
    def test_checkpoint_and_portable_tensors(self):
        # Optional local artifact integration: source-only checkouts do not contain checkpoints.
        exported=ROOT.parent/'Unity/Assets/StreamingAssets/suika_value_epoch3.json'
        if not exported.exists():self.skipTest('Export not present')
        m=json.loads(exported.read_text())
        self.assertEqual(m['epoch'],3);self.assertEqual(m['parameters'],35713)
        self.assertEqual(sum(len(l['weights'])+len(l['bias']) for l in m['layers']),35713)
        self.assertEqual([(l['inputs'],l['outputs']) for l in m['layers']],[(30,64),(64,64),(165,128),(128,64),(64,1)])
    def test_summary_does_not_invent_completed_pairs(self):
        with tempfile.TemporaryDirectory() as folder:
            report=module('compare_value_ai').summarize(folder)
            self.assertEqual(report['paired_difference']['n'],0)
            self.assertIsNone(report['paired_mean_difference_95ci'])
    def test_fixture_zero_and_unknown_and_terminal(self):
        fixture=ROOT.parent/'Unity/Assets/StreamingAssets/suika_value_parity.json'
        if not fixture.exists():self.skipTest('Export not present')
        cases=json.loads(fixture.read_text())['cases']
        self.assertTrue(any(not c['state']['fruits'] for c in cases))
        self.assertTrue(any(c['state']['next_fruit_type']==-1 for c in cases))
        self.assertTrue(any(c['state']['game_over'] and c['expected']==0 for c in cases))
