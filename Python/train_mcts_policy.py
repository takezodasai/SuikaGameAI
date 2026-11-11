"""Offline policy learning only. Never launches, stops or modifies a collector."""
import argparse,json,csv,time,sys
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
import numpy as np
import torch
from suika_ai.policy_data import build,load
from suika_ai.policy_model import PolicyBoards,infer
from suika_ai.policy_train import train,load_model,DEFAULTS
from suika_ai.policy_metrics import metrics,prior_fit,prior_predict
from suika_ai.learning_events import rewards
from suika_ai.value_checkpoint import atomic_json

def write_csv(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def evaluate(dataset,out):
    out=Path(out)
    if (out/'evaluation.json').exists():raise FileExistsError('Test evaluation already frozen')
    if not (out/'evaluation_plan.json').exists():raise ValueError('Freeze plan before training')
    torch.set_num_threads(1);b=PolicyBoards(load(dataset));r=b.records;prior=prior_fit(r);models={};checkpoints={}
    for kind in ('globals','deepsets'):
        model,payload,path=load_model(out/kind)
        expected=__import__('hashlib').sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest()
        if payload['dataset_fingerprint']!=expected:raise ValueError('Model/dataset mismatch')
        models[kind]=model;checkpoints[kind]=dict(path=str(path.resolve()),epoch=payload['epoch'])
    results={};all_predictions={};per_seed=[]
    for split in ('train','validation','test'):
        ids=[i for i,x in enumerate(r) if x['split']==split];results[split]={};all_predictions[split]={}
        predictions={'position_prior':prior_predict(prior,r,ids)}
        for kind,model in models.items():predictions[kind]=infer(model,b,ids)
        for name,prob in predictions.items():
            result,rows=metrics(r,ids,prob);results[split][name]=result;all_predictions[split][name]=prob;write_csv(out/(split+'_'+name+'_predictions.csv'),rows)
            for seed in sorted({r[i]['seed'] for i in ids}):
                keep=[(i,p) for i,p in zip(ids,prob) if r[i]['seed']==seed];s,_=metrics(r,[a for a,_ in keep],[p for _,p in keep]);per_seed.append(dict(split=split,model=name,seed=seed,**s))
            for label,condition in [('high_search_1024plus',lambda x:x['actual_iterations']>=1024),('candidates5',lambda x:len(x['candidate_x'])==5),('candidates9',lambda x:len(x['candidate_x'])==9),('last20_score_fraction',lambda x:x['score']>=x['final_score']*.8)]:
                keep=[(i,p) for i,p in zip(ids,prob) if condition(r[i])];result[label]=metrics(r,[a for a,_ in keep],[p for _,p in keep])[0]
        # MCTS is the reference teacher, not a neural inference baseline or measured game score advantage.
        results[split]['teacher_reference']=dict(samples=len(ids),accuracy_against_own_selection=1.,mean_logged_thinking_ms=float(np.mean([r[i]['thinking_ms'] for i in ids])),note='Identity by definition; logged collection timings, not a new benchmark. Root visits and values are targets, not proof of optimal play.')
    test=[i for i,x in enumerate(r) if x['split']=='test'];original=b.arrays['fruits'].copy();train_ids=[i for i,x in enumerate(r) if x['split']=='train'];offset=b.arrays['offsets']
    # Predeclared diagnostic: remove fruit geometry/motion, retain fruit types and global context. No Test refit.
    parts=[original[offset[i]:offset[i+1],11:18] for i in train_ids if offset[i+1]>offset[i]];mean=np.concatenate(parts).mean(0)
    for i in test:b.arrays['fruits'][offset[i]:offset[i+1],11:18]=mean
    ablation=metrics(r,test,infer(models['deepsets'],b,test))[0];b.arrays['fruits'][:]=original
    times={}
    for name,model in models.items():
        values=[];inputs,_,_,_=b.batch([test[len(test)//2]])
        with torch.inference_mode():
            for _ in range(20):model(*inputs)
            for _ in range(200):
                t=time.perf_counter();model(*inputs);values.append((time.perf_counter()-t)*1000)
        times[name]=dict(batch_boards=1,candidates=int(inputs[-1].sum()),median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)),scope='FP32 CPU one thread forward only; preprocessing/IPC excluded')
    by_episode={e['id']:e for e in b.manifest['episodes']};events={}
    for kind in ('watermelon_one','watermelon_melon_one','watermelon_melon_two','watermelon_two','double_watermelon'):
        known=[e for e in by_episode.values() if e['events']['labels'][kind]['known']];events[kind]=dict(evaluable_games=len(known),achieved_games=sum(e['events']['labels'][kind]['achieved'] for e in known),unknown_games=len(by_episode)-len(known))
    result=dict(results=results,checkpoints=checkpoints,geometry_ablation_test=ablation,inference=times,event_coverage=events,limitations=['Only fresh seed groups are Test; small count limits generalization claims','Imitation is not evidence of stronger or equally strong gameplay','Mixed teacher policies/iteration caps are not equally optimal','Old transient melon events absent -> unknown, not failure','Missing decision-source y/cooldown/optional physics fields remain masked'])
    write_csv(out/'per_seed.csv',per_seed);atomic_json(out/'evaluation.json',result)
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    fig,ax=plt.subplots()
    for kind in models:
        history=json.loads((out/kind/'history.json').read_text());ax.plot([v['epoch'] for v in history],[v['validation_group_loss'] for v in history],label=kind+' validation');ax.plot([v['epoch'] for v in history],[v['training_loss'] for v in history],linestyle='--',label=kind+' train weighted')
    ax.set(xlabel='Epoch',ylabel='Cross entropy + 0.25 hard CE');ax.legend();fig.tight_layout();fig.savefig(out/'learning_curve.png');plt.close(fig)
    print(json.dumps(result,indent=2));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('prepare');d.add_argument('--inventory',type=Path,required=True);d.add_argument('--output',type=Path,required=True);d.add_argument('--old-ac',type=Path,required=True);d.add_argument('--old-tests',type=Path,nargs='*',default=[])
    t=sub.add_parser('train');t.add_argument('--dataset',type=Path,required=True);t.add_argument('--output',type=Path,required=True);t.add_argument('--kind',choices=['globals','deepsets'],required=True);t.add_argument('--epochs',type=int,default=20);t.add_argument('--resume',action='store_true');t.add_argument('--success-multiplier',type=float,choices=[1,2,4],default=1)
    e=sub.add_parser('evaluate');e.add_argument('--dataset',type=Path,required=True);e.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('predict');q.add_argument('--dataset',type=Path,required=True);q.add_argument('--model',type=Path,required=True);q.add_argument('--indices',type=int,nargs='+',required=True)
    w=sub.add_parser('rewards');w.add_argument('--dataset',type=Path,required=True);w.add_argument('--weights',type=Path,required=True);w.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':build(a.inventory,a.output,a.old_ac,a.old_tests)
    elif a.command=='train':train(PolicyBoards(load(a.dataset)),a.dataset,a.output,a.kind,dict(epochs=a.epochs,success_multiplier=a.success_multiplier),a.resume)
    elif a.command=='evaluate':evaluate(a.dataset,a.output)
    elif a.command=='predict':
        torch.set_num_threads(1);b=PolicyBoards(load(a.dataset));m,_,_=load_model(a.model)
        for i,prob in zip(a.indices,infer(m,b,a.indices)):print(json.dumps(dict(index=i,candidate_x=b.records[i]['candidate_x'],probabilities=prob,selected_x=b.records[i]['candidate_x'][int(np.argmax(prob))])))
    else:
        if a.output.exists():raise FileExistsError(a.output)
        m=load(a.dataset)[0];weights=json.loads(a.weights.read_text());atomic_json(a.output,[dict(episode=e['id'],**rewards(e['events'],weights)) for e in m['episodes']])
if __name__=='__main__':main()
