"""Undiscounted n-step targets from verified actual natural-GO trajectories.

Rewards are score differences, including between-operation merges. No simulated
or censored return is promoted to a terminal teacher. Bootstrap values stay external.
"""
import math

def n_step_pairs(records,indices,n,*,natural_go):
    if natural_go is not True:raise ValueError('Verified actual natural GO required')
    if type(n) is not int or n<1:raise ValueError('Positive observation horizon required')
    ids=list(indices)
    if not ids:return []
    rs=[records[i] for i in ids]
    if len({(r['episode'],r['group'],r['split']) for r in rs})!=1:raise ValueError('Cross-episode/group/split trajectory')
    if not rs[-1]['game_over'] or any(r['game_over'] for r in rs[:-1]):raise ValueError('Missing or premature natural terminal')
    final=rs[-1]['score']
    for j,r in enumerate(rs):
        if r['score']+r['target']!=final:raise ValueError('MC score conservation failed')
        if j and r['score']<rs[j-1]['score']:raise ValueError('Reversed score trajectory')
    result=[]
    for p,r in enumerate(rs[:-1]):
        q=min(p+n,len(rs)-1);end=rs[q]
        result.append(dict(index=ids[p],bootstrap_index=ids[q],observations=q-p,score_delta=end['score']-r['score'],terminal=end['game_over'],continuation_discount=0 if end['game_over'] else 1,mc_return=r['target']))
    return result

def td_target(pair,value_next):
    if pair['terminal']:return float(pair['score_delta'])
    if not math.isfinite(value_next):raise ValueError('Nonfinite bootstrap')
    return pair['score_delta']+float(value_next)
