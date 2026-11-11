import unittest
import json,tempfile
from pathlib import Path
from branch_pair_dataset import grouped_splits,evaluate,evaluate_learning_seeds,prepare_protocol


class BranchPairDatasetTests(unittest.TestCase):
    def row(self,seed,prefix,delta=10):
        return dict(root_uid=str(seed),input={},target=dict(mean_return_A=100,mean_return_B=100+delta),
                    provenance=dict(source_seed=seed,split_keys=[f'game_seed:{seed}',f'initial8:{prefix}']))
    def protocol(self):return dict(new_development_train=[1,2],new_development_validation=[3],prior_development_train=[])
    def test_connected_seed_or_initial_sequence_cannot_cross_splits(self):
        rows=[self.row(1,'a'),self.row(2,'a'),self.row(3,'b')];grouped_splits(rows,self.protocol())
        self.assertEqual(rows[0]['source_group'],rows[1]['source_group']);self.assertNotEqual(rows[0]['source_group'],rows[2]['source_group'])
        with self.assertRaises(ValueError):grouped_splits([self.row(1,'same'),self.row(3,'same')],self.protocol())
    def test_root_level_metrics_gain_regret_and_sign_convention(self):
        rows=[self.row(1,'a',20),self.row(3,'b',-10)];grouped_splits(rows,self.protocol())
        m=evaluate(rows,{'1':20,'3':-10});self.assertEqual(m['roots'],2);self.assertEqual(m['independent_source_groups'],2)
        self.assertEqual(m['ranking_accuracy'],1);self.assertEqual(m['mean_gain_vs_MCTS_A'],10)
        self.assertEqual(m['mean_regret_to_observed_best_of_two'],0);self.assertEqual(m['delta_MAE'],0)
        b=evaluate(rows,{'1':-1,'3':-1},False);self.assertEqual(b['ranking_accuracy'],.5);self.assertIsNone(b['delta_MAE'])
    def test_empty_split_is_unknown_not_zero_performance(self):
        m=evaluate([],{});self.assertIsNone(m['ranking_accuracy']);self.assertIsNone(m['mean_gain_vs_MCTS_A'])
    def test_repeated_roots_do_not_overweight_one_source_group(self):
        rows=[self.row(1,'a',20),self.row(1,'a',-10),self.row(3,'b',-10)]
        rows[0]['root_uid']='1a';rows[1]['root_uid']='1b';grouped_splits(rows,self.protocol())
        m=evaluate(rows,{'1a':20,'1b':20,'3':-10});self.assertEqual(m['ranking_accuracy'],.75)
        self.assertAlmostEqual(m['root_macro_ranking_accuracy'],2/3)
    def test_learning_seed_variation_without_fitting(self):
        rows=[self.row(1,'a',20)];grouped_splits(rows,self.protocol())
        m=evaluate_learning_seeds(rows,{11:{'1':20},12:{'1':-10}})
        self.assertEqual(m['learning_seeds'],2);self.assertEqual(m['fraction_roots_with_changed_choice'],1)
    def test_protocol_is_frozen_from_root_order_before_main_trials(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'plan.json').write_text(json.dumps(dict(roots=[dict(source_seed=i) for i in [1,2,3,4]])))
            proto=prepare_protocol(p,prior_seeds=[]);self.assertEqual(proto['new_development_train'],[1,2]);self.assertEqual(proto['new_development_validation'],[3,4])
            self.assertEqual(proto['independent_test'],[])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'plan.json').write_text(json.dumps(dict(roots=[])));(p/'tasks/a_f123_recommended').mkdir(parents=True)
            with self.assertRaises(ValueError):prepare_protocol(p,prior_seeds=[])


if __name__=='__main__':unittest.main()
