import unittest
from audit_branch_repetitions import pair_statistics, physical_value, choose_index


class RepetitionAuditTests(unittest.TestCase):
    def test_repeated_measurements_not_independent_and_truncated_excluded(self):
        rows=[dict(return_A=100,return_B=120,delta_B_minus_A=20),
              dict(return_A=100,return_B=80,delta_B_minus_A=-20),
              dict(return_A=999,return_B=999,delta_B_minus_A=None)]
        result=pair_statistics(rows)
        self.assertEqual(result['valid_repetitions'],2)
        self.assertEqual(result['mean_return_A'],100)
        self.assertEqual(result['mean_delta'],0)
        self.assertEqual(result['B_wins'],1)
        self.assertTrue(result['replicate_rank_flip'])

    def test_observation_id_not_physical_error_but_position_and_ticks_are(self):
        a=dict(tick=5,state=dict(fruits=[dict(id=1,type=0,x=.2)]))
        b=dict(tick=5,state=dict(fruits=[dict(id=9,type=0,x=.2)]))
        self.assertEqual(physical_value(a),physical_value(b))
        b['state']['fruits'][0]['x']=.3
        self.assertNotEqual(physical_value(a),physical_value(b))

    def test_mean_and_legacy_visits_differ_and_reject_go(self):
        cs=[dict(index=0,visits=20,mean_points=10,drop_success=True,immediate_go=False),
            dict(index=1,visits=10,mean_points=20,drop_success=True,immediate_go=False),
            dict(index=2,visits=100,mean_points=100,drop_success=True,immediate_go=True)]
        self.assertEqual(choose_index(cs,'C_max_mean'),1)
        self.assertEqual(choose_index(cs,'D_max_visits'),0)


if __name__=='__main__':unittest.main()
