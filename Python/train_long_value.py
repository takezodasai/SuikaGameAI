"""STEP8-AC offline-only reproducible training/evaluation CLI. Never launches Unity."""
import argparse,csv,json,time
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import torch
from suika_ai.long_value_data import build,load
from suika_ai.long_value_model import PackedBoards,infer,forward
from suika_ai.long_value_train import train,load_trained,DEFAULTS
from suika_ai.long_value_metrics import point_metrics,matched_pairs,ranking_metrics,paired_mae_interval,near_terminal_ids
from suika_ai.value_train import load_model
from suika_ai.value_checkpoint import atomic_json


def write_csv(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def plan(dataset,out,old):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    value=dict(dataset=str(Path(dataset).resolve()),old_model=str(Path(old).resolve()),config=DEFAULTS,
      models=['train_mean_return','train_mean_final_minus_score','score_count_ridge','frozen_epoch3_v1','retrained_v1','geometry_rank'],
      selection='Validation seed-group macro MSE; no Test tuning. Train maximum30 epochs patience6. Fixed rank weight .05, no hyperparameter search.',
      primary_ranking='Cross-seed pairs: same behavior policy, score bin100, same current/NEXT types, observed return gap>=100; prediction ties<1point count0.5. Not counterfactual action ranking.',
      secondary_ranking='Same matched pairs without behavior-policy matching, separately labeled.',
      sampling='Uniform seed group -> episode -> state, with replacement. NEXT masked50% during training.',
      hypothesis='Geometry features and ranking may help but are not presumed superior. Test is evaluated after both Validation-selected checkpoints are frozen.')
    path=out/'evaluation_plan.json'
    if path.exists():raise FileExistsError(path)
    atomic_json(path,value)


def fit_baselines(boards,ids):
    r=boards.records;eps=Counter(r[i]['episode'] for i in ids);ge=defaultdict(set)
    for i in ids:ge[r[i]['group']].add(r[i]['episode'])
    w=np.array([1/(eps[r[i]['episode']]*len(ge[r[i]['group']])) for i in ids]);w/=w.sum()
    score=np.array([x['score'] for x in r]);count=np.array([x['fruit_count'] for x in r]);target=np.array([x['target'] for x in r]);terminal=np.array([x['game_over'] for x in r])
    constant=np.full(len(r),float(w@target[ids]));final=np.maximum(0,float(w@(target[ids]+score[ids]))-score);final=np.maximum(0,final)
    x=np.column_stack([np.ones(len(r)),score/1000,count/30]);a=x[ids];ridge=np.diag([0,.001,.001]);coef=np.linalg.solve(a.T@(w[:,None]*a)+ridge,a.T@(w*(target[ids]/1000)))
    predictions=dict(train_mean_return=constant,train_mean_final_minus_score=final,score_count_ridge=np.maximum(0,x@coef*1000))
    for v in predictions.values():v[terminal]=0
    return predictions,dict(mean_return=float(w@target[ids]),mean_final=float(w@(target[ids]+score[ids])),ridge_coefficients=coef.tolist(),terminal='All baselines use known-GO return0')


def evaluate(dataset,output,old):
    output=Path(output)
    if (output/'evaluation.json').exists():raise FileExistsError('Evaluation already frozen; use a new output for a separately declared experiment')
    if not (output/'evaluation_plan.json').exists():raise ValueError('Freeze evaluation plan before training')
    torch.set_num_threads(1);begin=time.monotonic();boards=PackedBoards(load(dataset));r=boards.records;n=len(r);all_ids=list(range(n));splits={s:[i for i,v in enumerate(r) if v['split']==s] for s in ('train','validation','test')}
    predictions,baseline=fit_baselines(boards,splits['train']);models={};checkpoints={}
    old_model,old_payload,path=load_model(old);models['frozen_epoch3_v1']=(old_model,'v1');checkpoints['frozen_epoch3_v1']=dict(path=str(path),epoch=old_payload['epoch'])
    for name,folder in [('retrained_v1','v1'),('geometry_rank','geometry')]:
        model,kind,payload,path=load_trained(output/folder);models[name]=(model,kind);checkpoints[name]=dict(path=str(path),epoch=payload['epoch'],parameters=sum(p.numel() for p in model.parameters()))
    for name,(model,kind) in models.items():predictions[name]=infer(model,kind,boards,all_ids)
    results={};rank_pairs={};pair_files=[]
    for split,ids in splits.items():
        primary=matched_pairs(r,ids);secondary=matched_pairs(r,ids,same_policy=False);rank_pairs[split]=(primary,secondary)
        write_csv(output/(split+'_ranking_pairs.csv'),[dict(a=int(a),b=int(b),target_a=r[a]['target'],target_b=r[b]['target']) for a,b in primary])
        results[split]={name:dict(**point_metrics(r,ids,p),ranking_same_policy=ranking_metrics(r,values,primary),ranking_mixed_policy=ranking_metrics(r,values,secondary)) for name,values in predictions.items() for p in [values[ids]]}
    ablations={}
    # Diagnostic only: preserve scores/counts/held/NEXT; replace fruit geometry with Train averages. No fitting or model selection on Test.
    test=splits['test'];model,kind=models['geometry_rank'];altered=[];original=boards.geometry.copy()
    boards.geometry[test]=np.mean(original[splits['train']],axis=0)
    for start in range(0,len(test),128):
        ids=test[start:start+128];inputs=list(boards.batch(ids));inputs[0][:,:,11:18]=0;inputs[0][:,:,20:26]=0;altered.extend((forward(model,kind,inputs).detach()*1000).tolist())
    boards.geometry=original;ablations['geometry_rank_board_geometry_removed']=point_metrics(r,test,altered)
    near_keys={(r[i]['episode'],r[i]['action_id']) for i in near_terminal_ids(r,test)}
    details=[];episode_rows=[]
    for name,values in predictions.items():
        for field,group_function in [('score_band',lambda v:str((v['score']//500)*500)),('fruit_count_band',lambda v:str((v['fruit_count']//10)*10)),('near_go',lambda v:'last5_nonterminal' if (v['episode'],v['action_id']) in near_keys else 'terminal' if v['game_over'] else 'earlier'),('policy',lambda v:v['policy'])]:
            groups=defaultdict(list)
            for i in test:groups[group_function(r[i])].append(i)
            for group,ids in groups.items():details.append(dict(model=name,field=field,band=group,**point_metrics(r,ids,values[ids])))
        episodes=defaultdict(list)
        for i in test:episodes[r[i]['episode']].append(i)
        for ep,ids in episodes.items():episode_rows.append(dict(model=name,episode=ep,seed=r[ids[0]]['seed'],**point_metrics(r,ids,values[ids])))
    over=[]
    p=predictions['geometry_rank'];worst=sorted(test,key=lambda i:p[i]-r[i]['target'],reverse=True)[:20]
    for i in worst:over.append(dict(index=i,episode=r[i]['episode'],seed=r[i]['seed'],score=r[i]['score'],fruit_count=r[i]['fruit_count'],steps_to_go=r[i]['steps_to_go'],target=r[i]['target'],prediction=float(p[i]),overestimate=float(p[i]-r[i]['target'])))
    timing={}
    for name,(model,kind) in models.items():
        timing[name]={}
        for number in (1,5):
            ids=sorted(test,key=lambda i:r[i]['fruit_count'],reverse=True)[:number];inputs=boards.batch(ids)
            with torch.inference_mode():
                for _ in range(10):forward(model,kind,inputs)
                times=[]
                for _ in range(100):
                    t=time.perf_counter();forward(model,kind,inputs);times.append((time.perf_counter()-t)*1000)
            timing[name][str(number)]=dict(median_ms=float(np.median(times)),p95_ms=float(np.quantile(times,.95)),scope='CPU model only; excludes JSON, encoding and geometry extraction')
    report=dict(results=results,baselines=baseline,checkpoints=checkpoints,ablations=ablations,inference=timing,
      test_paired_macro_mae_difference_new_minus_retrained=paired_mae_interval(r,test,predictions['geometry_rank'][test],predictions['retrained_v1'][test]),evaluation_seconds=time.monotonic()-begin,
      caveats=['Only6Test seed groups; bootstrap uncertainty is approximate. Observed behavior-policy returns are not optimal returns. Ranking is across actual boards, not alternative actions from one board.','Board-removal diagnostic changes input distribution and does not prove causal use of geometric strategy.'])
    atomic_json(output/'evaluation.json',report);write_csv(output/'test_bands.csv',details);write_csv(output/'test_episodes.csv',episode_rows);write_csv(output/'overestimates.csv',over)
    write_csv(output/'predictions.csv',[dict(index=i,split=r[i]['split'],episode=r[i]['episode'],seed=r[i]['seed'],score=r[i]['score'],target=r[i]['target'],**{k:float(v[i]) for k,v in predictions.items()}) for i in all_ids])
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for folder in ('v1','geometry'):
        history=json.loads((output/folder/'history.json').read_text());axes[0].plot([v['epoch'] for v in history],[v['training_mse']**.5*1000 for v in history],label=folder+' sampled train');axes[0].plot([v['epoch'] for v in history],[v['validation_group_rmse_points'] for v in history],label=folder+' validation')
    axes[0].set(xlabel='Epoch',ylabel='RMSE (points)');axes[0].legend(fontsize=7)
    axes[1].scatter([r[i]['target'] for i in test],predictions['geometry_rank'][test],s=3,alpha=.2);axes[1].set(xlabel='Observed future score',ylabel='Predicted future score');fig.tight_layout();fig.savefig(output/'evaluation.png',dpi=150);plt.close(fig)
    print(json.dumps(report,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','plan','train','evaluate','predict']);p.add_argument('--dataset',required=True);p.add_argument('--output');p.add_argument('--inputs',nargs='+');p.add_argument('--old-model',default='outputs/value_train_100_01');p.add_argument('--old-manifest',default='outputs/value_data_100_01/manifest.json');p.add_argument('--kind',choices=['v1','geometry'],default='geometry');p.add_argument('--epochs',type=int,default=30);p.add_argument('--resume',action='store_true');p.add_argument('--indices',type=int,nargs='+',default=[0]);a=p.parse_args()
    if a.command=='prepare':build(a.inputs,a.dataset,old_manifest=a.old_manifest)
    elif a.command=='plan':plan(a.dataset,a.output,a.old_model)
    elif a.command=='train':
        base=Path(a.output)
        if not (base/'evaluation_plan.json').exists():raise ValueError('Run plan first')
        if (base/'evaluation.json').exists():raise ValueError('Do not retrain after frozen Test evaluation; declare a new experiment')
        train(PackedBoards(load(a.dataset)),a.dataset,base/a.kind,a.kind,dict(epochs=a.epochs),a.resume)
    elif a.command=='predict':
        boards=PackedBoards(load(a.dataset));model,kind,payload,path=load_trained(Path(a.output)/a.kind)
        if any(i<0 or i>=len(boards.records) for i in a.indices):raise ValueError('Invalid state index')
        print(json.dumps(dict(checkpoint=str(path),epoch=payload['epoch'],predictions=[dict(index=i,predicted_future_score=float(v)) for i,v in zip(a.indices,infer(model,kind,boards,a.indices))]),indent=2))
    else:evaluate(a.dataset,a.output,a.old_model)
if __name__=='__main__':main()
