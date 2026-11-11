import unittest
from export_branch_teacher import example


class BranchExportTests(unittest.TestCase):
    def row(self):
        return dict(first_x=.37,natural_go=True,actual_return=200,new_watermelons=1,second_watermelon=True,
                    two_present=True,doubles=0,source_unchanged=True,all_iterations_correct=True,
                    root_id='r',source_seed=1,source_initial_sequence='1,2',split_keys=['game_seed:1'],
                    future_seed=99,continuation=dict(kind='legacy_mcts'),source='actual_experimental_continuation',
                    approximation='cold',trajectory='trace.jsonl')
    def state(self):
        return dict(fruits=[],current_fruit=dict(type=0),next_fruit_type=1,score=100,game_over=False,
                    drop_cooldown_remaining=0,ai_move_speed=3.75,fixed_delta_time=.02,geometry=[-3,3,-4,3],
                    future_seed=99,final_score=300,rng='not_public')
    def test_future_and_final_results_are_not_model_inputs(self):
        r=example(self.row(),self.state(),True)
        self.assertEqual(r['input']['normalized_x'],.37);self.assertTrue(r['eligible_observed_return'])
        for k in ['future_seed','final_score','rng']:self.assertNotIn(k,r['input']['state'])
        self.assertEqual(r['provenance']['future_seed'],99)
    def test_truncated_outcome_is_unknown_not_failure_or_zero(self):
        g=self.row();g.update(natural_go=False,actual_return=None)
        r=example(g,self.state(),True);self.assertFalse(r['eligible_observed_return'])
        self.assertFalse(r['labels']['outcome_known']);self.assertIsNone(r['labels']['additional_score'])
        self.assertIsNone(r['labels']['second_watermelon'])
    def test_noncomparable_pair_not_eligible(self):
        self.assertFalse(example(self.row(),self.state(),False)['eligible_observed_return'])


if __name__=='__main__':unittest.main()
