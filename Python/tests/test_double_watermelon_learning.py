import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from double_watermelon_learning import completed_trace, samples, audit_trial, summarize, train, sha, bounded_records, validate_view


class CurriculumTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, natural=True, normal=True):
        s=dict(fruits=[],geometry=[-3,3,-4,3],current_fruit=dict(type=1,present=True),next_fruit_type=2,score=10,game_over=False)
        raw=dict(known=True,source='actual_game',events=[])
        root=dict(evt='root',state=s,score=10)
        cmd=dict(start_tick=1,x=.5)
        row=dict(evt='decision',state=s,score=10,command=cmd,planning=dict(selected_index=2,selected_x=.5),
            search=dict(completed_iterations=256,source_unchanged=True,root=[dict(x=x,visits=v) for x,v in zip([0,.25,.5,.75,1],[51,51,52,51,51])]),
            rollout=dict(model_sha256='actor'),raw_events=raw,new_watermelons=0,max_watermelons_present=1,double_watermelons=0)
        end=dict(evt='end',state=s,score=25,initial_score=10,additional_score=15,accepted_drops=1,
            natural_go=natural,truncated=not natural,reason='natural_go' if natural else 'drop_limit',
            raw_events=raw,new_watermelons=1,max_watermelons_present=2,two_watermelons_present=True,double_watermelons=0)
        rows=[root,row,dict(evt='release',command=cmd,state=s),end]
        cfg=dict(normal_start=normal,iterations=256,depth=4,actor_sha256='actor')
        if not normal:
            f=self.p/'fixture.json';f.write_text(json.dumps(dict(snapshot=s)));cfg['fixture']=str(f)
        (self.p/'config.json').write_text(json.dumps(cfg))
        (self.p/'result.json').write_text(json.dumps(dict(natural_go=natural,exit_code=0)))
        (self.p/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        return rows

    def rewrite(self, rows):
        (self.p/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def test_mc_uses_terminal_extra_score(self):
        self.fixture();rs=samples(self.p,7,'train','p','actor')
        self.assertEqual(rs[0]['return_points'],15)
        self.assertTrue(rs[0]['events']['new_watermelon'])
        self.assertFalse(rs[0]['events']['double'])

    def test_cap_and_unknown_exit_never_teacher(self):
        self.fixture(False)
        with self.assertRaises(ValueError):completed_trace(self.p)
        self.fixture();(self.p/'result.json').write_text(json.dumps(dict(natural_go=True,exit_code=None)))
        with self.assertRaises(ValueError):completed_trace(self.p)

    def test_actor_mismatch(self):
        self.fixture()
        with self.assertRaises(ValueError):completed_trace(self.p,'wrong')

    def test_iteration_mismatch(self):
        rs=self.fixture();rs[1]['search']['completed_iterations']=128;self.rewrite(rs)
        with self.assertRaises(ValueError):completed_trace(self.p)

    def test_partial_trace(self):
        self.fixture()
        with (self.p/'trace.jsonl').open('a') as f:f.write('{')
        with self.assertRaises(ValueError):completed_trace(self.p)

    def test_approximate_has_separate_provenance(self):
        self.fixture(normal=False);r=samples(self.p,7,'train','p','actor')[0]
        self.assertEqual(r['source_kind'],'approximate_curriculum')
        self.assertEqual(r['seed'],7)

    def test_bad_restore_rejected(self):
        rs=self.fixture(normal=False);rs[0]=copy.deepcopy(rs[0]);rs[0]['state']['score']=99;self.rewrite(rs)
        with self.assertRaises(ValueError):completed_trace(self.p)

    def test_missing_event_is_unknown(self):
        rs=self.fixture();rs[-1]['raw_events']['known']=False;self.rewrite(rs)
        self.assertIsNone(samples(self.p,7,'train','p')[0]['events']['double'])

    def test_already_coexisting_not_future_success(self):
        rs=self.fixture();rs[1]['max_watermelons_present']=2;self.rewrite(rs)
        self.assertIsNone(samples(self.p,7,'train','p')[0]['events']['two_present'])

    def test_undropped_decision_excluded(self):
        rs=self.fixture();rs=[r for r in rs if r['evt']!='release'];rs[-1]['accepted_drops']=0;self.rewrite(rs)
        self.assertEqual(samples(self.p,7,'train','p'),[])

    def test_invalid_attempt_keeps_score_null(self):
        self.fixture(False);r=audit_trial(self.p,0)
        self.assertFalse(r['natural_go']);self.assertIsNone(r['additional_score'])

    def test_empty_summary_not_zero_point_game(self):
        r=summarize(self.p)
        self.assertIsNone(r['normal']['mean_additional'])

    def test_train_never_overwrites_model(self):
        with self.assertRaises(FileExistsError):train(self.p,'unused',self.p)

    def training_fixture(self, collision=False):
        self.fixture();s=json.loads((self.p/'trace.jsonl').read_text().splitlines()[0])['state']
        records=[]
        for i in range(5):
            records.append(dict(sample=dict(state=s,geometry=s['geometry']),selected_index=2,visits=[51,51,52,51,51],
                return_points=i*10,seed=i,initial8='same' if collision else str(i),split='train' if i<3 else 'validation',
                episode=str(i),source_kind='normal',actual_iterations=256,depth=4,action_id=1,events=None))
        replay=self.p/'replay.jsonl';replay.write_text(''.join(json.dumps(r)+'\n' for r in records))
        (self.p/'manifest.json').write_text(json.dumps(dict(replay_sha256=sha(replay))))
        m=self.p/'parent.json';m.write_text(json.dumps(dict(version='candidate-linear213-v1',weights=[0]*213)))
        return m

    def test_small_training_saves_reloadable_separate_model(self):
        model=self.training_fixture();old=sha(model)
        r=train(self.p,model,self.p/'generation',epochs=1)
        self.assertEqual(sha(model),old)
        self.assertTrue((self.p/'generation/complete.json').exists())
        self.assertFalse(r['automatic_promotion'])
        self.assertEqual(r['event_labels']['double']['known'],0)

    def test_linked_seed_group_split_leak_rejected(self):
        model=self.training_fixture(collision=True)
        with self.assertRaisesRegex(ValueError,'Train/Validation'):train(self.p,model,self.p/'generation',epochs=1)

    def test_streaming_sample_keeps_boundaries_and_deduplicates(self):
        records=[dict(episode='a',action_id=i) for i in range(100)]
        a=bounded_records(records+records,limit=8)
        b=bounded_records(iter(records),limit=8)
        self.assertEqual(a,b);self.assertEqual(len(a),8)
        self.assertEqual(a[0]['action_id'],0);self.assertEqual(a[-1]['action_id'],99)

    def test_progress_learning_keeps_game_return_separate(self):
        model=self.training_fixture()
        p=self.p/'replay.jsonl';rs=[json.loads(s) for s in p.read_text().splitlines()]
        rs[0].update(progress_labels=dict(watermelon_melon=True),progress_observation_complete=True)
        p.write_text(''.join(json.dumps(r)+'\n' for r in rs));(self.p/'manifest.json').write_text(json.dumps(dict(replay_sha256=sha(p))))
        original=sha(p);r=train(self.p,model,self.p/'generation',epochs=1,progress_bonus_points=10)
        self.assertEqual(sha(p),original);self.assertEqual(r['learning_bonus']['states_with_bonus'],1)
        labels=[json.loads(s) for s in (self.p/'generation/learning_labels.jsonl').read_text().splitlines()]
        label=next(s for s in labels if s['episode']=='0')
        self.assertEqual(label['actual_game_return'],0);self.assertEqual(label['learning_bonus'],20)
        self.assertEqual(label['learning_return'],20)

    def test_partial_observation_is_not_used_for_shaping(self):
        model=self.training_fixture();p=self.p/'replay.jsonl';rs=[json.loads(s) for s in p.read_text().splitlines()]
        rs[0]['progress_labels']=dict(double_watermelon=True)
        p.write_text(''.join(json.dumps(r)+'\n' for r in rs));(self.p/'manifest.json').write_text(json.dumps(dict(replay_sha256=sha(p))))
        r=train(self.p,model,self.p/'generation',epochs=1,progress_bonus_points=10)
        self.assertEqual(r['learning_bonus']['states_with_bonus'],0)

    def test_view_is_single_game_and_batch_remains_parallel(self):
        validate_view(False,4,1000);validate_view(True,1,1)
        with self.assertRaises(ValueError):validate_view(True,4,1)
        with self.assertRaises(ValueError):validate_view(True,1,2)


if __name__=='__main__':unittest.main()
