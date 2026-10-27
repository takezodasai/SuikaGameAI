import json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from suika_ai.overnight_collection import settings,choose_job,DEFAULT_PROFILES,collect,audit_attempt,event_geometry
from suika_ai.unity_env import validate_planning_settings
from suika_ai.value_checkpoint import atomic_json
from test_value_data import episode

class OvernightTests(unittest.TestCase):
 def config(self,root):
  exe=Path(root)/'player';exe.write_bytes(b'fake-player-for-unit-tests')
  return dict(exe=str(exe),workers=2,hours=.001,max_jobs=4,max_steps=3,think_seconds=240,communication_timeout=720,game_seed=810000,schedule_seed=20261027,base_port=45100,profiles=DEFAULT_PROFILES,shutdown='boundary')
 def test_limits_opt_in_only(self):
  s=settings(dict(depth=16,iterations=32768),8191);self.assertEqual(s['mcts_time_limit_seconds'],240);self.assertEqual(s['mcts_budget_mode'],'fixed');self.assertFalse(s['mcts_auto_depth'])
  with self.assertRaises(ValueError):validate_planning_settings(dict(s,mcts_collection_budget=False))
  for change in [dict(mcts_max_depth=17),dict(mcts_auto_depth=True),dict(mcts_budget_mode='importance'),dict(mcts_time_limit_seconds=241)]:
   with self.assertRaises(ValueError):validate_planning_settings(dict(s,**change))
 def test_schedule_and_seeds_are_reproducible(self):
  c=dict(profiles=DEFAULT_PROFILES,schedule_seed=20261027,game_seed=810000,think_seconds=240)
  a=[choose_job(c,i) for i in range(1000)];self.assertEqual(a,[choose_job(c,i) for i in range(1000)]);self.assertEqual(len({x['game_seed'] for x in a}),1000)
  groups=[sum(x['profile']['depth']<=8 for x in a),sum(10<=x['profile']['depth']<=12 for x in a),sum(x['profile']['depth']>=14 for x in a)];self.assertTrue(550<groups[0]<650);self.assertTrue(250<groups[1]<350);self.assertTrue(60<groups[2]<140)
 def test_corner_geometry_and_unknown(self):
  e=dict(location=dict(position_known=True,collider_known=True,x=.6,y=.6,half_width=.5,half_height=.5));env=dict(boundaries=[dict(role='wall',bounds_max=dict(x=0),bounds_min=dict(x=-1)),dict(role='wall',bounds_max=dict(x=11),bounds_min=dict(x=10)),dict(role='floor',bounds_max=dict(y=0),colliders=[{}])]);v=event_geometry(e,env);self.assertTrue(v['corner']);self.assertAlmostEqual(v['bottom_aabb_gap'],.1);self.assertFalse(event_geometry({},env)['geometry_known'])
 def test_parallel_refill_and_resume_skip(self):
  with tempfile.TemporaryDirectory() as root:
   cfg=self.config(root);out=Path(root)/'collect';active=[0];peak=[0];lock=threading.Lock()
   def runner(c,j,slot,folder,stop):
    folder.mkdir();
    with lock:active[0]+=1;peak[0]=max(peak[0],active[0])
    time.sleep(.04)
    with lock:active[0]-=1
    r=dict(job=j['index'],game_seed=j['game_seed'],search_seed=j['search_seed'],natural_go=True,valid_for_return_learning=True,final_score=10,steps=3,errors=[],attempt=str(folder));atomic_json(folder.parent/(folder.name+'_result.json'),r);return r
   result=collect(cfg,out,runner=runner);self.assertEqual(peak[0],2);self.assertEqual(result['usable_games'],4)
   with patch('suika_ai.overnight_collection.run_job',side_effect=AssertionError('Must not replay')):
    result=collect({},out,True,runner=lambda *a:(_ for _ in ()).throw(AssertionError('Must not replay')))
   self.assertEqual(result['usable_games'],4);self.assertEqual(result['seed_duplicates'],0)
 def test_deadline_boundary_preserves_partial(self):
  with tempfile.TemporaryDirectory() as root:
   cfg=self.config(root);cfg['hours']=.00001;out=Path(root)/'collect'
   def runner(c,j,slot,folder,stop):
    folder.mkdir()
    while not stop.wait(.01):pass
    r=dict(job=j['index'],game_seed=j['game_seed'],natural_go=False,valid_for_return_learning=False,final_score=None,steps=1,errors=[],attempt=str(folder));atomic_json(folder.parent/(folder.name+'_result.json'),r);return r
   result=collect(cfg,out,runner=runner);self.assertEqual(result['jobs'],2);self.assertEqual(result['usable_games'],0)
 def test_720_deadline_includes_step_and_keeps_pending_on_timeout(self):
  from suika_ai.unity_env import UnityEnv
  from test_unity_env import state
  from test_planning import planned_reply
  for completion in (600, None):
   with UnityEnv(local=('127.0.0.1',0)) as env:
    env._action_episode='episode1';clock=[0.0];sent=[]
    def receive(timeout,**kwargs):
     if not kwargs:return state()
     clock[0]+=timeout
     if completion and clock[0]>=completion:return planned_reply()
     raise TimeoutError()
    with patch('suika_ai.unity_env.time.monotonic',side_effect=lambda:clock[0]),patch.object(env,'receive_state',side_effect=receive),patch.object(env,'_send',side_effect=lambda c:sent.append(c)):
     cfg=settings(dict(depth=16,iterations=32768),8191)
     if completion:
      _,_,_,info=env.plan_step(cfg,timeout=720);self.assertIsNone(env._pending_step);self.assertGreaterEqual(clock[0],600)
     else:
      with self.assertRaises(TimeoutError):env.plan_step(cfg,timeout=720)
      self.assertIsNotNone(env._pending_step);self.assertAlmostEqual(clock[0],720,places=3)
     self.assertLessEqual(len(sent),6)
 def test_drain_deadline_finishes_active_games(self):
  with tempfile.TemporaryDirectory() as root:
   cfg=self.config(root);cfg.update(hours=.00001,shutdown='drain');out=Path(root)/'collect'
   def runner(c,j,slot,folder,stop):
    folder.mkdir();time.sleep(.07);self.assertFalse(stop.is_set())
    r=dict(job=j['index'],game_seed=j['game_seed'],natural_go=True,valid_for_return_learning=True,final_score=10,steps=1,errors=[],attempt=str(folder));atomic_json(folder.parent/(folder.name+'_result.json'),r);return r
   result=collect(cfg,out,runner=runner);self.assertEqual(result['jobs'],2);self.assertEqual(result['usable_games'],2)
 def test_worker_exception_is_saved(self):
  from suika_ai.overnight_collection import run_job
  with tempfile.TemporaryDirectory() as root:
   cfg=self.config(root);folder=Path(root)/'job'/'attempt_000';folder.parent.mkdir();job=choose_job(cfg,0)
   with patch('suika_ai.overnight_collection.run_parallel',side_effect=TimeoutError('injected timeout')):result=run_job(cfg,job,0,folder,threading.Event())
   self.assertFalse(result['valid_for_return_learning']);self.assertIsNone(result['final_score']);self.assertIn('injected timeout',result['errors'][0]);self.assertTrue((folder.parent/'attempt_000_result.json').exists())
 def test_crash_after_game_end_recovers_without_replay(self):
  with tempfile.TemporaryDirectory() as root:
   cfg=self.config(root);cfg.update(max_jobs=1);out=Path(root)/'collect'
   out.mkdir();from suika_ai.overnight_collection import player_identity
   import hashlib
   cfg.update(exe_sha256=hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest(),player_files=player_identity(cfg['exe']))
   atomic_json(out/'collection.json',cfg);d=out/'jobs'/'job_000000';d.mkdir(parents=True);j=choose_job(cfg,0);atomic_json(d/'job.json',j);a=d/'attempt_000';a.mkdir();(a/'game_00.jsonl').write_text(json.dumps(dict(event='episode_end',reason='game_over'))+'\n')
   result=dict(job=0,game_seed=j['game_seed'],natural_go=True,valid_for_return_learning=True,final_score=10,steps=1,errors=[])
   with patch('suika_ai.overnight_collection.audit_attempt',return_value=result):r=collect({},out,True,runner=lambda *a:(_ for _ in ()).throw(AssertionError('Replay forbidden')))
   self.assertEqual(r['usable_games'],1);self.assertTrue(r['games'][0]['recovered_after_interruption'])
 def test_natural_go_and_error_audit(self):
  with tempfile.TemporaryDirectory() as root:
   folder=Path(root);rows=episode();p=rows[1]['info']['planning'];p.update(selected_x=.5,mcts=dict(nodes=[dict(depth=0,actions=[])],requested_iterations=32,completed_iterations=32,max_depth=4,elapsed_ms=1,budget_stop_reason='iteration_cap'));rows[1]['info'].update(drop_success=True,applied_normalized_x=.5)
   (folder/'game_00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));job=dict(index=0,game_seed=1,search_seed=1,profile=dict(depth=4,iterations=32),settings=dict(mcts_iterations=32))
   result=audit_attempt(folder,job);self.assertTrue(result['natural_go']);self.assertEqual(result['final_score'],10)
   rows[-1].update(game_over=False,truncated=True,reason='step_limit',final_score=None);(folder/'game_00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));result=audit_attempt(folder,job);self.assertFalse(result['valid_for_return_learning']);self.assertIsNone(result['final_score'])
if __name__=='__main__':unittest.main()
