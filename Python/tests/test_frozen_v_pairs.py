import unittest
from analyze_frozen_v_pairs import paired_ci,valid_game,percentile,attach_groups
from frozen_v_pair_experiment import reserve_collision,seed_plan

class FrozenVPairsTests(unittest.TestCase):
    def test_fixed_seed_plan_excludes_reserved_seeds(self):
        a,r=seed_plan();b,_=seed_plan();self.assertEqual(a,b);self.assertEqual(len(a),12);self.assertEqual(len(set(a)),12);self.assertFalse(set(a)&{e['seed'] for e in r})
    def test_prefix_guard_does_not_impute_missing_fruits(self):
        p=dict(reserved_prefixes=['0,1,2,3,4,0,1,2'])
        self.assertFalse(reserve_collision([0,1],p));self.assertTrue(reserve_collision([0,1,2,3,4,0,1,2],p))
    def test_bootstrap_resamples_groups_not_decisions(self):
        self.assertIsNone(paired_ci([10,20],['same','same'],100))
        self.assertEqual(paired_ci([50,50,50],['a','b','c'],100),[50.,50.])
        self.assertEqual(paired_ci([1,2,4],['a','b','c'],100),paired_ci([1,2,4],['a','b','c'],100))
    def test_censored_or_quarantined_is_not_valid_final_score(self):
        r=dict(natural_go=True,errors=[],score_conserved=True);m=dict(failure=None,quarantined=False)
        self.assertTrue(valid_game(r,m));self.assertFalse(valid_game(dict(r,natural_go=False),m));self.assertFalse(valid_game(r,dict(m,quarantined=True)))
    def test_p95_is_descriptive(self):self.assertAlmostEqual(percentile([0,10,20,30,40],95),38.)
    def test_shared_prefix_across_either_actor_clusters_seed_pairs(self):
        p=[dict(seed=1,initial8_C='a',initial8_D='b'),dict(seed=2,initial8_C='c',initial8_D='b'),dict(seed=3,initial8_C='d',initial8_D='e')]
        attach_groups(p);self.assertEqual(p[0]['group'],p[1]['group']);self.assertNotEqual(p[0]['group'],p[2]['group'])

if __name__=='__main__':unittest.main()
