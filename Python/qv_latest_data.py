"""Freeze newly completed games; preserve old Validation/Test; observed drops only."""
import hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np
from suika_ai.policy_data import teacher
from suika_ai.long_value_data import slim,physical_identity
from suika_ai.value_data import validate_episode,encode
from suika_ai.collection_audit import initial_sequence,load_environment
from qv_experiment import ROOT,VALUE,POLICY,write

def prefix(path):
    rows=[];n=0
    with Path(path).open() as f:
        for l in f:
            r=json.loads(l);rows.append(r)
            if r['event']=='transition':
                n+=1
                if n==8:break
    return initial_sequence(rows)

def main():
    folder=ROOT/'latest';folder.mkdir(exist_ok=False);vm=json.loads((VALUE/'manifest.json').read_text());pm=json.loads((POLICY/'manifest.json').read_text());old=json.loads(Path('Python/outputs/step8ac_01/dataset/manifest.json').read_text())
    existing={e['source'] for e in vm['episodes']};reserved_seeds={e['seed'] for e in vm['episodes']};reserved_prefix={e.get('initial_sequence') for e in pm['episodes']+old['episodes']};reserved_prefix.discard(None)
    for e in vm['episodes']:
        if e['split']=='test':reserved_prefix.add(prefix(e['source']))
    source=Path('Python/outputs/overnight_diverse_20261029_012253_922ae62c');inventory=[]
    for p in sorted(source.glob('jobs/*/*_result.json')):
        r=json.loads(p.read_text());path=Path(r['attempt'])/'game_00.jsonl'
        if r.get('natural_go') and r.get('valid_for_return_learning') and not r.get('errors') and str(path) not in existing:inventory.append(dict(result=r,result_file=str(p),source=str(path),prefix=prefix(path)))
    # Reserve a genuinely fresh Test subset by seed hash, without score-based selection.
    groups=sorted({(r['result']['game_seed'],r['prefix']) for r in inventory},key=lambda a:hashlib.sha256(str(a[0]).encode()).hexdigest());test=set(groups[:max(1,round(len(groups)*.15))])
    write(folder/'inventory.json',dict(items=inventory,new_test_groups=[list(x) for x in test],selection='First 15% by SHA256(seed), outcome blind; initial8/seed collision with any old split is quarantined'))
    pf=[];pg=[];po=[0];vf=[];vg=[];vo=[0];records=[];excluded=Counter();seen_prefix=set();envs=set(vm['environments'])
    for item in inventory:
        seed=item['result']['game_seed'];seq=item['prefix']
        if seed in reserved_seeds or seq in reserved_prefix or seq in seen_prefix:excluded['related to previous split or duplicate initial8']+=1;continue
        if seq in {p for _,p in test}:excluded['fresh Test reserved, not opened for training']+=1;continue
        seen_prefix.add(seq);path=Path(item['source']);metadata=load_environment(path.parent,'game_00')
        if not metadata or physical_identity(metadata['environment']) not in envs:excluded['environment mismatch']+=1;continue
        small=[];samples=[];h=hashlib.sha256();size=path.stat().st_size
        with path.open('rb') as f:
            for raw in f:
                h.update(raw);r=json.loads(raw);small.append(slim(r))
                if r['event']!='transition':continue
                if r['info'].get('drop_success') is not True:excluded['not an executed drop']+=1;continue
                try:before,t=teacher(r)
                except (KeyError,ValueError,TypeError) as e:excluded['sample: '+str(e)]+=1;continue
                post=dict(state=r['state'],geometry=before['geometry']);samples.append((before,post,t,r['action_id']))
        validate_episode(small)
        if size!=path.stat().st_size:raise ValueError('Completed source changed')
        end=small[-1];uid='|'.join(small[0][k] for k in ['game_id','stream_id','episode_id']);final=end['final_score'];first_wm=next((i for i,(_,s,_,_) in enumerate(samples) if any(f['type']==10 for f in s['state']['fruits'])),None)
        for i,(before,after,t,action) in enumerate(samples):
            f,g=encode(before);ff,gg=encode(after);pf.extend(f);pg.append(g);po.append(len(pf));vf.extend(ff);vg.append(gg);vo.append(len(vf))
            score=before['state']['score'];s=after['state'];remaining=len(samples)-1-i
            records.append(dict(episode=uid,action_id=action,seed=seed,group='fresh-seed-'+str(seed),split='train',target=final-score,post_target=final-s['score'],score=score,fruit_count=len(f),selected_x=t['selected_x'],immediate=s['score']-score,game_over=s['game_over'],post_game_over=s['game_over'],before_game_over=False,near_go=not s['game_over'] and remaining<5,remaining_actions=remaining,wm_window='pre_observed' if first_wm is not None and first_wm-5<=i<first_wm else 'post_observed' if first_wm is not None and first_wm<=i<first_wm+5 else 'other',actual_iterations=t['actual_iterations'],requested_iterations=t['requested_iterations'],depth=t['depth'],stop_reason=t['stop_reason'],watermelon_known=item['result']['events_known'],watermelon_success=item['result']['watermelon_events']>0,source=str(path),source_sha256=h.hexdigest()))
    np.savez(folder/'features.npz',pre_fruits=np.asarray(pf,dtype='float32'),pre_globals=np.asarray(pg,dtype='float32'),pre_offsets=po,post_fruits=np.asarray(vf,dtype='float32'),post_globals=np.asarray(vg,dtype='float32'),post_offsets=vo)
    write(folder/'records.json',records);write(folder/'audit.json',dict(inventory_games=len(inventory),added_games=len({r['episode'] for r in records}),added_states=len(records),excluded=dict(excluded),test_reserved=len(test)))
    print(json.dumps(dict(games=len({r['episode'] for r in records}),states=len(records),excluded=excluded)),flush=True)

if __name__=='__main__':main()
