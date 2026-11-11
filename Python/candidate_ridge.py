"""Small public-information B-A ridge model. No Unity/MCTS modifications."""
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np

FEATURE_NAMES=['fruit_count','pile_top','mean_y','mean_speed','area_fraction','large_fraction',
    'watermelons','held_type','next_type','current_score','x_A','x_B','mean_gap','visit_gap',
    'sd_A','sd_B','terminal_A','terminal_B','local_area_gap','matching_distance_gap']
VERSION='ridge-public20-v1'


def features(state,coordinates,stats):
    left,right,bottom,top=map(float,state['geometry']);width=right-left;height=top-bottom
    if width<=0 or height<=0:raise ValueError('Unknown/invalid geometry')
    fs=state['fruits'];n=len(fs);held=int(state['current_fruit']['type']);a,b=map(float,coordinates)
    sa,sb=stats;na,nb=int(sa['visits']),int(sb['visits'])
    def local(x):return sum(math.pi*float(f['half_width'])*float(f['half_height'])*math.exp(-.5*(((float(f['x'])-left)/width-x)/.2)**2) for f in fs)/(width*height)
    def match(x):return min([abs((float(f['x'])-left)/width-x) for f in fs if int(f['type'])==held]+[1.0])
    x=[n/40,max([(float(f['y'])+float(f['half_height'])-bottom)/height for f in fs]+[0.0]),
       sum((float(f['y'])-bottom)/height for f in fs)/max(n,1),
       sum(math.hypot(float(f['vx']),float(f['vy'])) for f in fs)/max(n,1)/10,
       sum(math.pi*float(f['half_width'])*float(f['half_height']) for f in fs)/(width*height),
       sum(int(f['type'])>=8 for f in fs)/max(n,1),sum(int(f['type'])==10 for f in fs)/2,
       held/10,int(state['next_fruit_type'])/10,float(state['score'])/3000,a,b,
       (float(sb['mean_points'])-float(sa['mean_points']))/55,(nb-na)/max(na+nb,1),
       float(sa['sd_points'])/55,float(sb['sd_points'])/55,
       float(sa['terminal_returns'])/max(na,1),float(sb['terminal_returns'])/max(nb,1),local(b)-local(a),match(b)-match(a)]
    if len(x)!=20 or not all(math.isfinite(v) for v in x):raise ValueError('Non-finite feature')
    return np.asarray(x,dtype=np.float64)


def canonical_state(s):
    def clean(x):
        if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k!='id'}
        if isinstance(x,list):return [clean(v) for v in x]
        return x
    v=clean(s);v['fruits'].sort(key=lambda f:json.dumps(f,sort_keys=True));return v


def load_teachers(paths,reservation):
    reserved_seeds={r['seed'] for r in reservation['episodes']};reserved_prefix={r['initial_sequence'] for r in reservation['episodes']}
    rows=[];seen={};policies=set()
    for path in paths:
        for line in Path(path).open(encoding='utf8'):
            if not line.strip():continue
            row=json.loads(line);p=row['provenance'];inp=row['input']
            if set(inp)!={'state','coordinates_A_B','mcts_statistics_A_B'}:raise ValueError('Unexpected input fields')
            if p['source_seed'] in reserved_seeds or p['source_initial_sequence'] in reserved_prefix:raise ValueError('Reserved Test19 group')
            key=json.dumps(dict(state=canonical_state(inp['state']),coordinates=inp['coordinates_A_B'],policy=p['policy_id']),sort_keys=True)
            if key in seen:
                if seen[key]['target']!=row['target']:raise ValueError('Conflicting duplicate root labels')
                continue
            if not all(math.isfinite(float(row['target'][k])) for k in ['mean_delta_B_minus_A','mean_return_A','mean_return_B']):raise ValueError('Unknown/censored label')
            if abs(row['target']['mean_return_B']-row['target']['mean_return_A']-row['target']['mean_delta_B_minus_A'])>1e-6:raise ValueError('Inconsistent return difference')
            policies.add(p['policy_id']);seen[key]=row;rows.append(row)
    if len(policies)!=1:raise ValueError('Mixed continuation/Player; use separate models')
    # Union all original seed OR initial8 links; never split replicas/root siblings.
    parent=list(range(len(rows)));keys={}
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,r in enumerate(rows):
        for key in r['provenance']['split_keys']:
            if key in keys:parent[find(i)]=find(keys[key])
            else:keys[key]=i
    for i,r in enumerate(rows):r['ridge_group']=find(i)
    return rows


def fit(rows,alpha=10.0,margin_scale=.25,max_abs_z=6.0):
    if len(rows)<3:raise ValueError('At least three training roots required')
    x=np.stack([features(**dict(state=r['input']['state'],coordinates=r['input']['coordinates_A_B'],stats=r['input']['mcts_statistics_A_B'])) for r in rows]);y=np.array([r['target']['mean_delta_B_minus_A'] for r in rows])
    counts={g:sum(r['ridge_group']==g for r in rows) for g in {r['ridge_group'] for r in rows}}
    w=np.array([1/counts[r['ridge_group']] for r in rows]);mean=np.average(x,axis=0,weights=w);scale=np.sqrt(np.average((x-mean)**2,axis=0,weights=w));scale[scale<1e-8]=1
    z=(x-mean)/scale;intercept=float(np.average(y,weights=w));cross=z.T@(w[:,None]*z);inv=np.linalg.inv(cross+alpha*np.eye(x.shape[1]));coef=inv@z.T@(w*(y-intercept))
    residual=y-intercept-z@coef;df=float(np.trace(inv@cross));sigma=float(np.sqrt(np.sum(w*residual**2)/max(float(w.sum())-1-df,1)))
    return dict(version=VERSION,feature_names=FEATURE_NAMES,alpha=alpha,mean=mean.tolist(),scale=scale.tolist(),coef=coef.tolist(),intercept=intercept,
        inverse=inv.reshape(-1).tolist(),train_weight=float(w.sum()),residual_scale=sigma,margin_scale=margin_scale,max_abs_z=max_abs_z,
        train_groups=len(counts),train_roots=len(rows),parameters=21,uncertainty_note='Training residual/leverage proxy, not calibrated statistical confidence')


def predict(model,x,guard=True):
    if model['version']!=VERSION or model['feature_names']!=FEATURE_NAMES:raise ValueError('Unsupported feature model')
    x=np.asarray(x,dtype=float);z=(x-model['mean'])/model['scale'];pred=float(model['intercept']+z@model['coef']);inv=np.array(model['inverse']).reshape(20,20)
    uncertainty=float(model['residual_scale']*math.sqrt(max(0,1+1/model['train_weight']+z@inv@z)))
    maxz=float(np.max(np.abs(z)));ood=maxz>model['max_abs_z'];margin=model['margin_scale']*uncertainty if guard else 0
    choose=pred>margin and (not ood or not guard)
    return dict(predicted_delta=pred,uncertainty=uncertainty,max_abs_z=maxz,ood=ood,margin=margin,choose_B=choose,
        reason='ridge_B' if choose else 'out_of_distribution_keep_A' if ood and guard else 'uncertain_keep_A' if pred>0 else 'predicted_A')


def infer_public(model,inp):
    p=predict(model,features(inp['state'],inp['coordinates_A_B'],inp['mcts_statistics_A_B']))
    b=inp['mcts_statistics_A_B'][1]
    if inp['state'].get('game_over') or b['visits']<=0 or b.get('immediate_go',True) or not b.get('drop_success',True) or inp['coordinates_A_B'][0]==inp['coordinates_A_B'][1]:
        p.update(choose_B=False,reason='ineligible_B_keep_A')
    p['selected_x']=inp['coordinates_A_B'][1 if p['choose_B'] else 0]
    return p


def evaluate(rows,predictions):
    result=[]
    for row,p in zip(rows,predictions):
        a=row['target']['mean_return_A'];b=row['target']['mean_return_B'];selected=b if p['choose_B'] else a
        result.append(dict(group=row['ridge_group'],gain=selected-a,return_selected=selected,regret=max(a,b)-selected,
            correct=(p['choose_B']==(b>a)) if a!=b else None,mae=abs(p['predicted_delta']-(b-a))))
    def macro(k):return statistics.mean(statistics.mean(r[k] for r in result if r['group']==g and r[k] is not None) for g in {r['group'] for r in result} if any(r[k] is not None for r in result if r['group']==g))
    return dict(groups=len({r['group'] for r in result}),roots=len(rows),mean_selected_return=macro('return_selected'),gain_vs_A=macro('gain'),
                regret=macro('regret'),ranking_accuracy=macro('correct'),delta_MAE=macro('mae'),B_selected=sum(p['choose_B'] for p in predictions))


def train(protocol,out):
    from watermelon_lab import write,sha
    out=Path(out);out.mkdir(exist_ok=False,parents=True);start=time.perf_counter()
    for d in protocol['datasets']:
        if sha(d['path'])!=d['sha256']:raise ValueError('Frozen training dataset changed')
    rows=load_teachers([r['path'] for r in protocol['datasets']],json.loads((Path(__file__).resolve().parent/'outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text(encoding='utf8')))
    predictions=[None]*len(rows);folds=[]
    for group in sorted({r['ridge_group'] for r in rows}):
        training=[r for r in rows if r['ridge_group']!=group];indices=[i for i,r in enumerate(rows) if r['ridge_group']==group]
        m=fit(training,protocol['alpha'],protocol['margin_scale'],protocol['max_abs_z'])
        for i in indices:
            r=rows[i];predictions[i]=predict(m,features(r['input']['state'],r['input']['coordinates_A_B'],r['input']['mcts_statistics_A_B']))
        folds.append(dict(heldout_source_seeds=[rows[i]['provenance']['source_seed'] for i in indices],train_roots=len(training),train_groups=m['train_groups']))
    model=fit(rows,protocol['alpha'],protocol['margin_scale'],protocol['max_abs_z']);write(out/'model.json',model)
    assert json.loads((out/'model.json').read_text(encoding='utf8'))==model
    aa=[dict(choose_B=False,predicted_delta=0) for r in rows];bb=[dict(choose_B=True,predicted_delta=0) for r in rows]
    cv=dict(always_A=evaluate(rows,aa),always_B=evaluate(rows,bb),ridge=evaluate(rows,predictions),folds=folds,
        scope='Development leave-one-source-group-out only; all roots previously inspected, not independent Test; fixed alpha/feature/gate, no search')
    write(out/'evaluation.json',cv)
    cases=[];in_sample=[]
    for r in rows:
        x=features(r['input']['state'],r['input']['coordinates_A_B'],r['input']['mcts_statistics_A_B']);p=predict(model,x);in_sample.append(p)
        cases.append(dict(state=r['input']['state'],coordinates=r['input']['coordinates_A_B'],stats=r['input']['mcts_statistics_A_B'],features=x.tolist(),prediction=p))
    write(out/'parity_cases.json',dict(cases=cases))
    write(out/'training_manifest.json',dict(roots=len(rows),source_groups=len({r['ridge_group'] for r in rows}),source_seeds=[r['provenance']['source_seed'] for r in rows],
        datasets=protocol['datasets'],model_sha256=sha(out/'model.json'),train_seconds=time.perf_counter()-start,
        in_sample=evaluate(rows,in_sample),independent_test=0,source_policy_ids=sorted({r['provenance']['policy_id'] for r in rows})))
    with (out/'root_predictions.jsonl').open('x',encoding='utf8') as f:
        for r,p in zip(rows,predictions):f.write(json.dumps(dict(source_seed=r['provenance']['source_seed'],target=r['target'],out_of_group=p))+'\n')
    print(json.dumps(dict(roots=len(rows),groups=model['train_groups'],parameters=model['parameters'],evaluation=cv),indent=2))
    return model,rows
