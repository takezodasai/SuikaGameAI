import sys,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compare_mc_td_learning import bootstrap_targets,metrics,CONFIG,fingerprint
from mc_td_data import homogeneous
from suika_ai.temporal_value_targets import n_step_pairs
from suika_ai.long_value_model import GeometryValueNetwork

class Constant(torch.nn.Module):
    def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.tensor(.4))
    def forward(self,x):return self.p.expand(len(x))

class MCTDTests(unittest.TestCase):
    def boards(self,splits):return SimpleNamespace(records=[dict(split=s) for s in splits],batch=lambda ids:(torch.ones(len(ids)),))
    def test_terminal_bootstrap_zero_even_external_endpoint(self):
        t=dict(reward=np.array([6.]),next_index=np.array([100]),terminal=np.array([True]))
        y=bootstrap_targets(Constant(),self.boards(['train']),[0],t)
        self.assertAlmostEqual(float(y[0]),.006,places=6);self.assertFalse(y.requires_grad)
    def test_nonterminal_bootstrap_point_scale(self):
        t=dict(reward=np.array([30.,0]),next_index=np.array([1,1]),terminal=np.array([False,True]))
        y=bootstrap_targets(Constant(),self.boards(['train','train']),[0],t)
        self.assertAlmostEqual(float(y[0]),.430,places=6);self.assertFalse(y.requires_grad)
    def test_validation_future_never_enters_training_target(self):
        t=dict(reward=np.array([0.,0]),next_index=np.array([1,1]),terminal=np.array([False,True]))
        with self.assertRaises(ValueError):bootstrap_targets(Constant(),self.boards(['train','validation']),[0],t)
    def test_unknown_external_nonterminal_rejected(self):
        t=dict(reward=np.array([0.]),next_index=np.array([99]),terminal=np.array([False]))
        with self.assertRaises(ValueError):bootstrap_targets(Constant(),self.boards(['train']),[0],t)
    def test_same_seed_same_initial_weights(self):
        torch.manual_seed(12);a=GeometryValueNetwork();torch.manual_seed(12);b=GeometryValueNetwork()
        self.assertEqual(fingerprint(a),fingerprint(b))
    def test_mixture_limits_are_convex(self):
        self.assertEqual(CONFIG['td_weights']['MC'],0);self.assertEqual(CONFIG['td_weights']['TD'],1)
        self.assertTrue(all(0<=v<=1 for v in CONFIG['td_weights'].values()))
    def test_policy_subset_excludes_time_cap_and_other_rollout(self):
        s=dict(ai_mode='mcts',candidate_count=5,mcts_iterations=128,mcts_max_depth=4)
        self.assertTrue(homogeneous(s));self.assertFalse(homogeneous(dict(s,mcts_collection_budget=True)));self.assertFalse(homogeneous(dict(s,rollout_policy='geometric')));self.assertFalse(homogeneous({}))
    def test_episode_and_group_boundaries(self):
        r=[dict(episode='e',group='g',split='train',score=0,target=1,game_over=False),dict(episode='other',group='g',split='train',score=1,target=0,game_over=True)]
        with self.assertRaises(ValueError):n_step_pairs(r,[0,1],3,natural_go=True)
        r[1]['episode']='e';r[1]['group']='other'
        with self.assertRaises(ValueError):n_step_pairs(r,[0,1],3,natural_go=True)
    def test_macro_balances_games_inside_seed_group(self):
        r=[dict(episode='long' if i<3 else 'short',group='same_seed',target=0,score=0,wm_window='other') for i in range(4)]
        m=metrics(r,list(range(4)),[0,0,0,1000],dict(distance=np.array([5,5,5,5])))
        self.assertEqual(m['all']['mae'],250);self.assertEqual(m['group_macro_mae'],500)

if __name__=='__main__':unittest.main()
