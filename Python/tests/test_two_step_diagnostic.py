import json,copy,tempfile,unittest
from pathlib import Path
from analyze_two_step_probe import trace_search,analyze

class TwoStepDiagnosticTests(unittest.TestCase):
    def search(self):
        actions=[dict(visits=1,immediate_go=False,drop_success=True),dict(visits=1,immediate_go=False,drop_success=True)]
        report=dict(nodes=[dict(visits=2,arrivals=2,actions=actions),dict(visits=0,arrivals=1,actions=[dict(visits=0)]*2),dict(visits=0,arrivals=1,actions=[dict(visits=0)]*2)],iterations=[dict(iteration=i,actions=[i,1-i],chance_slots=[0,-1],reward=3+i,merges=1,game_over=False,depth=2,total_points=3+i) for i in range(2)])
        return dict(report=report,decision=dict(settings=dict(candidate_count=2,mcts_point_scale=55,mcts_exploration=2**.5)))
    def test_expansion_then_random_rollout_not_child_selection(self):
        ts=trace_search(self.search())
        for t in ts:self.assertEqual([s['phase'] for s in t['steps']],['expansion','rollout']);self.assertEqual(t['steps'][0]['next_rollout_reason'],'expanded_edge_and_new_chance')
    def test_changed_root_action_rejected(self):
        r=self.search();r['report']['iterations'][0]['actions'][0]=1
        with self.assertRaisesRegex(ValueError,'UCT'):trace_search(r)
    def test_invented_tree_visits_rejected(self):
        r=self.search();r['report']['nodes'][1]['visits']=1
        with self.assertRaisesRegex(ValueError,'visit'):trace_search(r)
    def test_new_chance_on_revisit_still_rollout(self):
        r=self.search();m=r['report'];m['iterations'].append(dict(iteration=2,actions=[1,1],chance_slots=[1,-1],reward=9,merges=1,game_over=False,depth=2,total_points=9));m['nodes'][0].update(visits=3,arrivals=3);m['nodes'][0]['actions'][1]['visits']=2;m['nodes'].append(dict(visits=0,arrivals=1,actions=[dict(visits=0)]*2))
        t=trace_search(r)[-1];self.assertEqual(t['steps'][0]['phase'],'selection_replay');self.assertEqual(t['steps'][0]['next_rollout_reason'],'new_chance');self.assertEqual(t['steps'][1]['phase'],'rollout')
    def fixture(self):
        ps=[dict(first_index=i,second_index=j,first_x=i/8,second_x=j/8,first_reward=0,second_reward=3,total_reward=3,first_ticks=25,second_ticks=25,ticks=50,prefix_match=True,first_go=False,game_over=False,first_drop=True,second_drop=True,terminal_excess=0) for i in range(9) for j in range(9)]
        return dict(policy='exhaustive-nine',fixture='fixed',initial=dict(score=10,current_fruit=dict(type=0),next_fruit_type=1),initial_build_ms=1,exhaustive=dict(outcomes=ps,selected_path=0,root_unchanged=True,live_unchanged=True,random_unchanged=True))
    def run_fixture(self,row):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.jsonl';p.write_text(json.dumps(row));return analyze(p)
    def test_all_81_and_later_reward_retained(self):self.assertEqual(self.run_fixture(self.fixture())['known_pair']['total_reward'],3)
    def test_missing_path_rejected(self):
        r=self.fixture();r['exhaustive']['outcomes'].pop()
        with self.assertRaisesRegex(ValueError,'grid'):self.run_fixture(r)
    def test_double_count_and_drop_after_go_rejected(self):
        r=self.fixture();r['exhaustive']['outcomes'][0]['total_reward']=6
        with self.assertRaisesRegex(ValueError,'conservation'):self.run_fixture(r)
        r=self.fixture();r['exhaustive']['outcomes'][0]['first_go']=True
        with self.assertRaisesRegex(ValueError,'after first GO'):self.run_fixture(r)
    def test_terminal_high_reward_cannot_win(self):
        r=self.fixture();r['exhaustive']['outcomes'][0].update(game_over=True,total_reward=100,second_reward=100);r['exhaustive']['selected_path']=1
        self.assertEqual(self.run_fixture(r)['exhaustive']['selected_path'],1)
    def test_wrong_best_path_rejected(self):
        r=self.fixture();r['exhaustive']['selected_path']=1
        with self.assertRaisesRegex(ValueError,'best-path'):self.run_fixture(r)
