import unittest
from suika_ai.temporal_value_targets import n_step_pairs,td_target

class TemporalTargetsTests(unittest.TestCase):
    def rows(self):return [dict(episode='e',group='g',split='train',score=s,target=10-s,game_over=i==3) for i,s in enumerate([0,2,7,10])]
    def test_rewards_include_all_score_intervals(self):
        pairs=n_step_pairs(self.rows(),range(4),2,natural_go=True)
        self.assertEqual(pairs[0]['score_delta'],7);self.assertEqual(td_target(pairs[0],3),10)
    def test_terminal_has_no_bootstrap(self):
        p=n_step_pairs(self.rows(),range(4),20,natural_go=True)[0]
        self.assertTrue(p['terminal']);self.assertEqual(td_target(p,float('nan')),10)
    def test_censored_not_natural(self):
        with self.assertRaises(ValueError):n_step_pairs(self.rows(),range(4),3,natural_go=False)
    def test_missing_terminal_rejected(self):
        with self.assertRaises(ValueError):n_step_pairs(self.rows(),range(3),2,natural_go=True)
    def test_cross_seed_or_split_rejected(self):
        r=self.rows();r[1]['split']='test'
        with self.assertRaises(ValueError):n_step_pairs(r,range(4),2,natural_go=True)
    def test_inconsistent_mc_rejected(self):
        r=self.rows();r[1]['target']+=1
        with self.assertRaises(ValueError):n_step_pairs(r,range(4),2,natural_go=True)

if __name__=='__main__':unittest.main()
