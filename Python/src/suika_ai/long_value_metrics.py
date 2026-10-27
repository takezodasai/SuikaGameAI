"""Group-aware offline ranking and return metrics, never used for live decisions."""
from collections import defaultdict
import math
import numpy as np

def rankdata(x):
    x=np.asarray(x);order=np.argsort(x,kind='stable');r=np.empty(len(x),dtype=float);i=0
    while i<len(order):
        j=i+1
        while j<len(order) and x[order[j]]==x[order[i]]:j+=1
        r[order[i:j]]=(i+j-1)/2;i=j
    return r

def spearman(a,b):
    a=rankdata(a);b=rankdata(b)
    return float(np.corrcoef(a,b)[0,1]) if np.std(a)>0 and np.std(b)>0 else None

def episode_group_errors(records,ids,prediction):
    eps=defaultdict(list);groups={}
    for i,p in zip(ids,prediction):
        r=records[int(i)];eps[r['episode']].append(float(p-r['target']));groups[r['episode']]=r['group']
    grouped=defaultdict(list)
    for ep,e in eps.items():
        e=np.asarray(e);grouped[groups[ep]].append([np.mean(np.abs(e)),np.mean(e*e)])
    return {g:np.mean(v,axis=0) for g,v in grouped.items()}

def point_metrics(records,ids,prediction):
    target=np.array([records[int(i)]['target'] for i in ids]);prediction=np.asarray(prediction);error=prediction-target
    grouped=episode_group_errors(records,ids,prediction);v=np.array(list(grouped.values()))
    nonterminal=np.array([not records[int(i)]['game_over'] for i in ids])
    return dict(states=len(ids),games=len({records[int(i)]['episode'] for i in ids}),groups=len(grouped),mae=float(np.abs(error).mean()),rmse=float(np.sqrt((error*error).mean())),bias=float(error.mean()),group_macro_mae=float(v[:,0].mean()),group_macro_rmse=float(np.sqrt(v[:,1].mean())),spearman_nonterminal=spearman(target[nonterminal],prediction[nonterminal]))

def matched_pairs(records,ids,count=4000,seed=20261027,same_policy=True):
    bins=defaultdict(lambda:defaultdict(lambda:defaultdict(list)))
    for i in ids:
        r=records[int(i)]
        if r['game_over']:continue
        key=((r['policy'] if same_policy else '*'),r['score']//100,r['held_type'],r['next_type'])
        bins[key][r['group']][r['episode']].append(int(i))
    keys=[key for key,v in bins.items() if len(v)>1];rng=np.random.default_rng(seed);pairs=[];seen=set()
    if not keys:return np.empty((0,2),dtype=int)
    for _ in range(max(10000,count*100)):
        b=bins[keys[int(rng.integers(len(keys)))]];groups=list(b)
        ga,gb=rng.choice(len(groups),2,replace=False);a=b[groups[ga]];d=b[groups[gb]]
        ea=list(a);eb=list(d);aa=a[ea[int(rng.integers(len(ea)))]];bb=d[eb[int(rng.integers(len(eb)))]]
        i=aa[int(rng.integers(len(aa)))];j=bb[int(rng.integers(len(bb)))];key=(min(i,j),max(i,j))
        if key in seen or abs(records[i]['target']-records[j]['target'])<100:continue
        seen.add(key);pairs.append((i,j))
        if len(pairs)>=count:break
    return np.asarray(pairs,dtype=int).reshape(-1,2)

def ranking_metrics(records,prediction,pairs,bootstrap=1000,seed=20261027):
    if len(pairs)==0:return dict(pairs=0,accuracy=None)
    a,b=pairs.T;truth=np.array([records[int(i)]['target'] for i in a])-np.array([records[int(i)]['target'] for i in b]);difference=prediction[a]-prediction[b]
    correct=np.where(np.abs(difference)<1,.5,(truth*difference>0).astype(float))
    groups=sorted({records[int(i)]['group'] for i in np.unique(pairs)});lookup={g:i for i,g in enumerate(groups)}
    ga=np.array([lookup[records[int(i)]['group']] for i in a]);gb=np.array([lookup[records[int(i)]['group']] for i in b]);rng=np.random.default_rng(seed);values=[]
    for _ in range(bootstrap):
        counts=rng.multinomial(len(groups),np.ones(len(groups))/len(groups));weights=counts[ga]*counts[gb]
        if weights.sum():values.append(float(np.sum(weights*correct)/weights.sum()))
    return dict(pairs=len(pairs),states=len(np.unique(pairs)),groups=len(groups),accuracy=float(correct.mean()),seed_group_bootstrap_95ci=np.quantile(values,[.025,.975]).tolist() if values else None,valid_bootstraps=len(values),ties=int(np.sum(np.abs(difference)<1)),limitation='Observed returns across matched different-seed boards; not counterfactual action-ranking accuracy')

def paired_mae_interval(records,ids,a,b,bootstrap=2000,seed=20261027):
    ga=episode_group_errors(records,ids,a);gb=episode_group_errors(records,ids,b);groups=sorted(ga)
    delta=np.array([ga[g][0]-gb[g][0] for g in groups]);rng=np.random.default_rng(seed)
    draws=delta[rng.integers(len(delta),size=(bootstrap,len(delta)))].mean(1)
    return dict(groups=len(groups),mean_group_macro_mae_difference=float(delta.mean()),bootstrap_95ci=np.quantile(draws,[.025,.975]).tolist())


def near_terminal_ids(records,ids,count=5):
    """Last saved nonterminal actual-action states per episode, not a time duration."""
    episodes=defaultdict(list)
    for i in ids:
        if not records[int(i)]['game_over']:episodes[records[int(i)]['episode']].append(int(i))
    return {i for values in episodes.values() for i in values[-count:]}
