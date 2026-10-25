import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
from analyze_two_step_probe import trace_search
from compare_coverage_ai import settings

class PairCoverageTests(unittest.TestCase):
    def test_defaults_and_budget(self):
        self.assertEqual(validate_planning_settings({})['pair_coverage_iterations'],0)
        self.assertEqual(validate_planning_settings(settings('coverage15'))['mcts_iterations'],32)
    def test_invalid_settings(self):
        for patch in [dict(pair_coverage_iterations=-1),dict(pair_coverage_iterations=26),dict(pair_coverage_iterations=True),dict(mcts_iterations=10),dict(candidate_count=9),dict(mcts_max_depth=1),dict(execution_mode='frames'),dict(tree_policy='public_open_loop'),dict(expansion_policy='chance_decision'),dict(action_order_policy='shuffle'),dict(rollout_policy='guided')]:
            s=settings('coverage15');s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'fake.exe';exe.write_bytes(b'x')
            with self.assertRaises(ValueError):run_parallel(exe,p/'out',games=4,settings=settings('coverage15'))
            self.assertFalse((p/'out').exists())
    def fixture(self):
        root=[dict(visits=2 if i==0 else 1,immediate_go=False,drop_success=True) for i in range(5)]
        children=[dict(visits=int(i==0),arrivals=2 if i==0 else 1,actions=[dict(visits=int(i==0 and a==2)) for a in range(5)]) for i in range(5)]
        its=[dict(iteration=i,actions=[i%5,0 if i<5 else 2],chance_slots=[0,-1],reward=3+i,total_points=3+i,merges=0,game_over=False,depth=2,coverage_requested=True,coverage_forced_steps=[True,True],rollout_steps=[False,i<5]) for i in range(6)]
        return dict(decision=dict(settings=dict(candidate_count=5,pair_coverage_iterations=15,mcts_point_scale=55,mcts_exploration=2**.5)),report=dict(nodes=[dict(visits=6,arrivals=6,actions=root)]+children,iterations=its))
    def test_full_horizon_return_and_tree_counts_preserved(self):
        t=trace_search(self.fixture());self.assertEqual(t[5]['steps'][0]['x'],0);self.assertEqual(t[5]['steps'][1]['x'],.5)
    def test_schedule_corruption_rejected(self):
        r=self.fixture();r['report']['iterations'][5]['actions'][1]=0
        with self.assertRaisesRegex(ValueError,'schedule'):trace_search(r)
    def test_force_flags_or_request_corruption_rejected(self):
        for key,val in [('coverage_requested',False),('coverage_forced_steps',[True,False])]:
            r=self.fixture();r['report']['iterations'][0][key]=val
            with self.assertRaises(ValueError):trace_search(r)
    def test_only_budget_differs(self):
        a=settings('legacy');b=settings('coverage15');a.pop('pair_coverage_iterations');b.pop('pair_coverage_iterations');self.assertEqual(a,b)
