"""Natural actual-game Q^pi observations for a single verified root; no fitting."""
import argparse,hashlib,json,statistics
from pathlib import Path
from run_fresh_continuation import read_rows

def build(folder):
    observations=[];root_signature=None;series={}
    for p in sorted(Path(folder).glob('branch24_*/result.json')):
        r=json.loads(p.read_text());cfg=json.loads((p.parent/'config.json').read_text());end=r.get('end');root=r.get('root')
        if not (end and root and end['mc_return_known'] and end['game_over'] and end['prefix_verified'] and not r['errors'] and not r['first_mismatch'] and r['exit_code']==0):continue
        sig=json.dumps({k:root[k] for k in ['tick','rng','state','bodies']},sort_keys=True)
        if root_signature is None:root_signature=sig
        if sig!=root_signature:raise ValueError('Different roots cannot supply same-state ranking teachers')
        rows=list(read_rows(p.parent/'trace.jsonl'));actions=[x for x in rows if x['evt']=='action' and x['drops']>root['drops']]
        first=actions[0]['commands'][0]
        if abs(first['x']-cfg['candidate_x'])>1e-6:raise ValueError('Forced coordinate mismatch')
        s=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]
        for a in actions:
            if a['state']['current_fruit']['type']!=s[-1]:raise ValueError('Public NEXT/held shift mismatch')
            s.append(a['state']['next_fruit_type'])
        series[p.parent.name]=s
        observations.append(dict(run=p.parent.name,candidate_x=cfg['candidate_x'],applied_x=first['applied_x'],future_seed=cfg['future_seed'],root_score=root['score'],final_score=end['score'],additional_score=end['score']-root['score'],seconds=r['wall_seconds'],natural_go=True,root_verified=True,continuation='existing heuristic5/25tick; decisions in Update; no neural network',special_events_complete=False))
    paired=[]
    for f in sorted({o['future_seed'] for o in observations}):
        group=[o for o in observations if o['future_seed']==f]
        for i,a in enumerate(group):
            for b in group[i+1:]:
                if a['candidate_x']==b['candidate_x']:continue
                sa,sb=series[a['run']],series[b['run']];n=min(len(sa),len(sb))
                if sa[:n]!=sb[:n]:raise ValueError('Common future series did not match')
                paired.append(dict(future_seed=f,a=a['candidate_x'],b=b['candidate_x'],difference_b_minus_a=b['additional_score']-a['additional_score'],common_public_fruits=n))
    estimates={str(x):dict(samples=len(a),mean_return=statistics.mean(o['additional_score'] for o in a),returns=[o['additional_score'] for o in a]) for x in sorted({o['candidate_x'] for o in observations}) if (a:=[o for o in observations if o['candidate_x']==x])}
    seconds=sum(o['seconds'] for o in observations)
    return dict(root_id=hashlib.sha256(root_signature.encode()).hexdigest() if root_signature else None,independent_roots=int(bool(observations)),observations=observations,paired=paired,estimates=estimates,branch_seconds=seconds,seconds_per_natural_return=seconds/len(observations) if observations else None,limitation='One root and finite common futures under a fixed policy, not optimal Q or proof of long-term strength. Transient special events are not exhaustively captured by this trace; unknown is not failure.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=build(a.root)
    with a.output.open('x',encoding='utf8') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
