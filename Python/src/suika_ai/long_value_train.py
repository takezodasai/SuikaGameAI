"""Offline AC training. Validation-only checkpoint selection; no gameplay imports."""
import json,math,random,time,hashlib
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import torch
from .long_value_data import load
from .value_data import INPUT_SPEC
from .long_value_model import PackedBoards,GeometryValueNetwork,FEATURE_SPEC,forward,infer
from .value_model import ValueNetwork
from .value_checkpoint import save_checkpoint,load_checkpoint,atomic_json
from .value_train import rng_state,restore_rng

DEFAULTS=dict(seed=20261027,epochs=30,patience=6,lr=.001,batch_size=128,width=64,head_width=128,rank_weight=.05,rank_margin_points=100,score_match_points=100,threads=1)

def macro_mse(records,ids,errors):
    episodes=defaultdict(list);groups={}
    for i,e in zip(ids,errors):episodes[records[i]['episode']].append(float(e*e));groups[records[i]['episode']]=records[i]['group']
    grouped=defaultdict(list)
    for ep,values in episodes.items():grouped[groups[ep]].append(np.mean(values))
    return float(np.mean([np.mean(v) for v in grouped.values()]))

def rank_loss(prediction,targets,score,groups,margin=.1,match=.1):
    eligible=(groups[:,None]!=groups[None,:])&((score[:,None]-score[None,:]).abs()<=match)&((targets[:,None]-targets[None,:]).abs()>=margin)
    eligible=torch.triu(eligible,diagonal=1)
    difference=prediction[:,None]-prediction[None,:]
    if not eligible.any():return prediction.sum()*0,0
    sign=torch.sign(targets[:,None]-targets[None,:])
    return torch.nn.functional.softplus(-sign[eligible]*difference[eligible]/.25).mean(),int(eligible.sum())

def train(boards,dataset_path,output,kind,config=None,resume=False):
    out=Path(output);cfg=dict(DEFAULTS,**(config or {}))
    if kind not in ('v1','geometry'):raise ValueError('Unsupported model')
    fingerprint=hashlib.sha256((Path(dataset_path)/'manifest.json').read_bytes()).hexdigest()
    if not resume:out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(cfg['threads']);torch.use_deterministic_algorithms(True);random.seed(cfg['seed']);np.random.seed(cfg['seed']);torch.manual_seed(cfg['seed'])
    model=(ValueNetwork if kind=='v1' else GeometryValueNetwork)(cfg['width'],cfg['head_width']).float()
    optimizer=torch.optim.AdamW(model.parameters(),lr=cfg['lr'],weight_decay=.0001)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=3,factor=.5)
    torch.manual_seed(cfg['seed']+2);generator=torch.Generator().manual_seed(cfg['seed']+1)
    records=boards.records;train_ids=np.array([i for i,r in enumerate(records) if r['split']=='train']);val_ids=[i for i,r in enumerate(records) if r['split']=='validation']
    ep_size=Counter(r['episode'] for r in records if r['split']=='train');group_eps=defaultdict(set)
    for i in train_ids:group_eps[records[i]['group']].add(records[i]['episode'])
    weights=torch.tensor([1/(ep_size[records[i]['episode']]*len(group_eps[records[i]['group']])) for i in train_ids],dtype=torch.float64)
    targets=torch.tensor(boards.targets);epoch=0;updates=0;best=float('inf');bad=0;history=[]
    if resume:
        payload,_=load_checkpoint(out/'checkpoints','latest')
        if payload['dataset_fingerprint']!=fingerprint or {k:v for k,v in payload['config'].items() if k!='epochs'}!={k:v for k,v in cfg.items() if k!='epochs'} or payload['kind']!=kind or cfg['epochs']<payload['epoch']:raise ValueError('Resume configuration/data mismatch')
        model.load_state_dict(payload['model']);optimizer.load_state_dict(payload['optimizer']);scheduler.load_state_dict(payload['scheduler']);epoch=payload['epoch'];updates=payload['updates'];best=payload['best'];bad=payload['bad'];history=payload['history'];restore_rng(payload['rng']);generator.set_state(payload['sampler_rng'])
    atomic_json(out/'run.json',dict(kind=kind,config=cfg,input_spec=dict(base=boards.manifest['input_spec'],geometry=FEATURE_SPEC if kind=='geometry' else None),dataset=str(Path(dataset_path).resolve()),dataset_fingerprint=fingerprint,parameters=sum(p.numel() for p in model.parameters()),sampling='uniform seed group -> episode -> state, with replacement',checkpoint_epoch_boundary=True))
    def save(is_best=False):
        return save_checkpoint(out/'checkpoints',dict(checkpoint_version=1,kind=kind,config=cfg,input_spec=dict(base=boards.manifest['input_spec'],geometry=FEATURE_SPEC if kind=='geometry' else None),dataset_fingerprint=fingerprint,model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch,updates=updates,best=best,bad=bad,history=history,rng=rng_state(),sampler_rng=generator.get_state(),split={k:boards.manifest[k] for k in ('split_seed','split_groups','split_games')}),is_best)
    start=time.monotonic()
    if not resume:save()
    while epoch<cfg['epochs'] and bad<cfg['patience']:
        order=train_ids[torch.multinomial(weights,len(train_ids),replacement=True,generator=generator).numpy()]
        sums=[];ranks=[];pairs=0;model.train()
        for start_i in range(0,len(order),cfg['batch_size']):
            ids=order[start_i:start_i+cfg['batch_size']];inputs=boards.batch(ids,hide_next=True);target=targets[ids]
            pred=forward(model,kind,inputs);mse=torch.nn.functional.mse_loss(pred,target)
            ranking,pair_count=rank_loss(pred,target,inputs[2][:,27],boards.group_ids[ids],cfg['rank_margin_points']/1000,cfg['score_match_points']/1000) if kind=='geometry' else (pred.sum()*0,0)
            loss=mse+(cfg['rank_weight']*ranking if kind=='geometry' else 0)
            if not torch.isfinite(loss):raise FloatingPointError('Nonfinite loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();updates+=1;sums.append(float(mse.detach()));ranks.append(float(ranking.detach()));pairs+=pair_count
        epoch+=1
        prediction=infer(model,kind,boards,val_ids);error=prediction/1000-boards.targets[val_ids];val=macro_mse(records,val_ids,error)
        scheduler.step(val);improved=val<best
        if improved:best=val;bad=0
        else:bad+=1
        row=dict(epoch=epoch,updates=updates,training_mse=float(np.mean(sums)),ranking_loss=float(np.mean(ranks)),ranking_pairs=pairs,validation_group_mse=val,validation_group_rmse_points=math.sqrt(val)*1000,lr=optimizer.param_groups[0]['lr'])
        history.append(row);save(improved);atomic_json(out/'history.json',history);print(json.dumps(dict(kind=kind,**row)),flush=True)
    save();atomic_json(out/'timing.json',dict(training_seconds=time.monotonic()-start,epochs=epoch,updates=updates))
    return model,history

def load_trained(output,which='best'):
    payload,path=load_checkpoint(Path(output)/'checkpoints',which);cfg=payload['config'];kind=payload['kind']
    if kind not in ('v1','geometry') or payload['input_spec']!=dict(base=INPUT_SPEC,geometry=FEATURE_SPEC if kind=='geometry' else None):raise ValueError('Unsupported checkpoint input specification')
    model=(ValueNetwork if kind=='v1' else GeometryValueNetwork)(cfg['width'],cfg['head_width']);model.load_state_dict(payload['model']);model.eval();return model,kind,payload,path
