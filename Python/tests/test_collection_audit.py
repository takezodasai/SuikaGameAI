import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from suika_ai.collection_audit import audit,correlation_groups,initial_sequence
from suika_ai.collection_metadata import CollectionMetadata
from suika_ai.value_data import prepare,load_dataset,encode
from test_value_data import episode,state


def write_run(root,index,seed=1,terminal=True,schema=2):
    run=root/f'run{index}';run.mkdir();rows=episode(seed)
    for row in rows:
        row['episode_id']=f'e{index}';row['state']['episode_id']=f'e{index}';row['schema_version']=schema
    rows[1]['observed_before']['episode_id']=f'e{index}'
    if not terminal:
        rows[-1].update(game_over=False,truncated=True,reason='step_limit',final_score=None);rows[-1]['state']['game_over']=False
    (run/'run.json').write_text(json.dumps(dict(workers=[dict(game_id='game_00',seed=seed)])))
    (run/'game_00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return run

class CollectionAuditTests(unittest.TestCase):
    def test_audit_real_go_vs_truncation_and_seed_repetition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_run(root,0,42);write_run(root,1,42);write_run(root,2,43,False)
            result=audit([root])
            self.assertTrue(result['integrity_ok']);self.assertEqual(result['completed_games'],2)
            self.assertEqual(result['truncated_games'],1);self.assertEqual(result['usable_states'],2)
            self.assertEqual(result['average_score'],10);self.assertEqual(result['total_actions'],3)
            self.assertEqual(len(result['duplicate_seeds']['42']),2)

    def test_reward_damage_is_not_training_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=write_run(root,0)
            path=run/'game_00.jsonl';rows=[json.loads(l) for l in path.read_text().splitlines()];rows[1]['reward']+=1
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows));result=audit([root])
            self.assertFalse(result['integrity_ok']);self.assertEqual(result['usable_states'],0)

    def test_seed_and_sequence_union_is_transitive(self):
        eps=[dict(id='a',seed=1,initial_sequence='0,1,2,3,4,0,1,2'),dict(id='b',seed=2,initial_sequence='0,1,2,3,4,0,1,2'),dict(id='c',seed=2),dict(id='d',seed=3)]
        groups=correlation_groups(eps)
        self.assertEqual(groups['a'],groups['c']);self.assertNotEqual(groups['a'],groups['d'])
        self.assertIsNone(initial_sequence(episode()))

    def test_three_way_split_policy_and_legacy_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(10):write_run(root,i,i//2,schema=1 if i%2 else 2)
            result=prepare([root],root/'data',val_fraction=.2,test_fraction=.2)
            self.assertEqual(set(result['split_counts']),{'train','validation','test'})
            manifest,records,_=load_dataset(root/'data')
            for seed in range(5):self.assertEqual(len({r['split'] for r in records if r['seed']==seed}),1)
            self.assertTrue(all(r['target']==3 for r in records))
            self.assertTrue(all('final_score' not in r['state'] for r in records))
            with self.assertRaises(ValueError):prepare([root],root/'filtered',policy='does-not-exist',test_fraction=.15)

    def test_new_false_values_not_mistaken_for_old_missing(self):
        s=state();s['fruits'][0].update(observation_metadata_known=True,touching=False,sleeping=True,collider_measurement_known=False)
        f,_=encode(dict(state=s));self.assertEqual(f[0][26:30],[0.,1.,1.,1.])
        s['fruits'][0]['observation_metadata_known']=False
        f,_=encode(dict(state=s));self.assertEqual(f[0][26:30],[0.,0.,0.,0.])

    def test_old_player_rejected_when_required(self):
        meta=CollectionMetadata(object(),'unused.json',require=True)
        with self.assertRaisesRegex(ValueError,'Old Player'):meta.attach(state())

    def test_new_catalog_is_preserved_and_geometry_restored(self):
        import hashlib
        from suika_ai.collection_metadata import canonical
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            env=dict(game_over_screen_ratio=.83,game_over_y=3.3,boundaries=[dict(role='floor',bounds_max=dict(y=-4.))])
            identity=hashlib.sha256(canonical(env)).hexdigest()
            capsule=dict(id='capsule-profile',body_known=True,mass=2.,inertia=.3,colliders=[dict(shape='CapsuleCollider2D',size=dict(x=1.,y=2.),offset=dict(x=0.,y=.1))])
            for i in range(3):
                run=write_run(root,i,i);(run/'metadata').mkdir()
                (run/'metadata/game_00.json').write_bytes(canonical(dict(schema_version=1,environment_id=identity,environment=env,physics_profiles={'capsule-profile':capsule})))
                path=run/'game_00.jsonl';rows=[json.loads(l) for l in path.read_text().splitlines()]
                for row in rows:
                    s=row['state'];s.update(training_metadata_known=True,environment_id=identity,drop_range=dict(left_wall_inner=-3.,right_wall_inner=3.))
                    s['fruits'][0].update(observation_metadata_known=True,physics_profile_id='capsule-profile',touching=False,sleeping=False)
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            prepare([root],root/'data',test_fraction=.15,go_ratio=.83)
            manifest,samples,_=load_dataset(root/'data')
            self.assertEqual(samples[0]['geometry'],[-3.,3.,-4.,3.3])
            self.assertEqual(manifest['environments'][identity]['physics_profiles']['capsule-profile']['colliders'][0]['shape'],'CapsuleCollider2D')

    def test_environment_reply_rejects_jsonutility_null_placeholder(self):
        from suika_ai.unity_env import UnityEnv
        env=UnityEnv.__new__(UnityEnv);sent=[];env._send=sent.append
        placeholder=dict(schema_version=1,unity_version='',build_guid='',fixed_delta_time=0,physics_profiles=[],boundaries=[])
        actual=dict(schema_version=1,unity_version='2022.3.21f1',build_guid='build',fixed_delta_time=.02,physics_profiles=[{}],boundaries=[{}])
        replies=iter([dict(environment=placeholder),dict(environment=actual)])
        env.receive_state=lambda timeout:next(replies)
        self.assertEqual(env.get_environment(),actual);self.assertEqual(len(sent),2)

    def test_external_test_requires_unseen_seed_and_initial_sequence(self):
        from suika_ai.value_train import external_test_context
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'run.json').write_text(json.dumps(dict(dataset='original-data')))
            original=dict(episodes=[dict(id='old',seed=1,split='train',initial_sequence='0,1,2,3,4,0,1,2',source='absent')])
            future=dict(episodes=[dict(id='new',seed=2,split='test',initial_sequence='1,1,2,3,4,0,1,2')])
            with patch('suika_ai.value_train.load_dataset',return_value=(original,[dict(target=17,split='train')],'fingerprint')):
                mean,context=external_test_context(root,future,[],dict(dataset_fingerprint='fingerprint'))
                self.assertEqual(mean,17);self.assertEqual(context['checked_initial_prefixes'],1)
                future['episodes'][0]['seed']=1
                with self.assertRaisesRegex(ValueError,'seeds'):external_test_context(root,future,[],dict(dataset_fingerprint='fingerprint'))
                future['episodes'][0]['seed']=2;future['episodes'][0]['initial_sequence']='0,1,2,3,4,0,1,2'
                with self.assertRaisesRegex(ValueError,'sequences'):external_test_context(root,future,[],dict(dataset_fingerprint='fingerprint'))

    def test_test_split_is_never_implicitly_evaluated(self):
        from suika_ai.value_train import evaluate
        samples=[dict(state=state(),geometry=None,split=split,target=target,episode=split,seed=i,action_id=1) for i,(split,target) in enumerate([('train',3),('validation',4),('test',999999)])]
        selected=[]
        def fake(model,items,**kwargs):selected.extend(s['split'] for s in items);return [2.]*len(items)
        with patch('suika_ai.value_train.predict',fake):
            result,_=evaluate(None,samples)
            self.assertNotIn('test',selected);self.assertNotIn('test',result['splits'])
            result,_=evaluate(None,samples,splits=('test',))
            self.assertEqual(result['baseline_training_mean'],3);self.assertEqual(result['splits']['test']['model']['n'],1)

if __name__=='__main__':unittest.main()
