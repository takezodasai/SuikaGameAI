import sys,unittest
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from value_reliability_data import roles,annotate
from value_reliability_train import RiskValueNetwork,metrics

class ReliabilityTests(unittest.TestCase):
    def test_test_priority(self):
        self.assertEqual(roles(['train','test']),'protected')
        self.assertEqual(roles(['historical_test','validation']),'protected')
    def test_conflicting_old_split_fails(self):
        with self.assertRaises(ValueError):roles(['train','validation'])
    def test_fresh_is_unassigned(self):self.assertIsNone(roles([]))
    def test_risk_transitions_not_seconds(self):
        r=[dict(game_over=i==7) for i in range(8)];annotate(r,None,[np.zeros((0,30))]*8)
        self.assertEqual([x['risk3'] for x in r],[False]*4+[True]*4)
        self.assertEqual(sum(x['near_go'] for x in r),4)
        self.assertFalse(r[-1]['near_go'])
    def test_observed_watermelon_window(self):
        r=[dict(game_over=False) for _ in range(12)];f=[np.zeros((0,30)) for _ in r];f[6]=np.zeros((1,30));f[6][0,10]=1;annotate(r,None,f)
        self.assertEqual(r[0]['wm_window'],'other');self.assertEqual(r[5]['wm_window'],'pre_observed');self.assertEqual(r[6]['wm_window'],'post_observed');self.assertEqual(r[11]['wm_window'],'other')
    def test_terminal_value_mask_and_risk_shape(self):
        m=RiskValueNetwork();g=torch.zeros(2,37);g[1,35]=1
        from suika_ai.long_value_model import geometry_features
        geometry=torch.tensor(np.stack([geometry_features([],x.tolist()) for x in g]))
        value,risk=m(torch.zeros(2,1,30),torch.zeros(2,1,dtype=torch.bool),g,geometry)
        self.assertEqual(tuple(risk.shape),(2,));self.assertEqual(float(value[1]),0);self.assertTrue(torch.isfinite(value).all())
    def test_near_go_error_excludes_terminal(self):
        r=[dict(target=0,group='a',game_over=False,near_go=True,wm_window='other'),dict(target=0,group='a',game_over=True,near_go=False,wm_window='other')]
        result=metrics(r,[0,1],np.array([100.,0.]));self.assertEqual(result['near_go']['mae'],100);self.assertEqual(result['all']['states'],1)

if __name__=='__main__':unittest.main()
