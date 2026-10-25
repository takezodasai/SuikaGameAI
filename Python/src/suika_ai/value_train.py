"""Offline supervised value training, metrics and reproducible optimizer-boundary resume."""
import csv
import io
import json
import math
from pathlib import Path
import random
import signal
import statistics
import time
import numpy as np
import torch
from .value_data import INPUT_SPEC,SCORE_SCALE,load_dataset
from .value_model import ValueNetwork,encoded_rows,batch,predict
from .value_checkpoint import atomic_bytes,atomic_json,save_checkpoint,load_checkpoint

DEFAULT_CONFIG=dict(epochs=30,lr=.001,batch_size=128,optimizer='adamw',loss='mse',huber_delta=1.,
    weight_decay=.0001,width=64,head_width=128,seed=2026,threads=1,next_mask_probability=.5,
    scheduler_patience=5,scheduler_factor=.5,early_stop_patience=20,save_seconds=300.,precision='fp32')

def config_checked(settings):
    if set(settings)-DEFAULT_CONFIG.keys():raise ValueError('unknown training setting')
    cfg=dict(DEFAULT_CONFIG,**settings)
    for k in ('epochs','batch_size','width','head_width','threads','scheduler_patience','early_stop_patience'):
        if type(cfg[k]) is not int or cfg[k]<1:raise ValueError('invalid '+k)
    for k in ('lr','huber_delta','weight_decay','save_seconds'):
        if type(cfg[k]) not in (int,float) or not math.isfinite(cfg[k]) or cfg[k]<0 or (k!='weight_decay' and cfg[k]==0):raise ValueError('invalid '+k)
    if cfg['optimizer'] not in ('adamw','adam','sgd') or cfg['loss'] not in ('mse','huber') or cfg['precision']!='fp32':raise ValueError('unsupported optimizer/loss/precision')
    if not 0<=cfg['next_mask_probability']<=1 or not 0<cfg['scheduler_factor']<1 or type(cfg['seed']) is not int or not 0<=cfg['seed']<2**32:raise ValueError('invalid probability/seed')
    return cfg

def rng_state():
    ns=np.random.get_state()
    return dict(python=random.getstate(),numpy=[ns[0],ns[1].tolist(),ns[2],ns[3],ns[4]],torch=torch.get_rng_state(),cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [])
def restore_rng(value):
    random.setstate(value['python']);ns=value['numpy'];np.random.set_state((ns[0],np.array(ns[1],dtype=np.uint32),ns[2],ns[3],ns[4]));torch.set_rng_state(value['torch'])
    if value['cuda'] and torch.cuda.is_available():torch.cuda.set_rng_state_all(value['cuda'])

def point_metrics(target,prediction):
    errors=[p-t for t,p in zip(target,prediction)];n=len(errors)
    return dict(n=n,mae=sum(abs(e) for e in errors)/n,rmse=math.sqrt(sum(e*e for e in errors)/n),bias=sum(errors)/n,
        mse_scaled=sum(e*e for e in errors)/n/(SCORE_SCALE*SCORE_SCALE))

def evaluate(model,samples,batch_size=128,splits=None,baseline_override=None):
    train=[s for s in samples if s['split']=='train'];baseline=sum(s['target'] for s in train)/len(train) if baseline_override is None else baseline_override
    results={};comparisons=[];episode_rows={}
    for split in (splits or ('train','validation')):
        if split not in ('train','validation','test'):raise ValueError('Invalid evaluation split')
        selected=[s for s in samples if s['split']==split]
        if not selected:raise ValueError('No samples in requested split: '+split)
        prediction=predict(model,selected,batch_size=batch_size);target=[s['target'] for s in selected]
        results[split]=dict(model=point_metrics(target,prediction),baseline=point_metrics(target,[baseline]*len(target)))
        for sample,pred in zip(selected,prediction):
            row=dict(split=split,episode=sample['episode'],seed=sample['seed'],action_id=sample['action_id'],score=sample['state']['score'],fruit_count=len(sample['state']['fruits']),target=sample['target'],prediction=pred,baseline=baseline,error=pred-sample['target'],steps_to_go=sample.get('steps_to_go'),policy=sample.get('policy','unknown'))
            comparisons.append(row);episode_rows.setdefault(sample['episode'],[]).append(row)
    episodes=[dict(episode=ep,split=rows[0]['split'],seed=rows[0]['seed'],**point_metrics([r['target'] for r in rows],[r['prediction'] for r in rows])) for ep,rows in episode_rows.items()]
    bands={}
    for split in results:
        rows=[r for r in comparisons if r['split']==split]
        def measures(items):
            return point_metrics([r['target'] for r in items],[r['prediction'] for r in items]) if items else None
        bands[split]=dict(
            by_score={f'{low}-{high}':measures([r for r in rows if low<=r['score']<high]) for low,high in [(0,500),(500,1000),(1000,2000),(2000,1000000000)]},
            by_fruit_count={f'{low}-{high}':measures([r for r in rows if low<=r['fruit_count']<high]) for low,high in [(0,10),(10,20),(20,40),(40,1000000)]},
            last_five_actions=measures([r for r in rows if r['steps_to_go'] is not None and r['steps_to_go']<=5]),
            largest_overpredictions=sorted([r for r in rows if r['error']>0],key=lambda r:r['error'],reverse=True)[:20],
            episode_macro_mae=statistics.mean(e['mae'] for e in episodes if e['split']==split))
    return dict(splits=results,baseline_training_mean=baseline,episodes=episodes,breakdowns=bands),comparisons

def external_test_context(model_output,manifest,samples,payload):
    """Explicit final-test-only comparison of old/new models on the same frozen holdout."""
    run=json.loads((Path(model_output)/'run.json').read_text(encoding='utf-8'))
    original,old_samples,identity=load_dataset(run['dataset'])
    if identity!=payload['dataset_fingerprint']:raise ValueError('Original model dataset no longer matches checkpoint')
    seen=[ep for ep in original['episodes'] if ep['split'] in ('train','validation')]
    heldout=[ep for ep in manifest['episodes'] if ep['split']=='test']
    if {ep['seed'] for ep in seen}&{ep['seed'] for ep in heldout}:raise ValueError('External Test overlaps model train/validation seeds')
    if {ep['id'] for ep in seen}&{ep['id'] for ep in heldout}:raise ValueError('External Test overlaps model train/validation episodes')
    from .collection_audit import initial_sequence
    prefixes=set();unknown=0
    for ep in seen:
        prefix=ep.get('initial_sequence')
        if not prefix and Path(ep['source']).is_file():
            rows=[]
            with Path(ep['source']).open(encoding='utf-8-sig') as file:
                for line in file:
                    try:row=json.loads(line)
                    except ValueError:break
                    if '|'.join(str(row.get(k)) for k in ('game_id','stream_id','episode_id'))==ep['id']:rows.append(row)
            prefix=initial_sequence(rows)
        if prefix:prefixes.add(prefix)
        else:unknown+=1
    if prefixes&{ep.get('initial_sequence') for ep in heldout}:raise ValueError('External Test overlaps observed initial fruit sequences')
    training=[s['target'] for s in old_samples if s['split']=='train']
    return sum(training)/len(training),dict(original_dataset_fingerprint=identity,
        checked_initial_prefixes=len(prefixes),unknown_initial_prefix_episodes=unknown,
        warning='Different policies/environments may cause distribution shift. Prefix checking cannot prove complete RNG independence.')


def write_reports(output,metrics,comparisons,history):
    output=Path(output);atomic_json(output/'metrics.json',metrics)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(comparisons[0]));writer.writeheader();writer.writerows(comparisons);atomic_bytes(output/'predictions.csv',stream.getvalue().encode('utf-8'))
    stream=io.StringIO();fields=['epoch','updates','training_loss','train_mse','validation_mse','baseline_validation_mse','lr'];writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(history);atomic_bytes(output/'learning_curve.csv',stream.getvalue().encode('utf-8'))
    if history:
        from matplotlib.figure import Figure
        figure=Figure(figsize=(8,4.5),layout='constrained');axes=figure.subplots()
        for key,label in [('train_mse','Train'),('validation_mse','Validation'),('baseline_validation_mse','Constant baseline')]:
            axes.plot([r['epoch'] for r in history],[r[key] for r in history],label=label)
        axes.set(xlabel='Epoch',ylabel='MSE (remaining score / 1000)',title='Value Network learning curve');axes.legend();axes.grid(alpha=.25)
        for extension in ('png','svg'):
            image=io.BytesIO();figure.savefig(image,format=extension,dpi=130);atomic_bytes(output/('learning_curve.'+extension),image.getvalue())

def train(dataset,output,settings=None,resume=False,max_updates=None,max_seconds=None):
    output=Path(output).resolve();manifest,samples,fingerprint=load_dataset(dataset)
    payload=None;loaded=None
    if resume:
        payload,loaded=load_checkpoint(output/'checkpoints','latest');cfg=config_checked(dict(payload['config'],**(settings or {})))
        if payload.get('torch')!=str(torch.__version__) or payload.get('numpy')!=str(np.__version__):raise ValueError('Resume requires the saved torch/numpy versions')
        if any(cfg[k]!=payload['config'][k] for k in cfg if k!='epochs'):raise ValueError('Resume permits only epochs limit to change')
        if payload['dataset_fingerprint']!=fingerprint or payload['input_spec']!=INPUT_SPEC:raise ValueError('dataset/input changed: start a new training run')
    else:
        cfg=config_checked(settings or {});output.mkdir(parents=True,exist_ok=False)
    if max_updates is not None and max_updates<1:raise ValueError('max_updates must be positive')
    if max_seconds is not None and max_seconds<=0:raise ValueError('max_seconds must be positive')
    torch.set_num_threads(cfg['threads']);torch.use_deterministic_algorithms(True)
    random.seed(cfg['seed']);np.random.seed(cfg['seed']);torch.manual_seed(cfg['seed'])
    model=ValueNetwork(cfg['width'],cfg['head_width']).float()
    opt_class={'adamw':torch.optim.AdamW,'adam':torch.optim.Adam,'sgd':torch.optim.SGD}[cfg['optimizer']]
    optimizer=opt_class(model.parameters(),lr=cfg['lr'],weight_decay=cfg['weight_decay'])
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=cfg['scheduler_patience'],factor=cfg['scheduler_factor'])
    loss_function=torch.nn.MSELoss() if cfg['loss']=='mse' else torch.nn.HuberLoss(delta=cfg['huber_delta'])
    rows=encoded_rows(samples);training=[i for i,s in enumerate(samples) if s['split']=='train']
    targets=torch.tensor([s['target']/SCORE_SCALE for s in samples],dtype=torch.float32)
    epoch=updates=cursor=bad_epochs=0;order=[];history=[];best=float('inf');loss_sum=0.;epoch_samples=0
    if payload:
        model.load_state_dict(payload['model']);optimizer.load_state_dict(payload['optimizer']);scheduler.load_state_dict(payload['scheduler'])
        epoch=payload['epoch'];updates=payload['updates'];cursor=payload['cursor'];order=payload['order'];history=payload['history'];best=payload['best'];bad_epochs=payload['bad_epochs'];loss_sum=payload['epoch_loss_sum'];epoch_samples=payload['epoch_samples'];restore_rng(payload['rng'])
    atomic_json(output/'run.json',dict(config=cfg,dataset_fingerprint=fingerprint,input_spec=INPUT_SPEC,dataset=str(Path(dataset).resolve()),
        split=manifest['split_counts'],train_groups=manifest['train_groups'],validation_groups=manifest['validation_groups'],test_groups=manifest.get('test_groups',[]),
        episodes=manifest['episodes'],torch=str(torch.__version__),numpy=str(np.__version__),resume_from=str(loaded) if loaded else None))
    started=time.monotonic();last_save=started;stopped=[False]
    def stop_handler(signum,frame):stopped[0]=True # Finish the optimizer update before saving.
    previous_handler=signal.signal(signal.SIGINT,stop_handler)
    def save(is_best=False):
        nonlocal last_save
        value=dict(checkpoint_version=1,config=cfg,input_spec=INPUT_SPEC,dataset_fingerprint=fingerprint,
            split=dict(train_groups=manifest['train_groups'],validation_groups=manifest['validation_groups'],test_groups=manifest.get('test_groups',[])),
            model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch,updates=updates,
            cursor=cursor,order=order,history=history,best=best,bad_epochs=bad_epochs,epoch_loss_sum=loss_sum,epoch_samples=epoch_samples,
            rng=rng_state(),validation=history[-1] if history else None,torch=str(torch.__version__),numpy=str(np.__version__))
        path=save_checkpoint(output/'checkpoints',value,is_best);last_save=time.monotonic();return path
    try:
        if payload is None:save()
        while epoch<cfg['epochs'] and bad_epochs<cfg['early_stop_patience']:
            if not order:order=[training[i] for i in torch.randperm(len(training)).tolist()];cursor=0;loss_sum=0.;epoch_samples=0
            while cursor<len(order):
                indices=order[cursor:cursor+cfg['batch_size']];fruits,mask,globals=batch(rows,indices)
                # Learning both observed NEXT and explicitly unknown NEXT never reveals future draws.
                hide=torch.rand(len(indices))<cfg['next_mask_probability'];globals[hide,11:22]=0;globals[hide,23]=0
                model.train();optimizer.zero_grad(set_to_none=True);loss=loss_function(model(fruits,mask,globals),targets[indices])
                if not torch.isfinite(loss):raise FloatingPointError('nonfinite training loss')
                loss.backward();optimizer.step();cursor+=len(indices);updates+=1;loss_sum+=float(loss.detach())*len(indices);epoch_samples+=len(indices)
                if time.monotonic()-last_save>=cfg['save_seconds']:save()
                if stopped[0] or (max_updates is not None and updates>=max_updates) or (max_seconds is not None and time.monotonic()-started>=max_seconds):
                    stopped[0]=True;break
            if cursor==len(order):
                metrics,_=evaluate(model,samples,cfg['batch_size']);validation=metrics['splits']['validation']['model']['mse_scaled'];scheduler.step(validation)
                epoch+=1;improved=validation<best
                if improved:best=validation;bad_epochs=0
                else:bad_epochs+=1
                history.append(dict(epoch=epoch,updates=updates,training_loss=loss_sum/max(1,epoch_samples),train_mse=metrics['splits']['train']['model']['mse_scaled'],validation_mse=validation,baseline_validation_mse=metrics['splits']['validation']['baseline']['mse_scaled'],lr=optimizer.param_groups[0]['lr']))
                order=[];cursor=0;loss_sum=0.;epoch_samples=0;save(improved)
                print(json.dumps(history[-1]),flush=True)
            if stopped[0]:break
        latest=save()
        metrics,comparisons=evaluate(model,samples,cfg['batch_size']);metrics.update(epoch=epoch,updates=updates,stopped=stopped[0],latest=str(latest),dataset_fingerprint=fingerprint)
        write_reports(output,metrics,comparisons,history)
        return metrics
    finally:signal.signal(signal.SIGINT,previous_handler)

def load_model(output,which='best'):
    payload,path=load_checkpoint(Path(output)/'checkpoints',which)
    if payload['input_spec']!=INPUT_SPEC:raise ValueError('unsupported input schema')
    cfg=payload['config'];torch.set_num_threads(cfg['threads']);model=ValueNetwork(cfg['width'],cfg['head_width']).float();model.load_state_dict(payload['model']);model.eval()
    return model,payload,path

def benchmark(model,samples,repeats=100):
    selected=sorted(samples,key=lambda s:len(s['state']['fruits']),reverse=True)[:5]
    if not selected:raise ValueError('empty input')
    result={}
    for count in (1,5):
        items=[selected[i%len(selected)] for i in range(count)];inputs=batch(encoded_rows(items),range(count))
        for _ in range(10):
            with torch.inference_mode():model(*inputs)
        measured=[];total=[]
        for _ in range(repeats):
            begin=time.perf_counter_ns()
            with torch.inference_mode():model(*inputs)
            measured.append((time.perf_counter_ns()-begin)/1e6)
            begin=time.perf_counter_ns();predict(model,items);total.append((time.perf_counter_ns()-begin)/1e6)
        def summary(values):
            values=sorted(values);return dict(mean=statistics.mean(values),p50=statistics.median(values),p95=values[min(len(values)-1,int(.95*len(values)))])
        result[str(count)]=dict(fruit_counts=[len(s['state']['fruits']) for s in items],forward_ms=summary(measured),encoding_batch_forward_ms=summary(total))
    return result
