"""Offline fixed-architecture success sampling study. No Unity/collector operations."""
import argparse,csv,json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from collections import defaultdict,Counter
import numpy as np
import torch
from suika_ai.policy_data import load
from suika_ai.policy_model import PolicyBoards,infer
from suika_ai.policy_train import train,load_model,group_average
from suika_ai.policy_metrics import metrics
from suika_ai.value_checkpoint import atomic_json
from suika_ai.policy_success_data import export_value_targets

VARIANTS={'A_normal':1.,'B_success2':2.,'C_success4':4.}

def csv_file(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def summarize(boards,ids,prob):
    records=boards.records;result,rows=metrics(records,ids,prob)
    if not ids:return result,rows
    losses=[]
    for i,p in zip(ids,prob):
        p=np.maximum(p,1e-12);v=np.array(records[i]['visits']);losses.append(-float(v@np.log(p)/v.sum())-.25*float(np.log(p[records[i]['selected_index']])))
    result['group_macro_loss']=group_average(records,ids,losses)
    for key,condition in [('success',lambda r:r.get('watermelon_success') is True),('non_success',lambda r:r.get('watermelon_success') is False),('unknown_success',lambda r:r.get('watermelon_success') is None),('high_search_1024plus',lambda r:r['actual_iterations']>=1024),('natural_distribution',lambda r:r.get('split_purpose')!='success_enrichment'),('enriched_only',lambda r:r.get('split_purpose')=='success_enrichment'),('new_natural_validation',lambda r:r.get('split_purpose')=='fresh_natural')]:
        subset=[(i,p) for i,p in zip(ids,prob) if condition(records[i])];result[key]=metrics(records,[i for i,_ in subset],[p for _,p in subset])[0]
    return result,rows

def bootstrap(records,ids,pa,pb,seed=20261028):
    groups=defaultdict(list)
    for i,a,b in zip(ids,pa,pb):groups[records[i]['group']].append(float(np.argmax(b)==records[i]['selected_index'])-float(np.argmax(a)==records[i]['selected_index']))
    means=np.array([np.mean(v) for v in groups.values()])
    if not len(means):return dict(groups=0)
    rng=np.random.default_rng(seed);est=np.mean(rng.choice(means,(2000,len(means)),replace=True),axis=1)
    return dict(groups=len(means),group_macro_accuracy_difference=float(means.mean()),bootstrap95=[float(np.percentile(est,2.5)),float(np.percentile(est,97.5))],note='Group resampling; descriptive small-sample interval, no multiplicity correction or IID-state claim')

def validation(dataset,output,old_model):
    out=Path(output)
    if (out/'validation.json').exists():raise FileExistsError('Validation already frozen')
    if not(out/'evaluation_plan.json').exists():raise ValueError('Freeze plan first')
    torch.set_num_threads(1);boards=PolicyBoards(load(dataset));r=boards.records;results={};models={};predictions={};per_seed=[]
    for name in list(VARIANTS)+['previous_model']:
        m,payload,path=load_model(old_model if name=='previous_model' else out/name);models[name]=m
        if name in VARIANTS and payload['dataset_fingerprint']!=hashlib.sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest():raise ValueError('Model/dataset fingerprint mismatch')
        for split in ['train','validation']:
            ids=[i for i,x in enumerate(r) if x['split']==split];prob=infer(m,boards,ids);result,rows=summarize(boards,ids,prob);results.setdefault(name,{})[split]=result;predictions[(name,split)]=prob
            csv_file(out/(name+'_'+split+'_predictions.csv'),rows)
            if split=='validation':
                for seed in sorted({r[i]['seed'] for i in ids}):
                    sub=[(i,p) for i,p in zip(ids,prob) if r[i]['seed']==seed];v,_=metrics(r,[i for i,_ in sub],[p for _,p in sub]);per_seed.append(dict(model=name,seed=seed,**v))
        results[name]['best_epoch']=payload['epoch'];results[name]['checkpoint']=str(path.resolve())
    selected=min(VARIANTS,key=lambda name:results[name]['validation']['group_macro_loss'])
    ids=[i for i,x in enumerate(r) if x['split']=='validation'];pairs={name:bootstrap(r,ids,predictions[('A_normal','validation')],predictions[(name,'validation')]) for name in ['B_success2','C_success4']}
    atomic_json(out/'validation.json',dict(results=results,paired_vs_normal=pairs));atomic_json(out/'selection.json',dict(selected=selected,criterion='Full Validation seed-group/episode-macro CE+0.25hardCE; Test unopened',checkpoints={k:v['checkpoint'] for k,v in results.items()}));csv_file(out/'validation_by_seed.csv',per_seed)
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    fig,ax=plt.subplots()
    for name in VARIANTS:
        history=json.loads((out/name/'history.json').read_text());ax.plot([x['epoch'] for x in history],[x['validation_group_loss'] for x in history],label=name)
    ax.set(xlabel='Epoch',ylabel='Validation group loss');ax.legend();fig.tight_layout();fig.savefig(out/'learning_curve.png');plt.close(fig)
    print(json.dumps(dict(selected=selected,validation={k:v['validation']['correct'] for k,v in results.items()}),indent=2));return results

def test(dataset,output):
    out=Path(output)
    if (out/'test_evaluation.json').exists():raise FileExistsError('Test evaluated already; no tuning/re-evaluation')
    selection=json.loads((out/'selection.json').read_text());torch.set_num_threads(1);boards=PolicyBoards(load(dataset));r=boards.records;ids=[i for i,x in enumerate(r) if x['split']=='test'];results={};predictions={};per_seed=[]
    for name,path in selection['checkpoints'].items():
        # Load the exact frozen generation, not a subsequently updated best pointer.
        m,payload,_=load_model(Path(path).parent.parent,which=path)
        if name in VARIANTS and payload['dataset_fingerprint']!=hashlib.sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest():raise ValueError('Model/dataset fingerprint mismatch')
        prob=infer(m,boards,ids);result,rows=summarize(boards,ids,prob);results[name]=result;predictions[name]=prob;csv_file(out/(name+'_test_predictions.csv'),rows)
        for seed in sorted({r[i]['seed'] for i in ids}):
            sub=[(i,p) for i,p in zip(ids,prob) if r[i]['seed']==seed];v,_=metrics(r,[i for i,_ in sub],[p for _,p in sub]);per_seed.append(dict(model=name,seed=seed,**v))
    comparisons={name:bootstrap(r,ids,predictions['A_normal'],predictions[name]) for name in ['B_success2','C_success4']}
    comparisons['new_A_minus_previous']=bootstrap(r,ids,predictions['previous_model'],predictions['A_normal'])
    atomic_json(out/'test_evaluation.json',dict(selected_by_validation=selection['selected'],results=results,paired=comparisons,historical_test='Protected and not evaluated',caution='Imitation metrics only, not game score or watermelon success improvement'));csv_file(out/'test_by_seed.csv',per_seed)
    print(json.dumps({name:v['correct'] for name,v in results.items()},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['train','validation','test','labels']);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--old-model',type=Path,default=Path('outputs/policy_experience_01/deepsets'));a=p.parse_args()
    if not(a.output/'evaluation_plan.json').exists():raise ValueError('Evaluation plan required')
    if a.command=='labels':export_value_targets(a.dataset,a.output/'value_targets_final.jsonl',a.output/'value_target_summary_final.json')
    elif a.command=='train':
        b=PolicyBoards(load(a.dataset))
        for name,weight in VARIANTS.items():train(b,a.dataset,a.output/name,'deepsets',dict(success_multiplier=weight))
    elif a.command=='validation':validation(a.dataset,a.output,a.old_model)
    else:test(a.dataset,a.output)
if __name__=='__main__':main()
