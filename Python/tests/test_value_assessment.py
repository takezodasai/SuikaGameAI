import copy,unittest
from test_value_data import state
try:
 from analyze_value_performance import score_only,masked_snapshot,cluster_intervals,board_shuffled
except ImportError:raise unittest.SkipTest('Use Python/.venv for assessment tests')

class AssessmentTests(unittest.TestCase):
 def sample(self,i):
  return dict(state=state(score=i),geometry=[-3,3,-4,3.3],episode=str(i),group=str(i),seed=i,target=10+i,action_id=1)
 def test_score_only_preserves_label_and_split_without_board_or_next(self):
  s=self.sample(1);before=copy.deepcopy(s);r=score_only(s)
  self.assertEqual(s,before);self.assertEqual(r['target'],s['target']);self.assertEqual(r['state']['score'],1)
  self.assertEqual(r['state']['fruits'],[]);self.assertEqual(r['state']['next_fruit_type'],-1)
 def test_missing_next_does_not_change_other_observed_inputs(self):
  s=self.sample(1);r=masked_snapshot(s,'unknown_next')
  self.assertEqual(r['state']['fruits'],s['state']['fruits']);self.assertEqual(s['state']['next_fruit_type'],2)
  self.assertEqual(r['state']['next_fruit_type'],-1)
 def test_cluster_bootstrap_perfect_prediction_is_zero(self):
  samples=[self.sample(i) for i in range(3)];truth=[s['target'] for s in samples]
  r=cluster_intervals(samples,truth,dict(equal=truth),repeats=20)
  self.assertEqual(r['groups'],3);self.assertEqual(r['mae'],dict(lower=0,upper=0));self.assertEqual(r['mae_reduction']['equal'],dict(lower=0,upper=0))
 def test_shuffle_keeps_count_global_and_uses_another_episode(self):
  samples=[self.sample(i) for i in range(3)]
  for i,s in enumerate(samples):s['state']['fruits'][0]['x']=i
  changed,indices=board_shuffled(samples)
  self.assertEqual(len(changed),3)
  for s,i in zip(changed,indices):
   self.assertEqual(s['state']['score'],samples[i]['state']['score']);self.assertNotEqual(s['state']['fruits'][0]['x'],samples[i]['state']['fruits'][0]['x'])

if __name__=='__main__':unittest.main()
