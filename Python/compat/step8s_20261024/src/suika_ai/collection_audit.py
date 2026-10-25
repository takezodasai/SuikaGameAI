"""Offline collection audit and correlation grouping. No Unity or training dependencies."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import statistics
from .collection_metadata import canonical


def load_environment(run,game):
    path=Path(run)/'metadata'/(game+'.json')
    if not path.is_file():return None
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('schema_version')!=1 or hashlib.sha256(canonical(value['environment'])).hexdigest()!=value['environment_id']:
        raise ValueError('Environment metadata hash mismatch: '+str(path))
    return value


def initial_sequence(rows,length=8):
    types=[]
    for row in rows:
        if row.get('event')!='transition':continue
        source=row.get('decision_source') or row.get('observed_before') or {}
        kind=(row.get('info',{}).get('planning') or {}).get('held_fruit_type',(source.get('current_fruit') or {}).get('type'))
        if type(kind) is not int or not 0<=kind<11:return None
        types.append(kind)
        if len(types)==length:return ','.join(map(str,types))
    return None


def episode_signature(rows):
    trajectory=[]
    for row in rows:
        if row.get('event')!='transition':continue
        state=row['state']
        fruits=sorted([tuple(f.get(k) for k in ('type','x','y','vx','vy','angle','angular_velocity','has_collided')) for f in state['fruits']])
        held=state.get('current_fruit') or {}
        trajectory.append([row.get('selected_x'),state['score'],state['game_over'],fruits,held.get('type'),held.get('x'),state.get('next_fruit_type')])
    return hashlib.sha256(canonical(trajectory)).hexdigest()


def correlation_groups(episodes):
    parents={ep['id']:ep['id'] for ep in episodes};seeds={};prefixes={}
    def root(k):
        while parents[k]!=k:parents[k]=parents[parents[k]];k=parents[k]
        return k
    def union(a,b):
        a,b=root(a),root(b)
        if a!=b:parents[max(a,b)]=min(a,b)
    for ep in episodes:
        uid=ep['id'];seed=ep['seed']
        if seed in seeds:union(uid,seeds[seed])
        seeds[seed]=uid
        prefix=ep.get('initial_sequence')
        if prefix:
            if prefix in prefixes:union(uid,prefixes[prefix])
            prefixes[prefix]=uid
    return {uid:root(uid) for uid in parents}


def manifests_under(inputs):
    found=set()
    for path in map(Path,inputs):
        if path.is_dir():found.update(path.rglob('run.json'))
        elif path.name=='run.json' and path.is_file():found.add(path)
        else:raise ValueError('Expected run/collection/outputs directory or run.json: '+str(path))
    return sorted(found)


def audit(inputs):
    from .parallel_play import validate_run
    from .value_data import validate_episode,encode
    details=[];issues=[];warnings=[];seed_uses=collections.defaultdict(list);seen=set();signatures={};duplicates=[]
    transitions=0;usable=0;policies=collections.Counter();environments=collections.Counter();field_counts=collections.Counter()
    run_count=0;log_bytes=0;throughputs=[]
    for manifest_path in manifests_under(inputs):
        manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if not manifest.get('workers'):continue
        run_count+=1
        try:validate_run(manifest_path.parent)
        except Exception as error:issues.append(dict(run=str(manifest_path.parent),error=str(error)))
        summary_path=manifest_path.parent/'summary.json'
        if summary_path.exists():
            rate=json.loads(summary_path.read_text()).get('collection_steps_per_second')
            if isinstance(rate,(int,float)):throughputs.append(rate)
        for worker in manifest['workers']:
            game=worker['game_id'];path=manifest_path.parent/(game+'.jsonl')
            if not path.exists():issues.append(dict(file=str(path),error='missing worker log'));continue
            log_bytes+=path.stat().st_size
            grouped=collections.defaultdict(list)
            with path.open(encoding='utf-8-sig') as file:
                for line_number,line in enumerate(file,1):
                    try:row=json.loads(line)
                    except ValueError:
                        # Only a partial final record may be ignored; interior corruption is fatal.
                        if file.read().strip():issues.append(dict(file=str(path),error=f'interior invalid JSON line {line_number}'))
                        else:warnings.append(dict(file=str(path),warning='incomplete final JSONL record'))
                        break
                    if row.get('event')=='worker_error':issues.append(dict(file=str(path),error=row.get('error')));continue
                    grouped[(row.get('game_id'),row.get('stream_id'),row.get('episode_id'))].append(row)
            try:metadata=load_environment(manifest_path.parent,game)
            except ValueError as error:issues.append(dict(file=str(path),error=str(error)));metadata=None
            for key,rows in grouped.items():
                uid='|'.join(str(v) for v in key)
                if uid in seen:duplicates.append(dict(episode=uid,file=str(path),kind='identity'));continue
                seen.add(uid);start=rows[0];end=rows[-1];seed=start.get('worker_seed',start.get('seed',worker.get('seed')))
                seed_uses[seed].append(dict(episode=uid,file=str(path),rng_mode=start.get('rng_mode','legacy_continuous')))
                count=sum(r.get('event')=='transition' for r in rows);transitions+=count
                status='incomplete';error=None;valid_samples=[]
                if end.get('event')=='episode_end':
                    status='game_over' if end.get('game_over') and not end.get('truncated') else 'truncated'
                if status=='game_over':
                    try:
                        if type(seed) is not int:raise ValueError("Missing seed group")
                        valid_samples=validate_episode(rows)
                        for sample in valid_samples:
                            encode(sample)
                            state=sample['state']
                            if state.get("training_metadata_known") and metadata is None:raise ValueError("Missing environment catalog")
                            if metadata:
                                if state.get('environment_id')!=metadata['environment_id']:raise ValueError('State/environment identity mismatch')
                                for fruit in state['fruits']:
                                    if fruit.get('observation_metadata_known') and fruit.get('physics_profile_id') not in metadata['physics_profiles']:raise ValueError('Missing runtime physics profile')
                        signature=episode_signature(rows)
                        if count>=8 and signature in signatures:
                            duplicates.append(dict(episode=uid,other=signatures[signature],kind='trajectory'));valid_samples=[]
                        signatures[signature]=uid
                    except Exception as exc:
                        error=str(exc);issues.append(dict(file=str(path),episode=uid,error=error));valid_samples=[];status='invalid'
                for row in rows:
                    if row.get('event')!='transition':continue
                    state=row['state']
                    for fruit in state['fruits']:
                        field_counts['board_fruits']+=1
                        field_counts['current_contact_known']+=int(fruit.get('observation_metadata_known') is True)
                        field_counts['sleep_known']+=int(fruit.get('observation_metadata_known') is True)
                        field_counts['collider_known']+=int(fruit.get('collider_measurement_known') is True)
                    field_counts['states']+=1;field_counts['held_y_known']+=int((state.get('current_fruit') or {}).get('y_known') is True)
                usable+=len(valid_samples)
                policy=sorted({(r.get('info',{}).get('planning') or {}).get('evaluation_version','unknown') for r in rows if r.get('event')=='transition'})
                for version in policy:policies[version]+=1
                ratio=metadata['environment'].get('game_over_screen_ratio') if metadata else None
                environments[str(ratio)]+=1
                details.append(dict(episode=uid,run=str(manifest_path.parent),game_id=game,seed=seed,status=status,
                    final_score=end.get('final_score') if status=='game_over' else None,steps=count,usable_states=len(valid_samples),
                    policy=','.join(policy),go_ratio=ratio,environment_id=metadata['environment_id'] if metadata else None,
                    initial_sequence=initial_sequence(rows),error=error))
    complete=[r for r in details if r['status']=='game_over'];scores=[r['final_score'] for r in complete]
    repeats={str(seed):uses for seed,uses in seed_uses.items() if len(uses)>1}
    groups=correlation_groups([dict(r,id=r['episode']) for r in details if type(r['seed']) is int])
    result=dict(schema_version=1,runs=run_count,episodes=len(details),completed_games=len(complete),
        truncated_games=sum(r['status']=='truncated' for r in details),incomplete_games=sum(r['status']=='incomplete' for r in details),
        average_score=statistics.mean(scores) if scores else None,max_score=max(scores) if scores else None,
        total_actions=transitions,usable_states=usable,log_bytes=log_bytes,policy_episode_counts=dict(policies),go_ratio_episode_counts=dict(environments),
        unique_seeds=len(seed_uses),duplicate_seeds=repeats,duplicate_episodes=duplicates,correlation_group_count=len(set(groups.values())),
        integrity_ok=not issues,issues=issues,warnings=warnings,field_coverage=dict(field_counts),episodes_detail=details,
        collection_steps_per_second=throughputs,
        note='Completed means validated natural GO; truncated/incomplete episodes have no final-score target. Repeated seeds are correlated, not independent samples.')
    return result


def save_audit(output,result):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if result['episodes_detail']:
        with (output/'episodes.csv').open('w',newline='',encoding='utf-8-sig') as file:
            writer=csv.DictWriter(file,fieldnames=list(result['episodes_detail'][0]));writer.writeheader();writer.writerows(result['episodes_detail'])
