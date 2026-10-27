import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compare_allocation_mcts import settings,make_plan,audit_decision
from suika_ai.unity_env import validate_planning_settings
from compare_mcts_budget import completed,save,sha
class AllocationTests(unittest.TestCase):
 def test_only_allocation_differs(self):
  b=settings('adaptive5');c=settings('adaptive9')
  self.assertEqual({k for k in b if b[k]!=c[k]},{'mcts_widening','widening_policy'})
  self.assertFalse(c['mcts_auto_depth']);self.assertEqual(c['mcts_max_iterations'],512)
  self.assertEqual(settings('fixed128')['mcts_iterations'],128);self.assertEqual(settings('fixed256')['mcts_iterations'],256)
 def test_optin_bounds(self):
  for cap in [5,7,9,17,31]:self.assertEqual(validate_planning_settings(dict(settings('adaptive9'),widening_max_candidates=cap))['widening_max_candidates'],cap)
  for change in [dict(widening_policy='other'),dict(widening_max_candidates=8),dict(mcts_extended_budget=False),dict(mcts_widening=False)]:
   with self.assertRaises(ValueError):validate_planning_settings(dict(settings('adaptive9'),**change))
  self.assertEqual(validate_planning_settings({})['widening_policy'],'legacy')
 def test_order_and_limits(self):
  with patch('compare_allocation_mcts.sha',return_value='hash'),patch('compare_allocation_mcts.assembly_sha',return_value='assembly'):
   p=make_plan(4,763100,8191,Path('fake.exe'),3000,39920,False,20)
   self.assertEqual(len(p['jobs']),16)
   self.assertEqual(len({p['jobs'][i*4]['iterations'] for i in range(4)}),4)
   for n in [0,31]:
    with self.assertRaises(ValueError):make_plan(n,763100,8191,Path('fake.exe'),3000,39920,False,20)
 def test_completed_hash_no_duplicate(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);(r/'job').mkdir();(r/'log').write_text('data');job=dict(key='job',seed=1,iterations='adaptive9')
   self.assertIsNone(completed(r,job))
   save(r/'job/result.json',dict(job=job,episode={'natural_go':False},hashes={'log':sha(r/'log')}))
   self.assertFalse(completed(r,job)['natural_go'])
   (r/'log').write_text('changed')
   with self.assertRaises(ValueError):completed(r,job)
 def test_unvisited_not_stable_native_contract(self):
  # Production telemetry guard is validated natively; refuse compact forged success here.
  s=settings('adaptive9');d=dict(settings=s,same_source_verified=True,candidates=[{}]*5,selected_index=0,selected_x=0)
  root=[dict(visits=v,x=x) for v,x in zip([28,1,1,1,1],[0,.25,.5,.75,1])]
  d['mcts']=dict(completed_iterations=32,iteration_cap=512,source_unchanged=True,prefixes_match=True,max_depth=4,nodes=[dict(actions=root)],tree_policy='chance',rollout_policy='random',expansion_policy='legacy',common_chance=False,budget_stop_reason='adaptive_stable',elapsed_ms=1,time_limit_ms=20000,time_overrun_ms=0,budget_checkpoints=[dict(stable=True,candidate_guard_blocked=True)])
  with self.assertRaisesRegex(ValueError,'Pending candidate'):audit_decision(d)
