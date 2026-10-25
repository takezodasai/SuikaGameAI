"""Audited STEP6 episode conversion and missing-aware value input schema. No Unity imports."""
import collections
import hashlib
import json
import math
from pathlib import Path
import random

SCORE_SCALE=1000.0
FRUIT_NAMES=[f"type_{i}" for i in range(11)]+["x","y","vx","vy","sin_angle","cos_angle","omega","has_collided","collision_known","half_width","half_height","size_known","offset_x","offset_y","offset_known","touching","touching_known","sleeping","sleeping_known"]
GLOBAL_NAMES=[f"held_{i}" for i in range(11)]+[f"next_{i}" for i in range(11)]+["held_present","next_known","held_x","held_y","held_y_known","score","cooldown","cooldown_known","move_speed","speed_known","fixed_dt","dt_known","count","game_over","geometry_known"]
INPUT_SPEC=dict(version="value-v1-missing-aware",fruit_names=FRUIT_NAMES,global_names=GLOBAL_NAMES,
    score_scale=SCORE_SCALE,velocity_scale=10.0,angular_scale_degrees=360.0,count_scale=64.0,
    fallback_world_scale=10.0,missing="zero + known flag; never inferred from current Prefabs",next_mask_index=23,game_over_index=35)

def digest(data):return hashlib.sha256(data).hexdigest()
def number(value):return type(value) in (int,float) and math.isfinite(value)
def integer(value):return type(value) is int

def geometry(row):
    p=row.get("info",{}).get("planning") or {};s=row['state'];r=p.get('drop_range') or s.get('drop_range') or {}
    values=[r.get('left_wall_inner'),r.get('right_wall_inner'),p.get('floor_y'),p.get('game_over_y')]
    if all(number(v) for v in values) and values[1]>values[0] and values[3]>values[2]:return values
    return None

def validate_episode(rows):
    """Reject ambiguous/partial episodes instead of manufacturing a final return."""
    if not rows or rows[0].get('event')!='episode_start':raise ValueError('missing episode_start')
    end=rows[-1]
    if end.get('event')!='episode_end':raise ValueError('unfinished episode')
    if end.get('game_over') is not True or end.get('truncated') is not False or end.get('reason')!='game_over':raise ValueError('not terminal game_over')
    final=end.get('final_score')
    if not integer(final) or end.get('conserved') is not True or end.get('state',{}).get('game_over') is not True or end['state'].get('score')!=final:raise ValueError('invalid terminal label')
    key=tuple(rows[0].get(k) for k in ('game_id','stream_id','episode_id'))
    score=rows[0]['state']['score'];seen=set();samples=[]
    for row in rows:
        if row.get('schema_version') not in (None,1,2):raise ValueError('unsupported episode schema')
        if tuple(row.get(k) for k in ('game_id','stream_id','episode_id'))!=key:raise ValueError('mixed episode')
        event=row['event']
        if event=='transition':
            action=row.get('action_id');info=row.get('info') or {};state=row['state']
            if not integer(action) or action<=0 or action in seen:raise ValueError('duplicate/invalid action')
            seen.add(action)
            if row.get('action_accepted',info.get('status')=='completed') is not True or info.get('status')!='completed':raise ValueError('unaccepted action')
            gap=row.get('between_steps_reward');reward=row.get('reward')
            if not integer(gap) or not integer(reward) or gap<0 or reward<0:raise ValueError('invalid rewards')
            if row.get('observed_before',{}).get('score')!=score:raise ValueError('stale score chain')
            score+=gap+reward
            if state.get('score')!=score or row.get('score')!=score or info.get('score_before')!=score-reward:raise ValueError('score not conserved')
            if state.get('episode_id')!=key[2] or state.get('stream_id')!=key[1] or state.get('game_id',key[0])!=key[0]:raise ValueError('mixed observation')
            ledger=state.get('reward_accounting')
            if ledger and (ledger.get('conserved') is not True or ledger.get('episode_score')!=score):raise ValueError('invalid Unity ledger')
            if final<score:raise ValueError('negative remaining score')
            samples.append(dict(state=state,geometry=geometry(row),target=final-score,action_id=action,
                policy=(info.get('planning') or {}).get('evaluation_version','unknown')))
        elif event=='terminal_observation':
            gap=row.get('between_steps_reward')
            if not integer(gap) or gap<0:raise ValueError('invalid terminal gap')
            score+=gap
            if score!=row['state']['score']:raise ValueError('terminal gap not conserved')
        elif event=='episode_end':
            tail=row.get('tail_between_steps_reward')
            if not integer(tail) or tail<0:raise ValueError('invalid tail reward')
            score+=tail
            if score!=final or score!=row.get('last_observed_score'):raise ValueError('tail not conserved')
        elif event!='episode_start':raise ValueError('error/unknown event in episode')
    if not samples:raise ValueError('no accepted transitions')
    if end.get('steps') is not None and end['steps']!=len(samples):raise ValueError('step count mismatch')
    return samples

def prepare(inputs,output,split_seed=2026,val_fraction=.25,test_fraction=0.,policy=None,go_ratio=None):
    if not 0<val_fraction<1 or not 0<=test_fraction<1 or val_fraction+test_fraction>=1:raise ValueError('Invalid validation/test fractions')
    out=Path(output).resolve()
    if out.exists():raise FileExistsError(out)
    manifests=set()
    for item in inputs:
        path=Path(item).resolve()
        if path.is_file() and path.name=='run.json':manifests.add(path)
        elif path.is_dir():manifests.update(path.rglob('run.json'))
        else:raise ValueError('Expected run directory, outputs directory, or run.json')
    records=[];episodes=[];seen=set();contents=set();environments={};sources=[];excluded=collections.Counter()
    for manifest_path in sorted(manifests):
        if any(word in manifest_path.parent.name.lower() for word in ('fixture','probe','smoke')):
            excluded['fixture/probe/smoke run']+=1;continue
        manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if not isinstance(manifest.get('workers'),list) or not manifest['workers']:continue
        sources.append(dict(path=str(manifest_path),sha256=digest(manifest_path.read_bytes())))
        for worker in manifest.get('workers',[]):
            path=manifest_path.parent/(worker['game_id']+'.jsonl')
            if not path.is_file():excluded['missing worker log']+=1;continue
            raw=path.read_bytes();sources.append(dict(path=str(path),sha256=digest(raw)))
            by_episode=collections.defaultdict(list);bad=set()
            lines=raw.decode('utf-8-sig').splitlines()
            for line_index,line in enumerate(lines):
                try:
                    row=json.loads(line);key=(row.get('game_id'),row.get('stream_id'),row.get('episode_id'))
                    by_episode[key].append(row)
                except (ValueError,AttributeError):
                    if line_index==len(lines)-1:
                        excluded['partial final line ignored']+=1;break
                    # Interior damage cannot be assigned safely to an episode.
                    bad.add('worker');excluded['invalid interior worker JSONL']+=1;break
            if bad:continue
            for key,rows in by_episode.items():
                uid='|'.join(str(k) for k in key)
                if uid in seen:excluded['duplicate episode']+=1;continue
                try:
                    if not all(isinstance(k,str) and k for k in key):raise ValueError('invalid episode identity')
                    samples=validate_episode(rows)
                    seed=rows[0].get('worker_seed',rows[0].get('seed',worker.get('seed')))
                    if not integer(seed):raise ValueError('missing seed group')
                    # Unknown physical optional fields stay missing; core kinematics must validate.
                    for sample in samples:encode(sample)
                except (ValueError,KeyError,TypeError) as error:excluded[str(error)]+=1;continue
                from .collection_audit import episode_signature, initial_sequence, load_environment
                signature=episode_signature(rows)
                if len(samples)>=8 and signature in contents:excluded['duplicate trajectory']+=1;continue
                versions=sorted({s['policy'] for s in samples})
                if policy and versions!=[policy]:excluded['policy filter']+=1;continue
                metadata=load_environment(manifest_path.parent,worker['game_id'])
                if metadata:
                    catalog=environments.setdefault(metadata['environment_id'],dict(environment=metadata['environment'],physics_profiles={}))
                    for profile_id,profile in metadata['physics_profiles'].items():
                        if profile_id in catalog['physics_profiles'] and catalog['physics_profiles'][profile_id]!=profile:raise ValueError('Conflicting physics profile')
                        catalog['physics_profiles'][profile_id]=profile
                    metadata_path=manifest_path.parent/'metadata'/(worker['game_id']+'.json')
                    sources.append(dict(path=str(metadata_path),sha256=digest(metadata_path.read_bytes())))
                if go_ratio is not None and (metadata is None or abs(metadata['environment']['game_over_screen_ratio']-go_ratio)>1e-5):
                    excluded['GO ratio missing/mismatch']+=1;continue
                for sample in samples:
                    if sample['state'].get('training_metadata_known') and metadata is None:raise ValueError('Missing environment catalog')
                    if metadata is not None:
                        if sample['state'].get('environment_id')!=metadata['environment_id']:raise ValueError('State/environment ID mismatch')
                        for fruit in sample['state']['fruits']:
                            if fruit.get('observation_metadata_known') and fruit.get('physics_profile_id') not in metadata['physics_profiles']:raise ValueError('Unresolved physics profile')
                        if sample['geometry'] is None:
                            env=metadata['environment'];r=sample['state'].get('drop_range') or {}
                            floors=[b for b in env['boundaries'] if b['role']=='floor']
                            candidate=[r.get('left_wall_inner'),r.get('right_wall_inner'),floors[0]['bounds_max']['y'] if floors else None,env.get('game_over_y')]
                            if all(number(v) for v in candidate):sample['geometry']=candidate
                seen.add(uid);contents.add(signature);group='worker_seed:'+str(seed)
                episodes.append(dict(id=uid,group=group,seed=seed,source=str(path),samples=len(samples),
                    final_score=rows[-1]['final_score'],policy_versions=sorted({s['policy'] for s in samples}),
                    rng_mode=rows[0].get('rng_mode','continuous_after_worker_seed'),initial_sequence=initial_sequence(rows),trajectory_sha256=signature,environment_id=metadata['environment_id'] if metadata else None,
                    terminal_provenance='logged game_over; legacy logs cannot prove absence of external fixture'))
                for sample_index,sample in enumerate(samples):
                    state=sample['state']
                    # Strip prediction candidates, old episode rewards and other label-bearing metadata.
                    minimal={k:state[k] for k in ('fruits','current_fruit','next_fruit_type','score','game_over','drop_cooldown_remaining','ai_move_speed','fixed_delta_time','environment_id','snapshot_fixed_time','snapshot_game_time','snapshot_realtime','snapshot_phase','merging_fruit_count','training_metadata_known') if k in state}
                    records.append(dict(episode=uid,group=group,seed=seed,state=minimal,geometry=sample['geometry'],
                        target=sample['target'],action_id=sample['action_id'],policy=sample['policy'],
                        steps_to_go=len(samples)-sample_index))
    # Union same seeds and identical observed 8-fruit prefixes; never split correlated episodes.
    from .collection_audit import correlation_groups
    membership=correlation_groups(episodes)
    for ep in episodes:ep['group']=membership[ep['id']]
    for row in records:row['group']=membership[row['episode']]
    groups=sorted(set(membership.values()));minimum=3 if test_fraction else 2
    if len(groups)<minimum:raise ValueError(f'Need at least {minimum} independent seed/initial-sequence groups; found {len(groups)}')
    random.Random(split_seed).shuffle(groups)
    nt=max(1,round(len(groups)*test_fraction)) if test_fraction else 0
    nv=max(1,round(len(groups)*val_fraction));nv=min(nv,len(groups)-nt-1)
    testing=set(groups[:nt]);validation=set(groups[nt:nt+nv])
    for row in records:row['split']='test' if row['group'] in testing else 'validation' if row['group'] in validation else 'train'
    for ep in episodes:ep['split']='test' if ep['group'] in testing else 'validation' if ep['group'] in validation else 'train'
    out.mkdir(parents=True,exist_ok=False)
    payload=''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in records).encode('utf-8')
    (out/'samples.jsonl').write_bytes(payload)
    report=dict(schema_version=2 if test_fraction else 1,environments=environments,input_spec=INPUT_SPEC,episodes=episodes,episode_count=len(episodes),sample_count=len(records),
        split_seed=split_seed,val_fraction=val_fraction,test_fraction=test_fraction,policy_filter=policy,go_ratio_filter=go_ratio,
        train_groups=sorted(set(groups)-validation-testing),validation_groups=sorted(validation),test_groups=sorted(testing),
        split_counts=dict(collections.Counter(r['split'] for r in records)),excluded=dict(excluded),sources=sources,
        samples_sha256=digest(payload),target='terminal final_score - this actual post-action score; no reward added again',
        limitations=['Behavior-policy Monte Carlo values, not optimal/MCTS values','8-fruit-prefix grouping cannot detect every related RNG stream','Unknown geometry/contacts stay masked','No solver cache; legacy GO provenance cannot be independently proved','Test excluded from training/early stopping; evaluate test only after freezing configuration'])
    (out/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def encode(sample,hide_next=False):
    """Pure Python features; no type->Prefab imputation. No IDs, seeds or labels as input."""
    state=sample['state'];geo=sample.get('geometry');known=bool(geo and len(geo)==4 and all(number(v) for v in geo) and geo[1]>geo[0] and geo[3]>geo[2])
    left,right,floor,go=geo if known else (0,10,0,10)
    width=right-left;height=go-floor
    def pos(x,y):return [(x-left)/width,(y-floor)/height]
    def flag(obj,key):
        known=obj.get('observation_metadata_known',True) if key in ('touching','sleeping') else True
        return [float(obj[key]),1.] if known and type(obj.get(key)) is bool else [0.,0.]
    fruits=[]
    for f in state['fruits']:
        kind=f.get('type')
        if not integer(kind) or not 0<=kind<11:raise ValueError('invalid fruit type')
        if not all(number(f.get(k)) for k in ('x','y','vx','vy','angle','angular_velocity')):raise ValueError('missing/nonfinite core fruit kinematics')
        angle=math.radians(f['angle']);vector=[float(i==kind) for i in range(11)]+pos(f['x'],f['y'])+[f['vx']/10,f['vy']/10,math.sin(angle),math.cos(angle),f['angular_velocity']/360]+flag(f,'has_collided')
        if f.get('collider_measurement_known',True) and all(number(f.get(k)) and f[k]>0 for k in ('half_width','half_height')):vector += [f['half_width']/width,f['half_height']/height,1.]
        else:vector += [0.,0.,0.]
        if f.get('collider_measurement_known',True) and all(number(f.get(k)) for k in ('collider_offset_x','collider_offset_y')):vector += [f['collider_offset_x']/width,f['collider_offset_y']/height,1.]
        else:vector += [0.,0.,0.]
        vector+=flag(f,'touching')+flag(f,'sleeping');fruits.append(vector)
    held=state.get('current_fruit') or {};present=held.get('present',True)
    if type(present) is not bool:raise ValueError('invalid held presence')
    kind=held.get('type');nxt=state.get('next_fruit_type');next_known=not hide_next and integer(nxt) and 0<=nxt<11
    if present and (not integer(kind) or not 0<=kind<11 or not number(held.get('x'))):raise ValueError('invalid held fruit')
    if not integer(state.get('score')) or type(state.get('game_over')) is not bool:raise ValueError('invalid score/GO')
    y_known=present and held.get('y_known',True) and number(held.get('y'))
    global_features=[float(present and i==kind) for i in range(11)]+[float(next_known and i==nxt) for i in range(11)]
    global_features += [float(present),float(next_known),(held['x']-left)/width if present else 0.,(held['y']-floor)/height if y_known else 0.,float(y_known),state['score']/SCORE_SCALE]
    for field,scale in [('drop_cooldown_remaining',1.),('ai_move_speed',10.),('fixed_delta_time',.02)]:
        valid=number(state.get(field));global_features += [state[field]/scale if valid else 0.,float(valid)]
    global_features += [len(fruits)/64.,float(state['game_over']),float(known)]
    if len(global_features)!=len(GLOBAL_NAMES) or any(len(v)!=len(FRUIT_NAMES) for v in fruits):raise AssertionError('feature schema mismatch')
    return fruits,global_features

def load_dataset(path):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'));raw=(path/'samples.jsonl').read_bytes()
    if manifest.get('schema_version') not in (1,2):raise ValueError('unsupported dataset schema')
    if digest(raw)!=manifest['samples_sha256'] or manifest['input_spec']!=INPUT_SPEC:raise ValueError('dataset/input schema hash mismatch')
    samples=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
    if len(samples)!=manifest['sample_count']:raise ValueError('sample count mismatch')
    membership={};seed_membership={};groups={'train':set(),'validation':set()}
    if manifest.get('test_groups'):groups['test']=set()
    for sample in samples:
        split=sample.get('split')
        if split not in groups or not number(sample.get('target')) or sample['target']<0:raise ValueError('invalid sample target/split')
        if sample['episode'] in membership and membership[sample['episode']]!=split:raise ValueError('episode leakage')
        membership[sample['episode']]=split;groups[split].add(sample['group'])
        if sample['seed'] in seed_membership and seed_membership[sample['seed']]!=split:raise ValueError('seed leakage')
        seed_membership[sample['seed']]=split
    if not all(groups.values()) or any(groups[a]&groups[b] for a in groups for b in groups if a!=b):raise ValueError('seed group leakage or empty split')
    fingerprint=digest((path/'manifest.json').read_bytes()+raw)
    return manifest,samples,fingerprint
