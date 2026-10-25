import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from adaptive_profiles import profile,PROFILES,audit_decision
from suika_ai.unity_env import validate_planning_settings
from compare_adaptive_mcts import make_plan
from compare_mcts_budget import pair_result
class AdaptiveMctsTests(unittest.TestCase):
 def test_default_off_and_single_feature_profiles(self):
  a=profile('legacy');self.assertEqual(a['mcts_iterations'],32);self.assertEqual(a['mcts_max_depth'],4);self.assertEqual(a['mcts_budget_mode'],'fixed');self.assertFalse(a['mcts_widening'])
  changes={'time':{'mcts_budget_mode'},'adaptive':{'mcts_budget_mode'},'grid9':{'candidate_count'},'widening':{'mcts_widening'}}
  for name,expected in changes.items():self.assertEqual({k for k,v in profile(name).items() if v!=a[k]},expected)
 def test_time_depth_candidate_independence(self):
  for depth in [4,6,8]:
   s=profile('time',depth=depth,time_limit=60,max_iterations=4096,candidates=9);self.assertEqual(s['mcts_max_depth'],depth);self.assertEqual(s['candidate_count'],9);self.assertEqual(s['mcts_time_limit_seconds'],60)
 def test_invalid_modes_caps_thresholds(self):
  for patch in [dict(mcts_budget_mode='x'),dict(mcts_max_iterations=4097),dict(mcts_max_iterations=True),dict(mcts_time_limit_seconds=0),dict(mcts_time_limit_seconds=float('nan')),dict(adaptive_initial_iterations=300),dict(widening_max_candidates=32),dict(widening_min_spacing=0),dict(mcts_widening=1),dict(adaptive_max_terminal_rate=1.1)]:
   s=profile('adaptive');s.update(patch)
   with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
 def test_new_features_isolated_from_other_prototypes(self):
  for patch in [dict(execution_mode='frames'),dict(rollout_policy='guided'),dict(tree_policy='public_open_loop'),dict(action_order_policy='shuffle'),dict(pair_coverage_iterations=15),dict(expansion_policy='chance_decision'),dict(candidate_policy='coarse-root',candidate_count=7),dict(planning_budget_ms=10)]:
   s=profile('adaptive');s.update(patch)
   with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
 def test_widening_initial_five_only(self):
  with self.assertRaises(ValueError):profile('widening',candidates=9)
 def test_sequential_unique_plan(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'x';exe.write_bytes(b'x');opts=dict(iterations=32,depth=4,candidates=5,time_limit=5.,max_iterations=256,widen_after=10,widen_max=9,search_seed=8191)
   p=make_plan(['legacy','adaptive'],[1,2],exe,3000,39500,False,opts);self.assertEqual(len(p['jobs']),4);self.assertEqual([j['iterations'] for j in p['jobs']],['legacy','adaptive','adaptive','legacy']);self.assertIn('adaptive_profiles.py',p['python_sources'])
 def test_smoke_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'x';exe.write_bytes(b'x');opts=dict(iterations=32,depth=4,candidates=5,time_limit=5.,max_iterations=256,widen_after=10,widen_max=9,search_seed=8191)
   with self.assertRaises(ValueError):make_plan(['legacy','time'],[1],exe,9,39500,True,opts)
 def rows(self):
  p=Path(__file__).resolve().parents[1]/'outputs/step8t_01/fixed.jsonl'
  if not p.exists():self.skipTest('Native diagnostic not available')
  return [json.loads(l) for l in p.read_text(encoding='utf-8-sig').splitlines()]
 def test_actual_native_reports_and_public_chance(self):
  rows=self.rows()
  for r in rows:
   if not r['error']:audit_decision(dict(r['decision'],mcts=r['report']))
 def test_native_addition_corruption_rejected(self):
  r=next(r for r in self.rows() if r.get('report',{}).get('candidate_additions'));d=dict(r['decision'],mcts=r['report']);d=copy.deepcopy(d);d['mcts']['candidate_additions'][0]['x']=2
  with self.assertRaises(ValueError):audit_decision(d)
 def test_native_visit_corruption_rejected(self):
  r=next(r for r in self.rows() if not r['error']);d=copy.deepcopy(dict(r['decision'],mcts=r['report']));d['mcts']['nodes'][0]['actions'][0]['visits']+=1
  with self.assertRaises(ValueError):audit_decision(d)
 def test_native_budget_and_public_information_corruption_rejected(self):
  r=next(r for r in self.rows() if r['name']=='time' and not r['error']);d=copy.deepcopy(dict(r['decision'],mcts=r['report']));d['mcts']['iterations'][0]['public_observations'][0]='99:99'
  with self.assertRaises(ValueError):audit_decision(d)
 def test_truncated_never_valid_score_pair(self):
  a=dict(errors=['not_natural_go:stopped'],natural_go=False,final_score=None,public_series=[1,2],environment_id='x',exe_sha256='x');self.assertFalse(pair_result(a,a)['eligible'])
