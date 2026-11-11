"""Append audited completed games to immutable policy-v1 data; protect past Tests."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,random
import numpy as np
from .policy_data import load,teacher,VERSION
from .value_data import encode,validate_episode
from .long_value_data import slim,tail,physical_identity
from .collection_audit import load_environment,correlation_groups,initial_sequence,episode_signature
from .learning_events import extract

def is_success(ep):return ep['events']['labels']['watermelon_one']['achieved'] is True

def assign_splits(episodes,seed=20261028):
    members=correlation_groups(episodes);groups=defaultdict(list)
    for e in episodes:groups[members[e['id']]].append(e)
    fresh=sorted(g for g,eps in groups.items() if all(e.get('previous_split') is None for e in eps))
    if len(fresh)<15:raise ValueError('Need >=15 new independent seed groups for this comparison')
    rng=random.Random(seed);rng.shuffle(fresh)
    # Select Test without looking at success or scores. Freeze it before enrichment.
    nt=max(3,round(len(fresh)*.2));test=set(fresh[:nt]);remaining=fresh[nt:]
    nv=max(3,round(len(fresh)*.15));natural=set(remaining[:nv]);remaining=remaining[nv:]
    def successful(g):return any(is_success(e) for e in groups[g])
    val_success=sum(successful(g) for g in natural);enriched=set()
    for g in remaining:
        if val_success>=3:break
        if successful(g):enriched.add(g);val_success+=1
    assignments={};purposes={}
    for g,eps in groups.items():
        old={e.get('previous_split') for e in eps}
        if 'test' in old or 'historical_test' in old:role='historical_test';purpose='protected_not_evaluated'
        elif 'train' in old and 'validation' in old:raise ValueError('Old split history conflict')
        elif 'validation' in old:role='validation';purpose='legacy_natural'
        elif 'train' in old:role='train';purpose='legacy_train'
        elif g in test:role='test';purpose='fresh_random_outcome_blind'
        elif g in natural:role='validation';purpose='fresh_natural'
        elif g in enriched:role='validation';purpose='success_enrichment'
        else:role='train';purpose='fresh_train'
        assignments[g]=role;purposes[g]=purpose
    for e in episodes:e.update(group=members[e['id']],split=assignments[members[e['id']]],split_purpose=purposes[members[e['id']]])
    return dict(test_selection='Random fresh groups, before any success enrichment',new_groups=len(fresh),new_test_groups=nt,natural_validation_groups=nv,enriched_groups=len(enriched),validation_success_groups=val_success)

def future_labels(record,episode,positive_snapshots):
    """Observed-policy outcomes; never inputs. Preserve ambiguous event timing."""
    score=record['score'];drop=record.get('source_drop_count');snap=episode.get('terminal_events') or {};extended=snap.get('learning') or {}
    complete=bool(snap.get('known') and snap.get('source')=='actual_game');extra_complete=bool(complete and extended.get('known') and extended.get('version')=='learning-milestones-v1')
    mapping={'future_watermelon_created':['watermelon_created'],'future_watermelon_melon_one':['watermelon_melon_one'],'future_watermelon_melon_two':['watermelon_melon_two'],'future_watermelon_two':['two_watermelons_present','watermelon_two'],'future_double_watermelon':['double_watermelon']}
    history=(snap.get('events',[]) if complete else [])+(extended.get('events',[]) if extra_complete else [])
    targets={'additional_points':dict(known=True,value=episode['final_score']-score,provenance='natural_GO final_score - decision_source.score')}
    for name,kinds in mapping.items():
        events=[e for e in history if e['kind'] in kinds];future=False;ambiguous=False
        for e in events:
            if drop is not None and e['drop_count']!=drop:
                future|=e['drop_count']>drop
            elif e['score']>score:future=True
            elif e['score']==score:ambiguous=True
        # A later saved actual board is positive evidence of coexistence, never
        # negative evidence: transient success can occur between saved snapshots.
        evidence=positive_snapshots.get(name,[])
        sampled=any(a>=record['action_id'] for a in evidence)
        # A natural-GO terminal board is later than every nonterminal input in
        # this episode. Its presence is positive evidence; absence proves nothing.
        sampled|=episode.get('terminal_coexistence',{}).get(name) is True
        recording=extra_complete if '_melon_' in name else complete
        known=future or sampled or (recording and not ambiguous)
        targets[name]=dict(known=bool(known),value=bool(future or sampled) if known else None,provenance='future callback / later actual snapshot positive evidence; unknown timing/absence stays masked')
    return targets

def export_value_targets(dataset,output,summary):
    """Separate labels for pre/post states; never edits the frozen policy dataset."""
    output=Path(output);summary=Path(summary)
    if output.exists() or summary.exists():raise FileExistsError('Value label output exists')
    m,rows,_=load(dataset);eps=json.loads(json.dumps({e['id']:e for e in m['episodes']}));positive=defaultdict(lambda:defaultdict(list))
    for e in eps.values():
        end=tail(Path(e['source']))
        if end.get('reason')!='game_over' or end.get('final_score')!=e['final_score']:raise ValueError('Terminal evidence changed')
        f=[x for x in end['state']['fruits'] if not x.get('is_merging')];w=sum(x['type']==10 for x in f);melons=sum(x['type']==9 for x in f)
        e['terminal_coexistence']={'future_watermelon_melon_one':w>=1 and melons>=1,'future_watermelon_melon_two':w>=1 and melons>=2,'future_watermelon_two':w>=2}
        for evidence in e['events'].get('snapshot_evidence',[]):
            key={'watermelon_melon_one':'future_watermelon_melon_one','watermelon_melon_two':'future_watermelon_melon_two'}.get(evidence['kind']);action=evidence.get('action_id')
            if key and type(action) is int:positive[e['id']][key].append(action)
    for r in rows:
        f=[x for x in r['post_state']['fruits'] if not x.get('is_merging')];w=sum(x['type']==10 for x in f);melons=sum(x['type']==9 for x in f)
        for name,condition in [('future_watermelon_melon_one',w>=1 and melons>=1),('future_watermelon_melon_two',w>=1 and melons>=2),('future_watermelon_two',w>=2)]:
            if condition:positive[r['episode']][name].append(r['action_id'])
    counts=defaultdict(Counter)
    with output.open('x') as f:
        for r in rows:
            for phase in ['decision_source','actual_post_action']:
                ep=eps[r['episode']];score=r['score'] if phase=='decision_source' else r['post_state']['score'];q=r if phase=='decision_source' else dict(score=score,action_id=r['action_id']+.5,source_drop_count=None)
                targets=future_labels(q,ep,positive[r['episode']])
                if phase=='actual_post_action' and r['post_state'].get('game_over') is True:
                    if score!=ep['final_score']:raise ValueError('Terminal score differs from final score')
                    targets={k:dict(known=True,value=0 if k=='additional_points' else False,provenance='Known terminal state: empty future interval') for k in targets}
                if score+targets['additional_points']['value']!=ep['final_score']:raise ValueError('Future point conservation failed')
                f.write(json.dumps(dict(episode=r['episode'],group=r['group'],action_id=r['action_id'],split=r['split'],phase=phase,score=score,targets=targets))+'\n')
                for k,t in targets.items():counts[(r['split'],phase,k)]['positive' if t['known'] and t['value'] else 'negative_or_zero' if t['known'] else 'unknown']+=1
    summary.write_text(json.dumps(dict(dataset_manifest_sha256=hashlib.sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest(),label_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),counts=[dict(split=s,phase=p,target=k,**v) for (s,p,k),v in counts.items()],note='Creation/double targets are future events; coexistence uses future callbacks or later observed boards. Timing ties and unobserved transient absence are masked. Previous Test remains protected.'),indent=2))

def build(old_dataset,inventory,output,forbidden_manifests=(),seed=20261028):
    out=Path(output);out.mkdir(parents=True,exist_ok=False);old,rows,arrays=load(old_dataset)
    episodes=json.loads(json.dumps(old['episodes']));episode_by_id={e['id']:e for e in episodes};sources=list(old['sources']);excluded=Counter();states=[]
    for e in episodes:
        e['previous_split']=e['split'];end=tail(Path(e['source']));e['terminal_events']=(end.get('state') or {}).get('episode_events');e['new_game']=False
    forbidden_seeds=set();forbidden_prefix=set()
    for path in forbidden_manifests:
        m=json.loads(Path(path).read_text())
        for e in m.get('episodes',[]):
            if e.get('split')=='test':forbidden_seeds.add(e['seed']);forbidden_prefix.add(e.get('initial_sequence'))
    forbidden_prefix.discard(None)
    # Old policy Test stays separately protected; earlier AC/ValueNet Tests never enter.
    frozen=json.loads(Path(inventory).read_text());new_f=[];new_g=[];offsets=list(map(int,arrays['offsets']));base_n=int(offsets[-1]);added=0
    environments={e['environment'] for e in episodes};seen=set(episode_by_id)
    for item in frozen:
        p=Path(item['source']);size=p.stat().st_size;digest=hashlib.sha256();valid=[];samples=[];bad=Counter();actions=[]
        metadata=load_environment(p.parent,p.stem)
        if not metadata or physical_identity(metadata['environment']) not in environments:excluded['physical environment mismatch']+=1;continue
        with p.open('rb') as f:
            for raw in f:
                digest.update(raw);r=json.loads(raw);v=slim(r)
                if r.get('state'):v['state']['episode_events']=r['state'].get('episode_events');v['state']['snapshot_fixed_time']=r['state'].get('snapshot_fixed_time')
                valid.append(v)
                if r.get('event')!='transition':continue
                try:
                    sample,t=teacher(r);before=r.get('observed_before') or {};snap=before.get('episode_events') or {};held=before.get('current_fruit') or {}
                    held_id=held.get('id')
                    drop=snap.get('drop_count') if snap.get('known') and type(held_id) is int and held_id==r['decision_source']['current_fruit'].get('id') else None
                    samples.append((sample,dict(t,action_id=r['action_id'],post_state={k:r['state'][k] for k in ('fruits','current_fruit','next_fruit_type','score','game_over') if k in r['state']},reward=r['reward'],between_steps_reward=r.get('between_steps_reward'),post_future_points=r['state']['score'],source_drop_count=drop)))
                except (ValueError,KeyError,TypeError) as e:bad[str(e)]+=1
        if p.stat().st_size!=size:raise ValueError('Completed source changed while reading')
        try:
            validate_episode(valid)
            from episode_events import audit_events
            audit_events(valid)
            start=valid[0];end=valid[-1];uid='|'.join(start[k] for k in ('game_id','stream_id','episode_id'));game_seed=start.get('worker_seed',start.get('seed'));prefix=initial_sequence(valid)
            if uid in seen:raise ValueError('duplicate episode')
            if game_seed in forbidden_seeds or prefix in forbidden_prefix:raise ValueError('historical Test quarantine')
            if not samples:raise ValueError('no usable selected decisions')
        except (ValueError,KeyError,TypeError) as e:excluded[str(e)]+=1;continue
        seen.add(uid);run=json.loads((p.parent/'run.json').read_text());ep=dict(id=uid,seed=game_seed,initial_sequence=prefix,source=str(p.resolve()),samples=len(samples),final_score=end['final_score'],natural_go=True,events=extract(valid),environment=physical_identity(metadata['environment']),previous_split=None,new_game=True,job=item['job'],terminal_events=end['state'].get('episode_events'),player_sha256=run.get('exe_sha256'))
        episodes.append(ep);episode_by_id[uid]=ep;sources.append(dict(path=str(p.resolve()),sha256=digest.hexdigest(),bytes=size));added+=1
        for sample,t in samples:
            f,g=encode(sample);new_f.extend(f);new_g.append(g);offsets.append(base_n+len(new_f));t['post_future_points']=ep['final_score']-t['post_future_points']
            rows.append(dict(episode=uid,seed=game_seed,score=sample['state']['score'],fruit_count=len(f),final_score=ep['final_score'],future_points=ep['final_score']-sample['state']['score'],**t));states.append(dict(episode=uid,action_id=t['action_id'],sample=sample))
        excluded.update({'sample: '+k:v for k,v in bad.items()});print(json.dumps(dict(new_games=added,new_samples=len(states),job=item['job'],score=ep['final_score'])),flush=True)
    split_info=assign_splits(episodes,seed)
    positive=defaultdict(lambda:defaultdict(list))
    for r in rows:
        f=[x for x in r['post_state']['fruits'] if not x.get('is_merging',False)];w=sum(x['type']==10 for x in f);melons=sum(x['type']==9 for x in f)
        for name,condition in [('future_watermelon_melon_one',w>=1 and melons>=1),('future_watermelon_melon_two',w>=1 and melons>=2),('future_watermelon_two',w>=2)]:
            if condition:positive[r['episode']][name].append(r['action_id'])
    for r in rows:
        e=episode_by_id[r['episode']];label=e['events']['labels']['watermelon_one'];r.update(split=e['split'],group=e['group'],split_purpose=e['split_purpose'],watermelon_success=label['achieved'],watermelon_success_known=label['known'],new_game=e['new_game']);r['future_targets']=future_labels(r,e,positive[e['id']])
    with (out/'states.jsonl').open('w',encoding='utf-8') as dest:
        with (Path(old_dataset)/'states.jsonl').open(encoding='utf-8') as f:
            for line in f:
                s=json.loads(line);s['split']=episode_by_id[s['episode']]['split'];dest.write(json.dumps(s)+'\n')
        for s in states:s['split']=episode_by_id[s['episode']]['split'];dest.write(json.dumps(s)+'\n')
    (out/'records.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
    np.savez(out/'features.npz',fruits=np.concatenate([arrays['fruits'],np.asarray(new_f,dtype=np.float32).reshape(-1,30)]),offsets=np.asarray(offsets,dtype=np.int64),globals=np.concatenate([arrays['globals'],np.asarray(new_g,dtype=np.float32)]))
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()};splits=sorted({e['split'] for e in episodes})
    report=dict(version=VERSION,input_spec=old['input_spec'],episodes=episodes,sample_count=len(rows),episode_count=len(episodes),added_games=added,files=files,sources=sources,split_seed=seed,split_info=split_info,excluded=dict(excluded),
        split_games=dict(Counter(e['split'] for e in episodes)),split_states=dict(Counter(r['split'] for r in rows)),split_groups={s:len({e['group'] for e in episodes if e['split']==s}) for s in splits},
        previous_dataset=str(Path(old_dataset).resolve()),previous_manifest_sha256=hashlib.sha256((Path(old_dataset)/'manifest.json').read_bytes()).hexdigest(),future_label_note='Recorded-policy outcomes, not optimal achievable returns. Additional points are exact; event equality without a source clock stays unknown. Coexistence includes positive later saved-board evidence; old absence remains unknown. No future labels are model inputs.')
    (out/'manifest.json').write_text(json.dumps(report,indent=2));return report
