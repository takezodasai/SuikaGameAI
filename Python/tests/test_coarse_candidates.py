import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
from analyze_two_step_probe import trace_search

class CoarseTests(unittest.TestCase):
    def settings(self):return dict(ai_mode='mcts',candidate_policy='coarse-root',candidate_count=7,mcts_max_depth=4)
    def test_defaults_and_opt_in(self):
        self.assertEqual(validate_planning_settings({})['candidate_policy'],'grid')
        self.assertEqual(validate_planning_settings(self.settings())['candidate_count'],7)
    def test_incompatible_options_rejected(self):
        for patch in [dict(candidate_count=5),dict(ai_mode='value'),dict(execution_mode='frames'),dict(tree_policy='public_open_loop'),dict(expansion_policy='chance_decision'),dict(action_order_policy='shuffle'),dict(rollout_policy='guided')]:
            s=self.settings();s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'fake.exe';exe.write_bytes(b'x')
            with self.assertRaises(ValueError):run_parallel(exe,p/'out',games=4,settings=self.settings())
            self.assertFalse((p/'out').exists())
    def fixture(self):
        xs=[0,.125,.25,.5,.625,.75,1]
        actions=[dict(x=x,visits=int(i==0),immediate_go=False,drop_success=True) for i,x in enumerate(xs)]
        child=dict(visits=0,arrivals=1,actions=[dict(visits=0) for i in range(5)])
        it=dict(iteration=0,actions=[0,4],chance_slots=[0,-1],action_x=[0,1],reward=3,merges=1,game_over=False,depth=2,total_points=3,rollout_steps=[False,True])
        return dict(decision=dict(settings=dict(candidate_policy='coarse-root',candidate_count=7,mcts_point_scale=55,mcts_exploration=2**.5)),report=dict(nodes=[dict(visits=1,arrivals=1,actions=actions),child],iterations=[it]))
    def test_seven_root_five_future(self):
        trace=trace_search(self.fixture());self.assertEqual(trace[0]['steps'][1]['x'],1)
    def test_future_outside_five_rejected(self):
        r=self.fixture();r['report']['iterations'][0]['actions'][1]=5
        with self.assertRaisesRegex(ValueError,'local candidate'):trace_search(r)
    def test_wrong_future_mapping_rejected(self):
        r=self.fixture();r['report']['iterations'][0]['action_x'][1]=4/6
        with self.assertRaisesRegex(ValueError,'mapping'):trace_search(r)
