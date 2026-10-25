"""Offline frozen-model assessment. Never trains or controls a game."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
import numpy as np
from suika_ai.value_data import load_dataset,INPUT_SPEC
from suika_ai.value_model import predict
from suika_ai.value_checkpoint import load_checkpoint
from suika_ai.value_train import load_model,evaluate,write_reports,point_metrics,benchmark


def score_only(sample):
    s=sample['state']
    return dict(sample,geometry=None,state=dict(fruits=[],current_fruit=dict(present=False,type=-1,x=0.),next_fruit_type=-1,score=s['score'],game_over=s['game_over']))


def masked_snapshot(sample,mode):
    s=copy.deepcopy(sample)
    if mode in ('unknown_next','simulator_missing'):
        s['state']['next_fruit_type']=-1
    if mode=='simulator_missing':
        held=s['state'].get('current_fruit') or {};held.pop('y',None);held['y_known']=False
        for f in s['state']['fruits']:
            f['observation_metadata_known']=False;f['collider_measurement_known']=False
    return s


def cluster_intervals(samples,predictions,comparators,repeats=3000):
    """Resample complete seed/initial-sequence clusters, not individual states."""
    groups=sorted({s['group'] for s in samples});index={g:i for i,g in enumerate(groups)}
    g=np.array([index[s['group']] for s in samples]);target=np.array([s['target'] for s in samples]);errors=np.array(predictions)-target
    n=np.bincount(g,minlength=len(groups));absolute=np.bincount(g,weights=np.abs(errors),minlength=len(groups));squared=np.bincount(g,weights=errors**2,minlength=len(groups))
    reference={name:np.bincount(g,weights=np.abs(np.array(values)-target),minlength=len(groups)) for name,values in comparators.items()}
    rng=np.random.default_rng(2026);mae=[];rmse=[];deltas={k:[] for k in reference}
    for _ in range(repeats):
        chosen=rng.integers(0,len(groups),size=len(groups));count=n[chosen].sum()
        error=absolute[chosen].sum()/count;mae.append(error);rmse.append(np.sqrt(squared[chosen].sum()/count))
        for name,values in reference.items():deltas[name].append(values[chosen].sum()/count-error)
    def interval(values):return dict(lower=float(np.quantile(values,.025)),upper=float(np.quantile(values,.975)))
    return dict(unit='seed/initial-sequence group',groups=len(groups),resamples=repeats,mae=interval(mae),rmse=interval(rmse),mae_reduction={k:interval(v) for k,v in deltas.items()})


def board_shuffled(samples):
    """Swap real boards between different episodes with same count/100-point score bin."""
    groups={}
    for i,s in enumerate(samples):
        if s['state']['game_over']:continue
        key=(len(s['state']['fruits']),s['state']['score']//100);groups.setdefault(key,[]).append(i)
    rng=random.Random(2026);result=[];indices=[]
    for positions in groups.values():
        for i in positions:
            choices=[j for j in positions if samples[j]['episode']!=samples[i]['episode']]
            if not choices:continue
            j=rng.choice(choices);s=samples[i];state=dict(s['state'],fruits=samples[j]['state']['fruits'])
            result.append(dict(s,state=state));indices.append(i)
    return result,indices


def board_summary(sample,prediction):
    s=sample['state'];geo=sample.get('geometry');fruits=s['fruits'];armed=[f for f in fruits if f.get('has_collided')]
    return dict(episode=sample['episode'],seed=sample['seed'],action_id=sample['action_id'],score=s['score'],target=sample['target'],prediction=prediction,error=prediction-sample['target'],
        fruit_count=len(fruits),types={str(k):sum(f['type']==k for f in fruits) for k in range(11)},steps_to_go=sample.get('steps_to_go'),game_over=s['game_over'],
        small_fruit_count=sum(f['type']<=2 for f in fruits),touching_count=sum(f.get('touching') is True for f in fruits),sleeping_count=sum(f.get('sleeping') is True for f in fruits),
        armed_center_margin_to_go=(geo[3]-max(f['y'] for f in armed)) if geo and armed else None,
        highest_collider_top=max((f['y']+f.get('half_height',0) for f in fruits),default=None))


def plots(output,samples,predictions):
    from matplotlib.figure import Figure
    fig=Figure(figsize=(11,4),layout='constrained');a,b=fig.subplots(1,2)
    target=np.array([s['target'] for s in samples]);prediction=np.array(predictions);score=[s['state']['score'] for s in samples]
    a.scatter(target,prediction,s=8,alpha=.3);limit=max(target.max(),prediction.max());a.plot([0,limit],[0,limit],color='black');a.set(xlabel='Actual remaining points',ylabel='Predicted remaining points',title='Frozen Test: 15 episodes')
    b.scatter(score,prediction-target,s=8,alpha=.3);b.axhline(0,color='black');b.set(xlabel='Current score',ylabel='Prediction - target (points)',title='Over/underprediction')
    for ax in (a,b):ax.grid(alpha=.2)
    fig.savefig(output/'test_predictions.png',dpi=150);fig.savefig(output/'test_predictions.svg')


def assess(data,model_output,comparison_data,comparison_output,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest,samples,fingerprint=load_dataset(data);cm,cs,cf=load_dataset(comparison_data)
    if cm.get('parent_fingerprint')!=fingerprint:raise ValueError('Comparison must mask this same dataset')
    if [(s['episode'],s['action_id'],s['target'],s['split']) for s in samples]!=[(s['episode'],s['action_id'],s['target'],s['split']) for s in cs]:raise ValueError('Comparison labels/split differ')
    model,payload,path=load_model(model_output);other,op,other_path=load_model(comparison_output)
    if payload['dataset_fingerprint']!=fingerprint or op['dataset_fingerprint']!=cf:raise ValueError('Checkpoint/dataset mismatch')
    # Freeze both selected checkpoint identities before evaluating any Test predictions.
    plan=dict(input_spec=INPUT_SPEC,data_fingerprint=fingerprint,test_used_for_model_selection=False,
        primary=dict(checkpoint=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),selected_epoch=payload['epoch']),
        score_only=dict(checkpoint=str(other_path),sha256=hashlib.sha256(other_path.read_bytes()).hexdigest(),selected_epoch=op['epoch']),
        config=payload['config'],selection='minimum Validation MSE independently for each predeclared model')
    (output/'evaluation_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    started=time.perf_counter();metrics,rows=evaluate(model,samples,splits=('train','validation','test'))
    latest,_=load_checkpoint(Path(model_output)/'checkpoints','latest')
    write_reports(output,metrics,rows,latest['history'])
    other_metrics,_=evaluate(other,cs,splits=('train','validation','test'))
    test=[s for s in samples if s['split']=='test'];test_rows=[r for r in rows if r['split']=='test'];pred=[r['prediction'] for r in test_rows];target=[s['target'] for s in test]
    other_pred=predict(other,[score_only(s) for s in test]);constant=[metrics['baseline_training_mean']]*len(test)
    final_mean=float(np.mean([e['final_score'] for e in manifest['episodes'] if e['split']=='train']))
    final_prediction=[0. if s['state']['game_over'] else max(0.,final_mean-s['state']['score']) for s in test]
    diagnostics={}
    for mode in ('unknown_next','simulator_missing'):
        values=predict(model,[masked_snapshot(s,mode) for s in test]);diagnostics[mode]=dict(metrics=point_metrics(target,values),mean_absolute_prediction_change=float(np.mean(np.abs(np.array(values)-pred))))
    reversed_samples=[dict(s,state=dict(s['state'],fruits=list(reversed(s['state']['fruits'])))) for s in test]
    reverse=predict(model,reversed_samples);diagnostics['permutation_max_difference_points']=float(np.max(np.abs(np.array(reverse)-pred)))
    changed,indices=board_shuffled(test)
    if changed:
        shuffled=predict(model,changed);original=[pred[i] for i in indices];ts=[target[i] for i in indices]
        diagnostics['board_swap']=dict(n=len(changed),original=point_metrics(ts,original),shuffled=point_metrics(ts,shuffled),mean_absolute_prediction_change=float(np.mean(np.abs(np.array(shuffled)-original))),caution='Real-board swaps can create inconsistent held/board contexts; sensitivity is diagnostic, not a causal performance estimate.')
    for label,chosen in [('nonterminal',[i for i,s in enumerate(test) if not s['state']['game_over']]),('last5_nonterminal',[i for i,s in enumerate(test) if not s['state']['game_over'] and s.get('steps_to_go',999)<=5])]:
        diagnostics[label]=dict(n=len(chosen),model=point_metrics([target[i] for i in chosen],[pred[i] for i in chosen]),score_only=point_metrics([target[i] for i in chosen],[other_pred[i] for i in chosen]))
    cases=sorted([board_summary(s,p) for s,p in zip(test,pred) if not s['state']['game_over']],key=lambda s:s['error'],reverse=True)
    unique=[];seen=set()
    for case in cases:
        if case['episode'] not in seen:unique.append(case);seen.add(case['episode'])
        if len(unique)==5:break
    stratified={}
    for name,predicate in [('near_line',lambda s:board_summary(s,0)['armed_center_margin_to_go'] is not None and board_summary(s,0)['armed_center_margin_to_go']<.25),('high_count',lambda s:len(s['state']['fruits'])>=30),('many_small',lambda s:sum(f['type']<=2 for f in s['state']['fruits'])>=10)]:
        ids=[i for i,s in enumerate(test) if not s['state']['game_over'] and predicate(s)]
        stratified[name]=point_metrics([target[i] for i in ids],[pred[i] for i in ids]) if ids else None
    result=dict(primary=metrics,score_only=other_metrics,constant_final_score_baseline=dict(training_episode_mean=final_mean,test=point_metrics(target,final_prediction)),
        test_cluster_bootstrap=cluster_intervals(test,pred,dict(constant=constant,score_only=other_pred)),diagnostics=diagnostics,worst_unique_episodes=unique,stratified=stratified,
        inference=benchmark(model,test),evaluation_wall_seconds=time.perf_counter()-started,
        limitations=['Monte Carlo value of the heuristic behavior policy, not optimal policy value','15 Test groups only; bootstrap is conditional on this cohort','No candidate action ranking or real-game score comparison performed','No full-input model retuning after Test was opened'])
    (output/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    plots(output,test,pred)
    print(json.dumps(dict(primary=metrics['splits'],score_only=other_metrics['splits'],confidence=result['test_cluster_bootstrap'],diagnostics=diagnostics,inference=result['inference']),indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('data','model','comparison-data','comparison-model','output'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();assess(a.data,a.model,a.comparison_data,a.comparison_model,a.output)
