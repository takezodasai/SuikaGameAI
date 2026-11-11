"""Natural returns and explicitly censored intervals, never invented MC targets."""
import json,math,statistics
from pathlib import Path
from action_decision_plan import ROOT,write
from run_fresh_continuation import read_rows
from compare_mcts_ai import public_series

def signature(root):
    import hashlib
    return hashlib.sha256(json.dumps({k:root[k] for k in ['tick','state','bodies','rng']},sort_keys=True).encode()).hexdigest()

def difference_interval(a,b):
    # [L, None] means right-censored return with no finite upper bound.
    return (None if a['upper'] is None else b['lower']-a['upper'],None if b['upper'] is None else b['upper']-a['lower'])

def certified_winner(lo,hi):
    if lo is not None and lo>0:return .37
    if hi is not None and hi<0:return 0.
    if lo==0 and hi==0:return 'tie'
    return None

def observation(path,pred):
    path=Path(path);r=json.loads(path.read_text());end=r.get('end');root=r.get('root');cfg=json.loads((path.parent/'config.json').read_text())
    if not(end and root and end['prefix_verified'] and r['exit_code']==0 and not r['errors'] and not r['first_mismatch']):return None
    if signature(root)!=pred['root_signature']:raise ValueError('Different observed root')
    exact=end['game_over'] and end['mc_return_known']
    censored=not end['game_over'] and end['reason'] in ['wall_limit','drop_limit','tick_limit']
    if not(exact or censored):return None
    rows=list(read_rows(path.parent/'trace.jsonl'));last=-1
    for row in rows:
        if row['score']<last:raise ValueError('Cannot derive a return lower bound without monotone actual score')
        last=row['score']
    actions=[a for a in rows if a['evt']=='action' and a['drops']>root['drops']];s=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]
    for a in actions:
        if a['state']['current_fruit']['type']!=s[-1]:raise ValueError('Public NEXT shift mismatch')
        s.append(a['state']['next_fruit_type'])
    if actions and abs(actions[0]['commands'][0]['x']-cfg['candidate_x'])>1e-5:raise ValueError('Actual coordinate mismatch')
    value=end['score']-root['score']
    return dict(path=str(path),future_seed=cfg['future_seed'],x=cfg['candidate_x'],exact_natural=bool(exact),mc_target=value if exact else None,lower=value,upper=value if exact else None,seconds=r['wall_seconds'],reason=end['reason'],public_fruits=s,first_horizon_GO=bool(exact and end['drops']<=root['drops']))

def analyze_root(role):
    pred=json.loads(Path(role['predictions']).read_text());paths=list((ROOT/'branches'/role['name']).glob('f*/result.json'))
    if role.get('past'):paths+=list(Path(role['past']).glob('x*/result.json'))
    obs=[];rejected=[]
    for p in paths:
        o=observation(p,pred)
        if o:obs.append(o)
        else:rejected.append(str(p))
    keys=[(o['x'],o['future_seed']) for o in obs]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate candidate/future')
    common=set(o['future_seed'] for o in obs if o['x']==0.)&set(o['future_seed'] for o in obs if abs(o['x']-.37)<1e-5);pairs=[]
    for f in sorted(common):
        a=next(o for o in obs if o['future_seed']==f and o['x']==0.);b=next(o for o in obs if o['future_seed']==f and abs(o['x']-.37)<1e-5);n=min(len(a['public_fruits']),len(b['public_fruits']))
        if a['public_fruits'][:n]!=b['public_fruits'][:n]:raise ValueError('Common future mismatch')
        lo,hi=difference_interval(a,b);pairs.append(dict(future=f,a=a,b=b,difference_lo=lo,difference_hi=hi,common_public_fruits=n))
    lo=statistics.mean(p['difference_lo'] for p in pairs) if pairs and all(p['difference_lo'] is not None for p in pairs) else None
    hi=statistics.mean(p['difference_hi'] for p in pairs) if pairs and all(p['difference_hi'] is not None for p in pairs) else None
    winner=certified_winner(lo,hi) if pairs else None;exact=bool(pairs) and all(p['a']['exact_natural'] and p['b']['exact_natural'] for p in pairs)
    methods={}
    for m,choice in pred['selected_observed_pair'].items():
        known=winner is not None and choice is not None;correct=choice==winner or winner=='tie' if known else None
        minimum_regret=0. if correct else min(abs(v) for v in [lo,hi] if v is not None) if known else None
        methods[m]=dict(chosen=choice,correct=correct,exact_regret=minimum_regret if exact and known else None,regret_lower_bound=minimum_regret,full_six_choice=pred['selected_full'][m],full_choice_observed=pred['selected_full'][m] in [0.,.37],training_seed_choices=pred['seed_choices'].get(m))
    full_seeds={}
    for m in ['C','D']:
        eligible=[r for r in pred['rows'] if r[m] is not None]
        if m!='D' and any(not r['predicted_GO'] for r in eligible):eligible=[r for r in eligible if not r['predicted_GO']]
        full_seeds[m]=[max(eligible,key=lambda r:r[m+'_seeds'][j])['x'] for j in range(3)] if eligible else []
    return dict(name=role['name'],role=role['role'],seed=role['seed'],observations=obs,rejected=rejected,pairs=pairs,common_futures=len(pairs),difference_mean_interval=[lo,hi],fully_natural=exact,certified_sample_winner=winner,methods=methods,full_training_seed_choices=full_seeds,Q_interval_overshoot=pred['q_scan']['maximum_interval_overshoot_points'],timing=pred['timing'],predicted_GO_candidates=sum(r['predicted_GO'] is True for r in pred['rows']),actual_first_horizon_GO=sum(o['first_horizon_GO'] for o in obs),note='Intervals refer to these sampled common futures under heuristic continuation, not optimal Q or a population confidence interval.')

def benchmark_audit():
    base=ROOT/'concurrency';stats=json.loads((base/'summary.json').read_text());logs={}
    for workers in ['2','4']:
        logs[workers]={}
        for p in (base/f'workers_{workers}').rglob('run.json'):
            seed=json.loads(p.read_text())['workers'][0]['seed'];rows=[json.loads(x) for x in (p.parent/'game_00.jsonl').read_text().splitlines()];acts=[r for r in rows if r['event']=='transition'];logs[workers][seed]=(rows,acts)
    matched=[]
    for seed in sorted(set(logs['2'])&set(logs['4'])):
        a,aa=logs['2'][seed];b,bb=logs['4'][seed];sa,sb=public_series(a),public_series(b);n=min(len(sa),len(sb));k=min(len(aa),len(bb))
        if sa[:n]!=sb[:n]:raise ValueError('Performance benchmark fruit stream mismatch')
        equal=sum(abs(x['selected_x']-y['selected_x'])<1e-5 for x,y in zip(aa[:k],bb[:k]))
        matched.append(dict(seed=seed,common_actions=k,public_fruit_prefix_equal=True,selected_coordinates_equal=equal,two_mean_ms=statistics.mean(r['info']['planning']['mcts']['elapsed_ms'] for r in aa[:k]),four_mean_ms=statistics.mean(r['info']['planning']['mcts']['elapsed_ms'] for r in bb[:k])))
    return dict(results=stats,matched=matched,throughput_ratio=stats['4']['decisions_per_hour']/stats['2']['decisions_per_hour'],note='Four fixed256/depth4 seeds, early24 steps/90s guards, fixed phase order2->4; no natural-GO throughput estimate. Same fruit stream does not imply same physical trajectory.')

def main(output=None):
    inv=json.loads((ROOT/'branches/inventory.json').read_text());roles=inv['roots'];extra=ROOT/'branches/backup_inventory.json'
    if extra.exists():roles+=json.loads(extra.read_text()).get('roots',[])
    roots=[analyze_root(role) for role in roles];summary={}
    for role in ['development','branch_evaluation','branch_evaluation_backup']:
        rr=[r for r in roots if r['role']==role];summary[role]={}
        for m in 'ABCD':
            known=[r for r in rr if r['methods'][m]['correct'] is not None];exact=[r['methods'][m]['exact_regret'] for r in known if r['methods'][m]['exact_regret'] is not None]
            lower=[r['methods'][m]['regret_lower_bound'] for r in known]
            summary[role][m]=dict(roots_with_known_sample_order=len(known),correct=sum(r['methods'][m]['correct'] for r in known),mean_exact_regret=statistics.mean(exact) if exact else None,exact_regret_roots=len(exact),mean_regret_lower_bound=statistics.mean(lower) if lower else None)
    supplementary=[];p=ROOT/'branches/proposal_inventory.json'
    if p.exists():
        supp=json.loads(p.read_text())
        if not supp.get('skipped'):
            rp=Path(supp['result']);name=rp.parent.parent.name;role=next(r for r in roles if r['name']==name);pred=json.loads(Path(role['predictions']).read_text());o=observation(rp,pred)
            supplementary.append(dict(exploratory_only=True,observation=o,full_choices=pred['selected_full'],note='One model-vote-selected extra coordinate, one future; censored lower bound is not a final return. Not included in primary heldout metrics.'))
    write(output or ROOT/'analysis.json',dict(roots=roots,summary=summary,supplementary=supplementary,benchmark=benchmark_audit(),limitation='Primary deployment decisions require full candidate returns. Most full-six selections have no actual return here. No model or algorithm changed; no Test19 model evaluation. Censored scores never MC targets.'))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args();main(a.output)
