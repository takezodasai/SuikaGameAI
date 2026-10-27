"""STEP8-AC streaming, audited actual-game dataset; never starts Unity."""
from collections import Counter,defaultdict
import hashlib,json,random
from pathlib import Path
import numpy as np
from .value_data import encode,validate_episode,geometry,INPUT_SPEC
from .collection_audit import load_environment,episode_signature,initial_sequence,correlation_groups

ROOT_PREFIXES=('budget_compare_','placement_long_','allocation_compare_','importance_stable_','legacy_sync_')
STATE_FIELDS=('fruits','current_fruit','next_fruit_type','score','game_over','drop_cooldown_remaining','ai_move_speed','fixed_delta_time','environment_id','game_id','episode_id','stream_id','training_metadata_known')

def physical_identity(environment):
    value={k:v for k,v in environment.items() if k not in ('unity_version','application_version','build_guid','limitation','game_over_rule','units')}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def tail(path):
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-2000000));lines=f.read().splitlines()
    try:return json.loads(lines[-1])
    except (ValueError,IndexError):return {}

def slim(row):
    value={k:v for k,v in row.items() if k in ('schema_version','event','game_id','episode_id','stream_id','seed','worker_seed','rng_mode','action_id','action_accepted','selected_x','score','reward','between_steps_reward','game_over','truncated','reason','final_score','conserved','steps','tail_between_steps_reward','last_observed_score')}
    if 'state' in row:value['state']={k:v for k,v in row['state'].items() if k in STATE_FIELDS}
    if 'observed_before' in row:value['observed_before']={k:v for k,v in row['observed_before'].items() if k in ('score','current_fruit')}
    if 'decision_source' in row and isinstance(row['decision_source'],dict):value['decision_source']={'current_fruit':row['decision_source'].get('current_fruit')}
    if 'info' in row:
        info=row['info'];p=info.get('planning')or{}
        value['info']={k:info[k] for k in ('status','score_before') if k in info}
        value['info']['planning']={k:p[k] for k in ('evaluation_version','held_fruit_type','drop_range','floor_y','game_over_y') if k in p}
    return value

def build(inputs,output,split_seed=20261027,old_manifest=None):
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    episodes=[];records=[];global_rows=[];offsets=[0];excluded=Counter();seen=set();signatures=set();sources=[];environments={};availability=Counter()
    with (out/'states.jsonl').open('w',encoding='utf-8') as states,(out/'fruits.f32').open('wb') as fruit_file:
        manifests=sorted({p for root in map(Path,inputs) for p in root.rglob('run.json')})
        for manifest_path in manifests:
            manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if not manifest.get('workers'):continue
            for worker in manifest['workers']:
                path=manifest_path.parent/(worker['game_id']+'.jsonl')
                if not path.exists():excluded['missing log']+=1;continue
                end=tail(path)
                if not(end.get('event')=='episode_end' and end.get('reason')=='game_over' and end.get('game_over') is True and end.get('truncated') is False):
                    excluded['not natural GO: '+str(end.get('event'))+'/'+str(end.get('reason'))]+=1;continue
                metadata=load_environment(path.parent,worker['game_id'])
                if not metadata or metadata['environment'].get('rules_version')!='step8e-all-fruit-go-v2' or abs(metadata['environment'].get('game_over_screen_ratio',0)-.83)>1e-5:
                    excluded['wrong or missing environment']+=1;continue
                identity=physical_identity(metadata['environment']);environments.setdefault(identity,metadata['environment'])
                by_episode=defaultdict(list);hash_value=hashlib.sha256();initial_size=path.stat().st_size;remaining=initial_size;stats=Counter();events=None;damaged=False
                with path.open('rb') as f:
                    while remaining:
                        raw=f.readline(remaining);remaining-=len(raw);hash_value.update(raw)
                        try:r=json.loads(raw)
                        except ValueError:damaged=True;break
                        if r.get('event')=='transition':
                            s=r['state'];stats['transitions']+=1
                            p=(r.get('info')or{}).get('planning')or{};m=p.get('mcts')or{}
                            if m.get('nodes'):stats['root_search_statistics']+=1
                            stats['held_known']+=int((s.get('current_fruit')or{}).get('present') is True)
                            stats['next_known']+=int(isinstance(s.get('next_fruit_type'),int) and s['next_fruit_type']>=0)
                            for fruit in s['fruits']:
                                stats['fruit_records']+=1
                                for key in ('touching','sleeping','has_collided','collider_measurement_known'):
                                    stats[key]+=int(key in fruit and (key!='collider_measurement_known' or fruit[key] is True))
                        if r.get('event')=='episode_end':events=r.get('state',{}).get('episode_events')
                        key=tuple(r.get(k) for k in ('game_id','stream_id','episode_id'));by_episode[key].append(slim(r))
                if damaged or path.stat().st_size!=initial_size:excluded['corrupt/changed file']+=1;continue
                sources.append(dict(path=str(path.resolve()),sha256=hash_value.hexdigest(),bytes=initial_size))
                for key,rows in by_episode.items():
                    uid='|'.join(map(str,key))
                    if uid in seen:excluded['duplicate episode']+=1;continue
                    try:
                        samples=validate_episode(rows);seed=rows[0].get('worker_seed',rows[0].get('seed',worker.get('seed')))
                        if type(seed) is not int:raise ValueError('missing seed')
                        for sample in samples:
                            if sample['state'].get('training_metadata_known') and sample['state'].get('environment_id')!=metadata['environment_id']:raise ValueError('state/catalog mismatch')
                            for fruit in sample['state']['fruits']:
                                if fruit.get('observation_metadata_known') and fruit.get('physics_profile_id') not in metadata['physics_profiles']:raise ValueError('missing physics profile')
                            if sample['geometry'] is None:
                                e=metadata['environment'];floor=next((b for b in e['boundaries'] if b['role']=='floor'),None);r=sample['state'].get('drop_range')or{}
                                # slim state excludes range: use immutable boundary/catalog geometry.
                                walls=[b for b in e['boundaries'] if b['role']=='wall']
                                left=max((b['bounds_max']['x'] for b in walls if b['bounds_max']['x']<0),default=None)
                                right=min((b['bounds_min']['x'] for b in walls if b['bounds_min']['x']>0),default=None)
                                if floor and left is not None and right is not None:sample['geometry']=[left,right,floor['bounds_max']['y'],e['game_over_y']]
                            encode(sample)
                        signature=episode_signature(rows)
                        if signature in signatures:raise ValueError('duplicate trajectory')
                    except (ValueError,KeyError,TypeError,StopIteration) as error:excluded[str(error)]+=1;continue
                    seen.add(uid);signatures.add(signature);start=len(records);settings=manifest.get('settings')or{}
                    policy='|'.join(str(settings.get(k,'legacy')) for k in ('ai_mode','mcts_budget_mode','mcts_iterations','mcts_max_iterations','candidate_count','mcts_widening','mcts_max_depth'))
                    ep=dict(id=uid,seed=seed,initial_sequence=initial_sequence(rows),samples=len(samples),final_score=rows[-1]['final_score'],source=str(path.resolve()),physical_environment=identity,policy=policy,
                        events=events if events and events.get('source')=='actual_game' and events.get('known') else None,start=start)
                    episodes.append(ep);availability.update(stats)
                    for index,sample in enumerate(samples):
                        f,g=encode(sample);array=np.asarray(f,dtype=np.float32).reshape(-1,30);fruit_file.write(array.tobytes());offsets.append(offsets[-1]+len(f));global_rows.append(g)
                        record=dict(episode=uid,seed=seed,score=sample['state']['score'],target=sample['target'],action_id=sample['action_id'],steps_to_go=len(samples)-index,policy=policy,
                            held_type=sample['state']['current_fruit'].get('type',-1),next_type=sample['state'].get('next_fruit_type',-1),game_over=sample['state']['game_over'],fruit_count=len(f),geometry=sample['geometry'])
                        records.append(record);states.write(json.dumps(dict(**record,state=sample['state']),ensure_ascii=False)+'\n')
                print(json.dumps(dict(file=str(path),accepted_games=len(episodes),states=len(records))),flush=True)
    if len(environments)!=1:raise ValueError('Multiple physical environments: split/model condition must be explicitly reviewed')
    membership=correlation_groups(episodes);groups=sorted(set(membership.values()))
    if len(groups)<12:raise ValueError('Need at least 12 seed/initial-sequence groups for this prototype')
    forced=set()
    if old_manifest:
        old=json.loads(Path(old_manifest).read_text(encoding='utf-8'));old_seen=[ep for ep in old['episodes'] if ep['split'] in ('train','validation')]
        seeds={ep['seed'] for ep in old_seen};prefixes={ep.get('initial_sequence') for ep in old_seen if ep.get('initial_sequence')}
        forced={membership[ep['id']] for ep in episodes if ep['seed'] in seeds or ep.get('initial_sequence') in prefixes}
    eligible=[g for g in groups if g not in forced];random.Random(split_seed).shuffle(eligible)
    nt=max(2,round(len(groups)*.15));nv=max(2,round(len(groups)*.15))
    if len(eligible)<nt+nv+1:raise ValueError('Not enough unseen groups for frozen-old-model holdout')
    testing=set(eligible[:nt]);validation=set(eligible[nt:nt+nv])
    split=lambda group:'test' if group in testing else 'validation' if group in validation else 'train'
    for ep in episodes:ep['group']=membership[ep['id']];ep['split']=split(ep['group'])
    for r in records:r['group']=membership[r['episode']];r['split']=split(r['group'])
    np.save(out/'offsets.npy',np.asarray(offsets,dtype=np.int64));np.save(out/'globals.npy',np.asarray(global_rows,dtype=np.float32));np.save(out/'targets.npy',np.asarray([r['target']/1000 for r in records],dtype=np.float32))
    (out/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}
    report=dict(version='long-value-ac-v1',input_spec=INPUT_SPEC,episodes=episodes,episode_count=len(episodes),sample_count=len(records),groups=len(groups),split_seed=split_seed,
        split_states=dict(Counter(r['split'] for r in records)),split_games=dict(Counter(ep['split'] for ep in episodes)),split_groups={s:len({ep['group'] for ep in episodes if ep['split']==s}) for s in ('train','validation','test')},
        forced_train_groups=sorted(forced),excluded=dict(excluded),availability=dict(availability),sources=sources,files=files,environments=environments,
        target='Observed natural-GO final score minus score at this actual post-action state; behavior-mixture return, not optimal return')
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report

def load(path):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text());
    if manifest.get('input_spec')!=INPUT_SPEC:raise ValueError('Unsupported base input specification')
    for name in ('records.jsonl','offsets.npy','globals.npy','targets.npy','fruits.f32'):
        expected=manifest.get('files',{}).get(name)
        if expected and hashlib.sha256((path/name).read_bytes()).hexdigest()!=expected:raise ValueError('Packed dataset hash mismatch: '+name)
    records=[json.loads(l) for l in (path/'records.jsonl').read_text().splitlines()]
    offsets=np.load(path/'offsets.npy');g=np.load(path/'globals.npy');y=np.load(path/'targets.npy')
    if len(records)!=manifest['sample_count'] or len(g)!=len(records) or len(y)!=len(records) or len(offsets)!=len(records)+1 or np.any(np.diff(offsets)<0):raise ValueError('Packed data shape mismatch')
    membership={};seeds={};groups={}
    for r in records:
        for table,key in ((membership,r['episode']),(seeds,r['seed']),(groups,r['group'])):
            if key in table and table[key]!=r['split']:raise ValueError('Split leakage')
            table[key]=r['split']
    if set(groups.values())!={'train','validation','test'}:raise ValueError('Missing split')
    if not np.isfinite(g).all() or not np.isfinite(y).all() or np.any(y<0):raise ValueError('Invalid feature/target')
    fruits=np.memmap(path/'fruits.f32',dtype=np.float32,mode='r',shape=(int(offsets[-1]),30))
    return manifest,records,offsets,g,y,fruits
