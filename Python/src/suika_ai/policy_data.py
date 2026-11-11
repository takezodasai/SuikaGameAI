"""Frozen completed-game policy data. This module never calls collector/audit writers."""
from collections import Counter,defaultdict
import hashlib,json,math,random
from pathlib import Path
import numpy as np
from .value_data import encode,validate_episode,INPUT_SPEC
from .long_value_data import tail,slim,physical_identity
from .collection_audit import load_environment,correlation_groups,episode_signature,initial_sequence
from .learning_events import extract

VERSION='mcts-policy-v1'

def teacher(row):
    p=(row.get('info') or {}).get('planning') or {};m=p.get('mcts') or {};src=row.get('decision_source')
    if p.get('ai_mode')!='mcts' or not isinstance(src,dict):raise ValueError('missing MCTS decision source')
    if p.get('status')!='selected' or p.get('partial_plan') or not p.get('same_source_verified'):raise ValueError('unverified/partial plan')
    if src.get('episode_id')!=row['episode_id'] or src.get('state_id')!=p.get('source_state_id'):raise ValueError('decision source identity mismatch')
    if src.get('score')!=row['info'].get('score_before'):raise ValueError('decision source score mismatch')
    held=src.get('current_fruit') or {}
    if held.get('type')!=p.get('held_fruit_type') or src.get('next_fruit_type')!=p.get('next_fruit_type'):raise ValueError('public fruit mismatch')
    state=dict(fruits=src['fruits'],current_fruit=dict(held,present=True,y_known=False),next_fruit_type=src.get('next_fruit_type',-1),score=src['score'],game_over=False,
               fixed_delta_time=src.get('fixed_delta_time'),ai_move_speed=src.get('move_speed'))
    r=p.get('drop_range') or {};geo=[r.get('left_wall_inner'),r.get('right_wall_inner'),p.get('floor_y'),p.get('game_over_y')]
    sample=dict(state=state,geometry=geo);encode(sample)
    roots=[n for n in m.get('nodes',[]) if n.get('depth')==0]
    if len(roots)!=1:raise ValueError('missing/ambiguous root statistics')
    actions=roots[0].get('actions',[]);candidates=p.get('candidates',[])
    if len(actions)<2 or len(actions)!=len(candidates):raise ValueError('candidate count mismatch')
    xs=[a['x'] for a in actions];visits=[a['visits'] for a in actions];means=[a['mean_points'] for a in actions]
    if any(type(v) is not int or v<0 for v in visits) or sum(visits)!=m.get('completed_iterations') or not sum(visits):raise ValueError('invalid root visits')
    if any(not math.isfinite(x) or not 0<=x<=1 for x in xs+[]) or len(set(xs))!=len(xs) or not all(math.isfinite(q) for q in means):raise ValueError('invalid candidate data')
    for index,(a,c) in enumerate(zip(actions,candidates)):
        if a['index']!=index or c is None or abs(c['x']-a['x'])>1e-6:raise ValueError('root candidate order mismatch')
    selected=p['selected_index']
    if not 0<=selected<len(xs) or abs(xs[selected]-p['selected_x'])>1e-6:raise ValueError('selected candidate mismatch')
    if row['info'].get('drop_success') and abs(row['info']['applied_normalized_x']-xs[selected])>1e-4:raise ValueError('actual drop mismatch')
    return sample,dict(candidate_x=xs,visits=visits,mean_points=means,selected_index=selected,selected_x=xs[selected],actual_iterations=m['completed_iterations'],requested_iterations=m['requested_iterations'],depth=m['max_depth'],
        stop_reason=m.get('budget_stop_reason'),time_limit_ms=m.get('time_limit_ms'),thinking_ms=m.get('elapsed_ms'),search_seed=m.get('seed'),time_limit_reached=m.get('budget_stop_reason')=='time_limit',
        immediate_go=[a.get('immediate_go') for a in actions],quality_weight=min(2.,max(.5,math.sqrt(m['completed_iterations']/128))),quality_rule='clip(sqrt(actual_iterations/128),0.5,2); experimental weight, depth is metadata, not proof of quality')

def build(inventory,output,old_ac,old_tests,seed=20261028):
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    ac=json.loads(Path(old_ac).read_text());registry={e['id']:e for e in ac['episodes']};forbidden_seeds=set();forbidden_prefix=set()
    for path in [old_ac]+list(old_tests):
        m=json.loads(Path(path).read_text())
        for e in m.get('episodes',[]):
            if e.get('split')=='test':forbidden_seeds.add(e['seed']);forbidden_prefix.add(e.get('initial_sequence'))
    forbidden_prefix.discard(None)
    paths=sorted(set(json.loads(Path(inventory).read_text())));excluded=Counter();episodes=[];sources=[];seen=set();trajectories=set();identities=set();rows_encoded=[];records=[];offsets=[0];globals_=[]
    frozen_paths=[]
    for path in paths:
        p=Path(path)
        if not p.exists():excluded['missing log']+=1;continue
        end=tail(p)
        if not(end.get('event')=='episode_end' and end.get('reason')=='game_over' and end.get('game_over') is True and end.get('truncated') is False):excluded['incomplete/non-natural game at inventory freeze']+=1;continue
        uid='|'.join(str(end.get(k)) for k in ('game_id','stream_id','episode_id'))
        old=registry.get(uid)
        if old and (old['seed'] in forbidden_seeds or old.get('initial_sequence') in forbidden_prefix):excluded['historical Test group quarantined']+=1;continue
        frozen_paths.append(path)
    for path in frozen_paths:
        p=Path(path);size=p.stat().st_size;h=hashlib.sha256();valid=[];samples=[];bad=Counter()
        metadata=load_environment(p.parent,p.stem)
        if not metadata or metadata['environment'].get('rules_version')!='step8e-all-fruit-go-v2' or abs(metadata['environment'].get('game_over_screen_ratio',0)-.83)>1e-5:excluded['wrong/missing environment']+=1;continue
        try:
            with p.open('rb') as f:
                for raw in f:
                    h.update(raw);r=json.loads(raw);v=slim(r)
                    if r.get('state'):v['state']['episode_events']=r['state'].get('episode_events');v['state']['snapshot_fixed_time']=r['state'].get('snapshot_fixed_time')
                    valid.append(v)
                    if r.get('event')=='transition':
                        try:sample,t=teacher(r);samples.append((sample,dict(t,action_id=r['action_id'],post_state={k:r['state'][k] for k in ('fruits','current_fruit','next_fruit_type','score','game_over') if k in r['state']},reward=r['reward'],between_steps_reward=r.get('between_steps_reward'),post_future_points=r['state']['score'])))
                        except (ValueError,KeyError,TypeError) as e:bad[str(e)]+=1
            if p.stat().st_size!=size:raise ValueError('source changed during read')
            validate_episode(valid)
            from episode_events import audit_events
            audit_events(valid)
            start=valid[0];end=valid[-1];uid='|'.join(start[k] for k in ('game_id','stream_id','episode_id'));game_seed=start.get('worker_seed',start.get('seed'));prefix=initial_sequence(valid)
            if game_seed in forbidden_seeds or prefix in forbidden_prefix:raise ValueError('historical Test group quarantined')
            sig=episode_signature(valid)
            if uid in seen or sig in trajectories:raise ValueError('duplicate episode/trajectory')
            if not samples:raise ValueError('no usable policy samples')
            if any(s['state']['score']>end['final_score'] for s,_ in samples):raise ValueError('invalid future return')
        except (ValueError,KeyError,TypeError) as e:
            excluded[str(e)]+=1;print(json.dumps(dict(excluded_file=str(p),reason=str(e),sample_rejections=dict(bad))),flush=True);continue
        seen.add(uid);trajectories.add(sig);identity=physical_identity(metadata['environment']);identities.add(identity)
        ep=dict(id=uid,seed=game_seed,initial_sequence=prefix,source=str(p.resolve()),samples=len(samples),final_score=end['final_score'],natural_go=True,events=extract(valid),old_split=registry.get(uid,{}).get('split'),environment=identity)
        run=json.loads((p.parent/'run.json').read_text())
        ep.update(player_sha256=run.get('exe_sha256'),player_path=run.get('exe'),recording_version=(end.get('state',{}).get('episode_events')or{}).get('version'))
        episodes.append(ep);sources.append(dict(path=str(p.resolve()),sha256=h.hexdigest(),bytes=size,metadata=str((p.parent/'metadata'/(p.stem+'.json')).resolve())))
        for sample,t in samples:
            f,g=encode(sample);rows_encoded.extend(f);offsets.append(len(rows_encoded));globals_.append(g)
            t['post_future_points']=end['final_score']-t['post_future_points']
            records.append(dict(episode=uid,seed=game_seed,score=sample['state']['score'],fruit_count=len(f),final_score=end['final_score'],future_points=end['final_score']-sample['state']['score'],**t,sample=sample))
        excluded.update({'sample: '+k:v for k,v in bad.items()});print(json.dumps(dict(audited_games=len(episodes),samples=len(records),file=str(p))),flush=True)
    if len(identities)!=1:raise ValueError('Multiple physical environments; review required')
    members=correlation_groups(episodes);groups=defaultdict(list)
    for ep in episodes:groups[members[ep['id']]].append(ep)
    fresh=[g for g,eps in groups.items() if all(e['old_split'] is None for e in eps)]
    if len(fresh)<2:raise ValueError('Need at least two genuinely new seed groups for fresh Test')
    random.Random(seed).shuffle(fresh);test=set(fresh[:max(2,round(len(fresh)*.25))]);split={}
    for g,eps in groups.items():
        olds={e['old_split'] for e in eps}
        if 'test' in olds:raise ValueError('Historical test leakage')
        split[g]='test' if g in test else 'validation' if 'validation' in olds else 'train'
    if set(split.values())!={'train','validation','test'}:raise ValueError('Missing split')
    for e in episodes:e['group']=members[e['id']];e['split']=split[e['group']]
    for r in records:r['group']=members[r['episode']];r['split']=split[r['group']]
    # Keep labels/physics search metadata separate from strictly whitelisted input.
    with (out/'states.jsonl').open('w',encoding='utf-8') as f:
        for r in records:f.write(json.dumps(dict(episode=r['episode'],action_id=r['action_id'],split=r['split'],sample=r.pop('sample')),allow_nan=False)+'\n')
    (out/'records.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in records))
    np.savez(out/'features.npz',fruits=np.asarray(rows_encoded,dtype=np.float32).reshape(-1,30),offsets=np.asarray(offsets,dtype=np.int64),globals=np.asarray(globals_,dtype=np.float32))
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    report=dict(version=VERSION,input_spec=INPUT_SPEC,episodes=episodes,sample_count=len(records),episode_count=len(episodes),sources=sources,files=files,split_seed=seed,
        split_games=dict(Counter(e['split'] for e in episodes)),split_states=dict(Counter(r['split'] for r in records)),split_groups={s:sum(v==s for v in split.values()) for s in ('train','validation','test')},excluded=dict(excluded),historical_test_seeds=sorted(forbidden_seeds),
        split_note='Old AC Train/Validation preserved; historical Test groups excluded; fresh Test only from completed previously unused seed groups. Validation is reused development data, not a new holdout.',
        input_note='Exact decision_source; y/cooldown absent -> unknown flags. No post-state, visits, returns, seeds, future fruit, or search statistics are model inputs.')
    (out/'manifest.json').write_text(json.dumps(report,indent=2));return report

def load(path):
    path=Path(path);m=json.loads((path/'manifest.json').read_text())
    if m['version']!=VERSION or m['input_spec']!=INPUT_SPEC:raise ValueError('Unknown policy data schema')
    for file,sha in m['files'].items():
        if hashlib.sha256((path/file).read_bytes()).hexdigest()!=sha:raise ValueError('Dataset hash mismatch')
    rows=[json.loads(s) for s in (path/'records.jsonl').read_text().splitlines()]
    with np.load(path/'features.npz') as packed:data={k:packed[k] for k in packed.files}
    for key in ('seed','episode','group'):
        seen={}
        for r in rows:
            if r[key] in seen and seen[r[key]]!=r['split']:raise ValueError('Split leakage')
            seen[r[key]]=r['split']
    if len(rows)!=m['sample_count'] or len(data['offsets'])!=len(rows)+1 or len(data['globals'])!=len(rows):raise ValueError('Dataset shape mismatch')
    if any(not np.isfinite(data[k]).all() for k in ('fruits','globals')):raise ValueError('Nonfinite features')
    return m,rows,data
