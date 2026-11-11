import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('candidate_value_compare',Path(__file__).parents[1]/'compare_candidate_value.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CandidateValueTests(unittest.TestCase):
    def test_order(self):
        r=module.rank_pairs([10,20,30],[1,2,3]);self.assertEqual(r['correct'],3)

    def test_reverse(self):
        self.assertEqual(module.rank_pairs([3,2,1],[1,2,3])['correct'],0)

    def test_target_ties_not_evidence(self):
        self.assertEqual(module.rank_pairs([1,2,3],[0,0,0])['comparable_pairs'],0)

    def test_predictive_ties_half_credit(self):
        self.assertEqual(module.rank_pairs([1,1],[10,20])['accuracy_with_half_credit_ties'],.5)

    def test_repeats_not_independent(self):
        base=dict(source='prediction_scene',fixture='f',x=.5,q_value=100,heuristic=2,first=dict(reward=3,game_over=False,drop_success=True,merges=1,physics_steps=26),game_over=False,completed_actions=6)
        rows=[dict(base,repeat=0,total_reward=10),dict(base,repeat=1,total_reward=10000),dict(base,repeat=0,total_reward=20)]
        r=module.aggregate(rows)[0];self.assertEqual(r['future_samples'],2);self.assertEqual(r['continuation_mean'],15);self.assertFalse(r['natural_go_verified'])

    def test_score_roughness_units(self):
        f=dict(reward=55,evaluation_features=dict(go_y=1,floor_y=0,left_x=0,right_x=1,fruits=[]))
        self.assertEqual(module.heuristic(f),55)

    def test_airborne_not_in_contacted_skyline(self):
        f=dict(reward=0,evaluation_features=dict(go_y=1,floor_y=0,left_x=0,right_x=1,fruits=[dict(contacted=False,top_y=99,min_x=0,max_x=1)]))
        self.assertEqual(module.heuristic(f),0)

    def test_unknown_next_is_averaged_not_maximized(self):
        row=dict(first=dict(reward=5,drop_success=True),after_first=dict(next_fruit_type=4,game_over=False),public_spawn_types=[0,0,2])
        with patch.object(module,'predict',side_effect=lambda model,kind,state:10*state['next_fruit_type']):
            q,_=module.expected_q(None,None,row)
        self.assertAlmostEqual(q,5+20/3);self.assertEqual(row['after_first']['next_fruit_type'],4)

    def test_pre_drop_go_has_no_new_next(self):
        row=dict(first=dict(reward=0,drop_success=False),after_first=dict(next_fruit_type=4,game_over=True),public_spawn_types=[0,1,2])
        with patch.object(module,'predict',return_value=0) as inference:
            q,values=module.expected_q(None,None,row)
        self.assertEqual(q,0);self.assertEqual(len(values),1);self.assertEqual(inference.call_count,1)


if __name__=='__main__':unittest.main()
