import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from rollout_selfplay import audit_trace,completed_job,summary,exclusive_lock
from rollout_experience_learning import from_trace,assign_groups,advantage_weights,train_generation

class SelfPlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.guard=patch('rollout_selfplay.reservations',return_value=(set(),set()));self.guard.start()
    def tearDown(self):self.guard.stop();self.tmp.cleanup()
    def fixture(self,terminal=True):
        state=dict(fruits=[],geometry=[-3,3,-4,3],current_fruit=dict(type=3,present=True),next_fruit_type=2,score=0,game_over=False)
        root=dict(evt='root',state=state,restoration='fresh_game_from_start_no_fixture',initial_score=0,score=0);rows=[root]
        for i in range(6):
            s=copy.deepcopy(state);s['score']=i;cmd=dict(start_tick=i+1,x=0);stats=[dict(x=x,index=j,visits=v,mean_points=0) for j,(x,v) in enumerate(zip([0,.25,.5,.75,1],[51,51,51,51,52]))]
            rows.append(dict(evt='decision',state=s,score=i,command=cmd,planning=dict(selected_x=0,selected_index=0),search=dict(completed_iterations=256,source_unchanged=True,root=stats,guided_calls=10,physics_ticks=1),rollout=dict(model_sha256='abc',rollout_calls=20,learned_calls=10,random_calls=10,fallback_calls=0),planning_ms=1))
            post=copy.deepcopy(s);post['next_fruit_type']=i%5;rows.append(dict(evt='release',state=post,score=i,command=cmd))
        rows.append(dict(evt='end',natural_go=terminal,truncated=not terminal,reason='natural_go' if terminal else 'drop_limit',score=21,accepted_drops=6,elapsed_seconds=1,new_watermelons=0,double_watermelons=0,state=state,raw_events=dict(source='actual_game',known=True,events=[])))
        (self.p/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));(self.p/'config.json').write_text(json.dumps(dict(mode='learned',normal_start=True,game_seed=1,search_seed=2,iterations=256,depth=4)));(self.p/'result.json').write_text(json.dumps(dict(natural_go=terminal,exit_code=0)))
        return rows
    def test_natural_vs_cap(self):
        self.fixture();job=dict(index=0,game_seed=1,search_seed=2);self.assertTrue(audit_trace(self.p,job,'abc')['valid_for_learning']);self.fixture(False);self.assertFalse(audit_trace(self.p,job,'abc')['valid_for_learning'])
    def test_unknown_exit_and_forced_stop_not_valid(self):
        self.fixture();job=dict(index=0,game_seed=1,search_seed=2);self.assertFalse(audit_trace(self.p,job,'abc',exit_code=None)['valid_for_learning']);self.assertFalse(audit_trace(self.p,job,'abc',override='interrupted')['valid_for_learning'])
    def test_actual_terminal_extra_points(self):
        self.fixture();samples=from_trace(self.p,'abc');self.assertEqual(len(samples),6);self.assertEqual(samples[0]['return_points'],21);self.assertEqual(samples[-1]['return_points'],16)
    def test_bad_actor_rejected(self):
        self.fixture()
        with self.assertRaises(ValueError):from_trace(self.p,'different')
    def test_truncation_no_return_labels(self):
        self.fixture(False)
        with self.assertRaises(ValueError):from_trace(self.p,'abc')
    def test_retry_not_duplicate_sample(self):
        d=self.p/'jobs/job_000000';(d/'attempt_000').mkdir(parents=True);(d/'attempt_001').mkdir();a=dict(valid_for_learning=False,status='interrupted',natural_go=False);b=dict(valid_for_learning=True,status='natural_go',natural_go=True,final_score=12,new_watermelons=0,double_watermelons=0);(d/'attempt_000/result.json').write_text(json.dumps(a));(d/'attempt_001/result.json').write_text(json.dumps(b));s=summary(self.p);self.assertEqual(s['natural_go'],1);self.assertEqual(s['mean_score'],12);self.assertTrue(completed_job(d,2))
    def test_interruption_retry_and_cap_done(self):
        (self.p/'attempt_000').mkdir();p=self.p/'attempt_000/result.json';p.write_text(json.dumps(dict(valid_for_learning=False,status='interrupted')));self.assertFalse(completed_job(self.p,2));p.write_text(json.dumps(dict(valid_for_learning=False,status='drop_limit')));self.assertTrue(completed_job(self.p,2))
    def test_exclusive_lock(self):
        with exclusive_lock(self.p/'lock'):
            with self.assertRaises(RuntimeError):
                with exclusive_lock(self.p/'lock'):pass
    def test_seed_or_prefix_union_and_fixed_split(self):
        def row(ep,seed,prefix):return dict(episode=ep,seed=seed,initial8=prefix,action_id=1,source_kind='selfplay',original_split=None)
        rs=[row('a',1,'p'),row('b',2,'p'),row('c',3,'q')];registry={}
        with patch('rollout_experience_learning.reservations',return_value=(set(),set())):
            out,_=assign_groups(rs,[],registry);self.assertEqual(out[0]['group'],out[1]['group']);old={r['episode']:r['split'] for r in out};out2,_=assign_groups(rs+[row('d',4,'r')],[],registry);self.assertTrue(all(r['split']==old[r['episode']] for r in out2 if r['episode'] in old))
    def test_crossfit_baseline_does_not_see_own_group_labels(self):
        rng=np.random.default_rng(3);x=rng.normal(size=(15,5,213));y=np.arange(15)*20.;g=np.repeat(np.arange(5),3);train=g<4;w=np.ones(15);a,p,b=advantage_weights(x,y,g,train,w);yy=y.copy();yy[g==0]+=1000;aa,pp,bb=advantage_weights(x,yy,g,train,w);np.testing.assert_allclose(p[g==0],pp[g==0]);self.assertTrue((a>=.5-1e-9).all() and (a<=2+1e-9).all());self.assertEqual(len(b['model']['coef']),53)
    def test_no_complete_selfplay_no_fake_generation(self):
        (self.p/'jobs').mkdir();m=self.p/'parent.json';m.write_text(json.dumps(dict(version='candidate-linear213-v1',weights=[0]*213)));r=train_generation(self.p,m);self.assertEqual(r['status'],'skipped_no_valid_selfplay');self.assertFalse((self.p/'generations').exists())

if __name__=='__main__':unittest.main()
