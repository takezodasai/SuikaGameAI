"""One-off frozen Q/V ranking diagnosis on fresh actual returns, with cold physics labeled."""
import json,hashlib,subprocess,time
from pathlib import Path
import numpy as np
import torch
from qv_experiment import ROOT,ActionValue,write
from run_fresh_continuation import read_rows
from suika_ai.value_data import encode
from suika_ai.long_value_model import GeometryValueNetwork,geometry_features
from suika_ai.long_value_train import load_trained
from compare_candidate_value import expected_q,heuristic

def inputs(state,pre=False):
    s=dict(state)
    if pre:
        s={k:state[k] for k in ['fruits','current_fruit','next_fruit_type','score','game_over','fixed_delta_time','ai_move_speed']}
        s['current_fruit']=dict(s['current_fruit'],y_known=False)
    f,g=encode(dict(state=s,geometry=state['geometry']));a=torch.zeros(1,max(1,len(f)),30);m=torch.zeros(1,max(1,len(f)),dtype=torch.bool)
    if f:a[0,:len(f)]=torch.tensor(f);m[0,:len(f)]=True
    return [a,m,torch.tensor([g]),torch.tensor(geometry_features(f,g)).unsqueeze(0)]

def main():
    torch.set_num_threads(1);plan=json.loads((ROOT/'plan.json').read_text());model_root=ROOT/'latest_models';summary=json.loads((model_root/'summary.json').read_text());folder=ROOT/'branch_assessment_04';folder.mkdir(exist_ok=False)
    models={};frozen={}
    for kind in ['Q','V']:
        models[kind]=[]
        for seed in plan['seeds']:
            p=model_root/f'{kind}_{seed}/best.pt';r=torch.load(p,weights_only=True);model=ActionValue() if kind=='Q' else GeometryValueNetwork();model.load_state_dict(r['model']);model.eval();models[kind].append(model);frozen[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    ac,k,_,cp=load_trained(Path('Python/outputs/step8ac_01/geometry'));frozen[str(cp)]=hashlib.sha256(cp.read_bytes()).hexdigest();write(folder/'frozen_models.json',frozen)
    roots=[]
    for i in range(3):
        p=ROOT/f'branches/root_{i}/reference/result.json'
        if p.exists():
            r=json.loads(p.read_text())
            qualified=any(json.loads(q.read_text()).get('end',{}).get('mc_return_known') for q in p.parent.parent.glob('x*/result.json'))
            if r['root'] and qualified:roots.append((f'validation_root_{i}',r['root'],p.parent.parent,False))
    p=Path('Python/outputs/actual_ai_research_01/branch/branch24_f9101_x0p0/result.json');old=json.loads(p.read_text());roots.append(('prior_known_root',old['root'],p.parent.parent,True))
    fixtures=[];byfixture={}
    for name,root,base,oldflag in roots:
        s=root['state'];snapshot=dict(s,current_fruit=dict(s['current_fruit'],y_known=False));p=folder/f'{name}.json';write(p,dict(fruits=s['fruits'],score=s['score'],current_fruit_type=s['current_fruit']['type'],next_fruit_type=s['next_fruit_type'],held_x=s['current_fruit']['x'],drop_cooldown_remaining=s['drop_cooldown_remaining'],game_over_y=s['geometry'][3],snapshot=snapshot,category='cold recreation only; native cache unavailable; held y restored by prefab default, compared against recorded y',reason='Existing helper unconditionally dereferences optional held Rigidbody when applying y; no Player or physics changes'))
        fixtures.append(str(p.resolve()));byfixture[str(p.resolve())]=(name,root,base,oldflag)
    exe=Path('Unity/Builds/FreshBranch_01/SuikaGameAI.exe').resolve();t=time.monotonic();physics_rows=[];failures=[]
    # Separate process per fixture; never rely on same-Player Reset restoration.
    for i,fixture in enumerate(fixtures):
        cfg=folder/f'physics_config_{i}.json';raw=folder/f'cold_predictions_{i}.jsonl';write(cfg,dict(fixtures=[fixture],output=str(raw.resolve()),positions=[0.,.37],seeds=[314159],horizon=1,repeats=1,live=False))
        try:
            r=subprocess.run([str(exe),'-batchmode','-nographics','--suika-listen-port','42160','--suika-python-port','42161','-suikaRuntimeProbe',str((folder/f'runtime_{i}.jsonl').resolve()),'-suikaCounterfactualProbe',str(cfg.resolve()),'-logFile',str((folder/f'player_{i}.log').resolve())],timeout=20,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            if r.returncode:failures.append(dict(fixture=fixture,error='nonzero exit'))
        except subprocess.TimeoutExpired:failures.append(dict(fixture=fixture,error='20s diagnostic limit'))
        if raw.exists():physics_rows.extend(read_rows(raw))
    write(folder/'physics_failures.json',failures)
    ridge=np.load(model_root/'ridge.npz');result=[]
    for line in physics_rows:
        if line.get('error'):continue
        name,root,base,oldflag=byfixture[line['fixture']];x=line['x'];inp=inputs(root['state'],True)
        with torch.inference_mode():q=[float(m(*inp,torch.tensor([x]))*1000) for m in models['Q']]
        vs=[expected_q(m,'geometry',line)[0] for m in models['V']];a=expected_q(ac,k,line)[0]
        z=np.r_[inp[2].numpy()[0],inp[3].numpy()[0],x,x*x];simple=float(np.r_[1,(z-ridge['mean'])/ridge['sd']]@ridge['coef'])
        observed=[]
        pattern='branch24_f*/result.json' if oldflag else 'x*/result.json'
        root_sig=json.dumps({k:root[k] for k in ['tick','state','bodies','rng']},sort_keys=True)
        for p in base.glob(pattern):
            rr=json.loads(p.read_text());c=json.loads((p.parent/'config.json').read_text());end=rr.get('end');other=rr.get('root')
            if abs(c['candidate_x']-x)>1e-5 or not (end and other and end['mc_return_known'] and end['game_over'] and end['prefix_verified'] and rr['exit_code']==0 and not rr['errors'] and not rr['first_mismatch']):continue
            if json.dumps({k:other[k] for k in ['tick','state','bodies','rng']},sort_keys=True)!=root_sig:raise ValueError('Root state differs')
            rows=list(read_rows(p.parent/'trace.jsonl'));acts=[r for r in rows if r['evt']=='action' and r['drops']>root['drops']];s=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]
            for ar in acts:s.append(ar['state']['next_fruit_type'])
            observed.append(dict(future_seed=c['future_seed'],return_points=end['score']-root['score'],seconds=rr['wall_seconds'],public_fruits=s))
        result.append(dict(root=name,prior_diagnostic=oldflag,x=x,observed=observed,mean_observed_return=float(np.mean([o['return_points'] for o in observed])) if observed else None,Q_ensemble=float(np.mean(q)),Q_individual=q,V_ensemble=float(np.mean(vs)),V_individual=vs,AC=a,ridge_Q=simple,heuristic=heuristic(line['first']),predicted_immediate=line['first']['reward'],predicted_GO=line['first']['game_over'],physics_ms=line['elapsed_ms'],held_y_default_error=abs(line['actual_initial']['current_fruit']['y']-root['state']['current_fruit']['y']),actual_root_equals_prediction_root=False))
    comparisons=[]
    for name in sorted({r['root'] for r in result}):
        rows=[r for r in result if r['root']==name];common=set.intersection(*[{o['future_seed'] for o in r['observed']} for r in rows]) if len(rows)==2 else set()
        if not common:continue
        a,b=sorted(rows,key=lambda r:r['x']);diff=[]
        for f in sorted(common):
            aa=next(o for o in a['observed'] if o['future_seed']==f);bb=next(o for o in b['observed'] if o['future_seed']==f);n=min(len(aa['public_fruits']),len(bb['public_fruits']))
            if aa['public_fruits'][:n]!=bb['public_fruits'][:n]:raise ValueError('Common future stream mismatch')
            diff.append(bb['return_points']-aa['return_points'])
        truth=float(np.mean(diff));scores={}
        for model in ['Q_ensemble','V_ensemble','AC','ridge_Q','heuristic']:
            delta=b[model]-a[model];scores[model]=dict(difference_b_minus_a=delta,correct=None if truth==0 else delta*truth>0,realized_regret=abs(truth) if delta*truth<0 else 0)
        comparisons.append(dict(root=name,prior_diagnostic=a['prior_diagnostic'],future_samples=len(common),differences=diff,mean_difference_b_minus_a=truth,models=scores))
    write(folder/'result.json',dict(physics_wall_seconds=time.monotonic()-t,rows=result,comparisons=comparisons,limitations='V uses cold one-step physics with residual state error and C marginalization. Actual natural returns under heuristic continuation; finite futures, not optimal Q. Prior root is not an independent holdout. No fitting on branches.'))

if __name__=='__main__':main()
