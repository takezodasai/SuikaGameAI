"""Imitation diagnostics, not evidence of real-game strength."""
import math
from collections import defaultdict
import numpy as np

def metrics(records,ids,probabilities):
    rows=[]
    for i,p in zip(ids,probabilities):
        r=records[i];p=np.asarray(p,dtype=float);p=p/p.sum();v=np.asarray(r['visits'],dtype=float);target=v/v.sum();log=np.log(np.maximum(p,1e-12));sel=r['selected_index'];pred=int(np.argmax(p));order=np.argsort(-p,kind='stable')
        strict=[];qstrict=[]
        for a in range(len(p)):
            for b in range(a):
                for values,acc in [(v,strict),(np.asarray(r['mean_points']),qstrict)]:
                    diff=values[a]-values[b]
                    if abs(diff)>1e-8:acc.append(.5 if abs(p[a]-p[b])<1e-10 else float((p[a]-p[b])*diff>0))
        rows.append(dict(index=i,episode=r['episode'],seed=r['seed'],group=r['group'],correct=float(pred==sel),top2=float(sel in order[:2]),x_error=abs(r['candidate_x'][pred]-r['selected_x']),cross_entropy=-float(target@log),kl=float(sum(t*(math.log(t)-lp) for t,lp in zip(target,log) if t>0)),visit_pair_accuracy=float(np.mean(strict)) if strict else None,value_pair_accuracy=float(np.mean(qstrict)) if qstrict else None,target_entropy=float(-sum(t*math.log(t) for t in target if t>0)),teacher_x=r['selected_x'],predicted_x=r['candidate_x'][pred],confidence=float(p[pred]),actual_iterations=r['actual_iterations'],depth=r['depth'],candidate_count=len(p)))
    if not rows:return dict(samples=0),[]
    fields=['correct','top2','x_error','cross_entropy','kl','visit_pair_accuracy','value_pair_accuracy','target_entropy']
    summary=dict(samples=len(rows),episodes=len({r['episode'] for r in rows}),seed_groups=len({r['group'] for r in rows}))
    for k in fields:
        v=[r[k] for r in rows if r[k] is not None];summary[k]=float(np.mean(v)) if v else None
    groups=defaultdict(list)
    for r in rows:groups[r['group']].append(r)
    summary['group_macro_accuracy']=float(np.mean([np.mean([r['correct'] for r in v]) for v in groups.values()]))
    summary['group_macro_kl']=float(np.mean([np.mean([r['kl'] for r in v]) for v in groups.values()]))
    return summary,rows

def prior_fit(records):
    bins=np.ones(17,dtype=float)*1e-3
    for r in records:
        if r['split']!='train':continue
        for x,v in zip(r['candidate_x'],r['visits']):bins[round(x*16)]+=v/sum(r['visits'])
    return bins/bins.sum()

def prior_predict(prior,records,ids):
    result=[]
    for i in ids:
        x=np.array([prior[round(x*16)] for x in records[i]['candidate_x']]);result.append((x/x.sum()).tolist())
    return result
