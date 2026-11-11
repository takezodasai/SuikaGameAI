"""Post-action natural-GO data with protected historical Test and fresh seed Test."""
import hashlib,json,random
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from suika_ai.long_value_data import load,slim,physical_identity
from suika_ai.value_data import encode,validate_episode,INPUT_SPEC
from suika_ai.collection_audit import correlation_groups,initial_sequence,load_environment


def roles(old_roles):
    if set(old_roles)&{'test','historical_test'}:return 'protected'
    if 'train' in old_roles and 'validation' in old_roles:raise ValueError('Historical split conflict')
    return 'validation' if 'validation' in old_roles else 'train' if 'train' in old_roles else None


def annotate(records,episode,fruit_slices):
    first=next((i for i,f in enumerate(fruit_slices) if len(f) and np.any(np.argmax(f[:,:11],axis=1)==10)),None)
    for i,r in enumerate(records):
        remaining=len(records)-1-i
        r.update(remaining_actions=remaining,risk3=bool(r['game_over'] or remaining<=3),near_go=bool(not r['game_over'] and remaining<5),
            wm_window='pre_observed' if first is not None and first-5<=i<first else 'post_observed' if first is not None and first<=i<first+5 else 'other')


def build(root):
    root=Path(root);root.mkdir(exist_ok=False);dataset=root/'dataset';dataset.mkdir()
    old_path=Path('Python/outputs/step8ac_01/dataset');old=load(old_path);om,ors,offsets,gs,ys,fs=old
    pm=json.loads(Path('Python/outputs/policy_success_01/dataset/manifest.json').read_text(encoding='utf8'))
    all_eps={e['id']:dict(e,roles=[e['split']]) for e in om['episodes']}
    for e in pm['episodes']:
        if e['id'] in all_eps:all_eps[e['id']]['roles'].append(e['split'])
        else:all_eps[e['id']]=dict(e,roles=[e['split']])
    # Freeze completion inventory; no unfinished trajectory is read.
    inventory=[]
    for p in sorted(Path('Python/outputs/overnight_diverse_20261028_155849_bd9f1a81').glob('jobs/*/*_result.json')):
        item=json.loads(p.read_text(encoding='utf8'))
        if item.get('natural_go') and item.get('valid_for_return_learning') and not item.get('errors'):
            inventory.append(dict(item,result_path=str(p)))
    (root/'inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf8')
    new_sources={str(Path(e['source'])):e['id'] for e in all_eps.values() if e['id'] not in {v['id'] for v in om['episodes']}}
    for item in inventory:new_sources[str(Path(item['attempt'])/'game_00.jsonl')]=None
    parsed={};source_hashes={}
    for source in sorted(new_sources):
        data=[];sha=hashlib.sha256();path=Path(source)
        with path.open('rb') as f:
            for line in f:
                sha.update(line);row=json.loads(line);data.append(slim(row))
        samples=validate_episode(data);end=data[-1];start=data[0];uid='|'.join(start[k] for k in ('game_id','stream_id','episode_id'))
        metadata=load_environment(path.parent,'game_00')
        if not metadata or physical_identity(metadata['environment']) not in om['environments']:raise ValueError('Environment mismatch')
        if uid not in all_eps:all_eps[uid]=dict(id=uid,seed=start.get('worker_seed',start.get('seed')),initial_sequence=initial_sequence(data),source=source,roles=[],split=None)
        e=all_eps[uid];e.update(final_score=end['final_score'],samples=len(samples));parsed[uid]=samples;source_hashes[source]=sha.hexdigest()
    members=correlation_groups(list(all_eps.values()));group_roles=defaultdict(list)
    for e in all_eps.values():group_roles[members[e['id']]]+=e['roles']
    assignments={g:roles(v) for g,v in group_roles.items()}
    fresh=sorted(g for g,r in assignments.items() if r is None);random.Random(20261029).shuffle(fresh)
    if len(fresh)<15:raise ValueError('Insufficient fresh groups; no recycled Test')
    nt=max(5,round(len(fresh)*.2));nv=max(3,round(len(fresh)*.16))
    for i,g in enumerate(fresh):assignments[g]='test' if i<nt else 'validation' if i<nt+nv else 'train'
    (root/'evaluation_plan.json').write_text(json.dumps(dict(seed=20261029,variants=['A','B','C'],epochs=10,patience=3,
        architecture='AC geometry43009; C adds 223-parameter risk head',rank_weight=.05,near_go_weight_B=4,risk_loss_C=.1,
        risk_target='natural-GO within next 3 accepted observation transitions; behavioral, not action-independent hazard',
        checkpoint_selection='validation seed-group macro MSE only',test='new untouched groups, outcome-blind allocation; all variants frozen before one evaluation',
        fresh_groups=fresh,test_groups=fresh[:nt],validation_groups=fresh[nt:nt+nv],D='not trained without trustworthy same-root full-return labels'),indent=2),encoding='utf8')
    records=[];fruits=[];globals_=[];targets=[];eps=[]
    old_by=defaultdict(list)
    for i,r in enumerate(ors):old_by[r['episode']].append(i)
    for uid,e in all_eps.items():
        split=assignments[members[uid]]
        if split=='protected':continue
        rr=[];ff=[];gg=[];tt=[]
        if uid in old_by:
            for i in old_by[uid]:rr.append(dict(ors[i]));ff.append(np.asarray(fs[offsets[i]:offsets[i+1]]));gg.append(gs[i]);tt.append(ys[i])
        elif uid in parsed:
            for s in parsed[uid]:
                f,g=encode(s);ff.append(np.asarray(f,dtype=np.float32).reshape(-1,30));gg.append(g);tt.append(s['target']/1000)
                rr.append(dict(episode=uid,seed=e['seed'],score=s['state']['score'],target=s['target'],action_id=s['action_id'],game_over=s['state']['game_over'],fruit_count=len(f),policy=s['policy']))
        else:continue
        annotate(rr,e,ff)
        for r in rr:r.update(split=split,group=members[uid])
        records+=rr;fruits+=ff;globals_+=gg;targets+=tt;eps.append(dict(id=uid,seed=e['seed'],group=members[uid],split=split,source=e['source'],samples=len(rr),final_score=e['final_score']))
    off=np.cumsum([0]+[len(f) for f in fruits]);np.concatenate(fruits).astype('float32').tofile(dataset/'fruits.f32');np.save(dataset/'offsets.npy',off);np.save(dataset/'globals.npy',np.asarray(globals_,dtype='float32'));np.save(dataset/'targets.npy',np.asarray(targets,dtype='float32'))
    (dataset/'records.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n',encoding='utf8')
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dataset.iterdir()}
    m=dict(version='value-reliability-post-v1',input_spec=INPUT_SPEC,episodes=eps,sample_count=len(records),episode_count=len(eps),
        split_seed=20261029,split_games=dict(Counter(e['split'] for e in eps)),split_groups={s:sorted({e['group'] for e in eps if e['split']==s}) for s in ('train','validation','test')},files=files,sources=source_hashes,protected_groups=sorted(g for g,r in assignments.items() if r=='protected'),environments=om['environments'])
    (dataset/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf8')
    print(json.dumps(dict(games=m['split_games'],groups={s:len(v) for s,v in m['split_groups'].items()},states=dict(Counter(r['split'] for r in records)),new_sources=len(source_hashes),protected_groups=len(m['protected_groups']))),flush=True)
    return dataset
