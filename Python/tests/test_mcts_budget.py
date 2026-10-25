import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compare_mcts_budget import settings,make_plan,pair_result,save,sha,completed,summarize,experiment_lock,percentile
class BudgetComparisonTests(unittest.TestCase):
 def test_only_iteration_count_changes(self):
  base=settings(32);self.assertFalse(base['mcts_common_chance']);self.assertEqual(base['pair_coverage_iterations'],0)
  for n in [64,128,256]:
   other=settings(n);base2=dict(base);base2['mcts_iterations']=n;self.assertEqual(base2,other)
 def test_invalid_budget(self):
  for n in [0,31,33,512]:
   with self.assertRaises(ValueError):settings(n)
 def test_unique_jobs_rotating_order(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'x';exe.write_bytes(b'x');p=make_plan([32,64,128,256],[100,101,102],8191,exe,3000,39200,False)
   self.assertEqual(len({j['key'] for j in p['jobs']}),12);self.assertEqual([j['iterations'] for j in p['jobs'][4:8]],[64,128,256,32]);self.assertEqual(p['step_timeout'],120)
 def test_invalid_plan_or_duplicate_seeds(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'x';exe.write_bytes(b'x')
   for budgets,seeds,limit,smoke in [([32,32],[1],8,True),([32,64],[1,1],8,True),([32,64],[1],9,True),([32,64],[1],0,False)]:
    with self.assertRaises(ValueError):make_plan(budgets,seeds,8191,exe,limit,39200,smoke)
 def ep(self,n,seed,score,natural=True):
  return dict(worker_errors=[],iterations=n,depth=4,seed=seed,search_seed=8191,errors=[] if natural else ['not_natural_go:step_limit'],natural_go=natural,termination='game_over' if natural else 'step_limit',final_score=score if natural else None,last_observed_score=score,public_series=[1,2,3],environment_id='env',exe_sha256='exe',operations=8,successful_drops=8,merges=2,maximum_fruit_type=4,planning_ms=dict(n=8,mean=100*n/32),planning_p95_ms=150,planning_total_seconds=n,game_wall_seconds=n+10,physical_ticks=n*200,search_go_samples=5,go_confusion=dict(false_negative=0,false_positive=0))
 def test_truncation_never_natural_pair(self):
  a=self.ep(32,1,100);b=self.ep(64,1,500,False);self.assertFalse(pair_result(a,b)['eligible']);self.assertIsNone(pair_result(a,b)['difference'])
 def test_fruit_sequence_and_environment_mismatch(self):
  a=self.ep(32,1,100);b=self.ep(64,1,200);b['public_series']=[1,2,4];self.assertIn('fruit_sequence_mismatch',pair_result(a,b)['reasons']);b['public_series']=a['public_series'];b['environment_id']='old';self.assertIn('environment_mismatch',pair_result(a,b)['reasons'])
 def test_completed_hash_prevents_modified_data(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);j=dict(key='job',seed=1,iterations=32);(root/'job').mkdir();data=root/'raw';data.write_text('original');save(root/'job/result.json',dict(job=j,episode=self.ep(32,1,100),hashes={'raw':sha(data)}));self.assertEqual(completed(root,j)['final_score'],100);data.write_text('changed')
   with self.assertRaises(ValueError):completed(root,j)
 def test_resume_skips_saved_and_preserves_attempts(self):
  from unittest.mock import patch
  from compare_mcts_budget import run
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);exe=root/'x';exe.write_bytes(b'x');plan=make_plan([32,64],[1],8191,exe,8,39200,True)
   for j in plan['jobs']:
    p=root/j['key'];p.mkdir(parents=True);save(p/'result.json',dict(job=j,episode=self.ep(j['iterations'],1,100),hashes={}))
   with patch('compare_mcts_budget.run_parallel') as launch:run(root,plan);launch.assert_not_called()
 def test_game_level_pair_summary_and_immutable_reports(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);jobs=[]
   for seed in [1,2,3]:
    for n in [32,64]:
     j=dict(key=f'{seed}/{n}',seed=seed,iterations=n);jobs.append(j);p=root/j['key'];p.mkdir(parents=True);save(p/'result.json',dict(job=j,episode=self.ep(n,seed,100+seed+(10 if n==64 else 0)),hashes={}))
   plan=dict(jobs=jobs,budgets=[32,64],seeds=[1,2,3],purpose='natural_go_comparison');r=summarize(root,plan);c=r['comparisons'][0];self.assertEqual(c['valid_pairs'],3);self.assertEqual(c['difference']['mean'],10);self.assertEqual(c['mean_difference_95ci'],[10,10]);self.assertEqual(c['wins_b'],3);summarize(root,plan);self.assertEqual(len(list((root/'reports').glob('*/comparison.json'))),2)
 def test_lock_prevents_duplicate_runner(self):
  with tempfile.TemporaryDirectory() as d:
   with experiment_lock(Path(d)):
    with self.assertRaises(RuntimeError):
     with experiment_lock(Path(d)):pass
   with experiment_lock(Path(d)):pass
 def test_percentile(self):self.assertAlmostEqual(percentile([10,20]),19.5);self.assertIsNone(percentile([]))

 def test_unfinished_job_gets_fresh_attempt(self):
  from unittest.mock import patch
  from compare_mcts_budget import run
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);exe=root/'x';exe.write_bytes(b'x');plan=make_plan([32,64],[1],8191,exe,8,39200,True)
   old=root/plan['jobs'][0]['key']/'attempt_000';old.mkdir(parents=True);(old/'keep').write_text('partial')
   def launch(exe,folder,**kw):
    folder.mkdir();save(folder/'run.json',{});(folder/'game_00.jsonl').write_text('preserved');(folder/'metadata').mkdir();save(folder/'metadata/game_00.json',{});return {}
   def audit(folder,n,seed):return self.ep(n,1,100,False)
   with patch('compare_mcts_budget.run_parallel',side_effect=launch) as worker,patch('compare_mcts_budget.audit_game',side_effect=audit):run(root,plan)
   self.assertEqual(worker.call_args_list[0].args[1].name,'attempt_001');self.assertEqual((old/'keep').read_text(),'partial')
 def test_invalid_optional_step_timeout(self):
  from suika_ai.parallel_play import run_parallel
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'x';exe.write_bytes(b'x')
   for t in [0,-1,float('nan'),True]:
    with self.assertRaises(ValueError):run_parallel(exe,Path(d)/'out',games=1,settings=settings(32),step_timeout=t)

 def test_failed_save_never_publishes_completion_marker(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'result.json'
   with self.assertRaises(ValueError):save(p,dict(bad=float('nan')))
   self.assertFalse(p.exists());save(p,dict(ok=True))
   with self.assertRaises(FileExistsError):save(p,dict(ok=False))
   self.assertTrue(json.loads(p.read_text())['ok'])
