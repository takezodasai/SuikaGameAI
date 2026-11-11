"""CPU-one-thread offline imitation, Validation selection, atomic resume checkpoints."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,random,time
import numpy as np
import torch
from .policy_model import PolicyNetwork,losses,infer,CANDIDATE_SPEC
from .value_checkpoint import save_checkpoint,load_checkpoint,atomic_json
from .value_train import rng_state,restore_rng
from .value_data import INPUT_SPEC

DEFAULTS=dict(seed=20261028,epochs=20,patience=4,lr=.001,batch_size=128,width=64,threads=1,success_multiplier=1.)

def sampling_weights(boards,train_ids,multiplier=1.):
    """Only extraction probability changes; labels and quality loss weights do not."""
    if not np.isfinite(multiplier) or multiplier<=0:raise ValueError('Invalid success multiplier')
    records=boards.records;size=Counter(records[i]['episode'] for i in train_ids);ge=defaultdict(set)
    confirmed={e['id'] for e in boards.manifest.get('episodes',[]) if e.get('events',{}).get('labels',{}).get('watermelon_one',{}).get('achieved') is True}
    for i in train_ids:ge[records[i]['group']].add(records[i]['episode'])
    success=np.array([records[i].get('watermelon_success') is True or records[i]['episode'] in confirmed for i in train_ids])
    base=np.array([1/(size[records[i]['episode']]*len(ge[records[i]['group']])) for i in train_ids]);weights=base*np.where(success,multiplier,1.)
    return torch.tensor(weights,dtype=torch.float64),success,float(weights[success].sum()/weights.sum())

def group_average(records,ids,values):
    ep=defaultdict(list);groups={}
    for i,v in zip(ids,values):ep[records[i]['episode']].append(float(v));groups[records[i]['episode']]=records[i]['group']
    g=defaultdict(list)
    for k,v in ep.items():g[groups[k]].append(np.mean(v))
    return float(np.mean([np.mean(v) for v in g.values()]))

def train(boards,dataset,output,kind='deepsets',config=None,resume=False):
    cfg=dict(DEFAULTS,**(config or {}));out=Path(output)
    if out.exists() and not resume:raise FileExistsError(out)
    out.mkdir(parents=True,exist_ok=True);torch.set_num_threads(1);random.seed(cfg['seed']);np.random.seed(cfg['seed']);torch.manual_seed(cfg['seed'])
    model=PolicyNetwork(kind,cfg['width']).float();optimizer=torch.optim.AdamW(model.parameters(),lr=cfg['lr'],weight_decay=1e-4)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=2,factor=.5);generator=torch.Generator().manual_seed(cfg['seed']+1)
    r=boards.records;train_ids=np.array([i for i,x in enumerate(r) if x['split']=='train']);val_ids=[i for i,x in enumerate(r) if x['split']=='validation']
    if not len(train_ids) or not val_ids:raise ValueError('Missing Train/Validation')
    sampling,success_flags,expected_success=sampling_weights(boards,train_ids,cfg['success_multiplier'])
    fingerprint=hashlib.sha256((Path(dataset)/'manifest.json').read_bytes()).hexdigest();epoch=updates=bad=0;best=float('inf');history=[]
    if resume:
        payload,_=load_checkpoint(out/'checkpoints')
        previous_config=dict(DEFAULTS,**payload['config'])
        if payload['dataset_fingerprint']!=fingerprint or payload['kind']!=kind or {k:v for k,v in previous_config.items() if k!='epochs'}!={k:v for k,v in cfg.items() if k!='epochs'}:raise ValueError('Resume configuration/data mismatch')
        model.load_state_dict(payload['model']);optimizer.load_state_dict(payload['optimizer']);scheduler.load_state_dict(payload['scheduler']);epoch=payload['epoch'];updates=payload['updates'];best=payload['best'];bad=payload['bad'];history=payload['history'];restore_rng(payload['rng']);generator.set_state(payload['sampler_rng'])
    atomic_json(out/'run.json',dict(kind=kind,config=cfg,dataset=str(Path(dataset).resolve()),dataset_fingerprint=fingerprint,parameters=sum(p.numel() for p in model.parameters()),loss='quality-weighted (visit-distribution cross entropy + 0.25 selected-action cross entropy)',sampling='base uniform seed group -> episode -> state, multiplied only for confirmed successful games',expected_success_sampling_fraction=expected_success,input_spec=boards.manifest['input_spec'],candidate_spec=CANDIDATE_SPEC))
    def save(best_eligible=False):
        save_checkpoint(out/'checkpoints',dict(checkpoint_version=1,kind=kind,config=cfg,dataset_fingerprint=fingerprint,input_spec=boards.manifest['input_spec'],candidate_spec=CANDIDATE_SPEC,model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch,updates=updates,best=best,bad=bad,history=history,rng=rng_state(),sampler_rng=generator.get_state(),split={k:boards.manifest[k] for k in ('split_seed','split_groups','split_games')}),best_eligible)
    began=time.monotonic()
    if not resume:save()
    while epoch<cfg['epochs'] and bad<cfg['patience']:
        positions=torch.multinomial(sampling,len(train_ids),replacement=True,generator=generator).numpy();order=train_ids[positions];model.train();cost=[]
        for begin in range(0,len(order),cfg['batch_size']):
            ids=order[begin:begin+cfg['batch_size']].tolist();inputs,target,selected,weights=boards.batch(ids);loss=(losses(model(*inputs),target,selected)*weights).sum()/weights.sum()
            if not torch.isfinite(loss):raise FloatingPointError('Nonfinite policy loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();updates+=1;cost.append(float(loss.detach()))
        epoch+=1;probs=infer(model,boards,val_ids);values=[]
        for i,p in zip(val_ids,probs):
            log=np.log(np.maximum(p,1e-12));v=np.array(r[i]['visits']);values.append(-float(v@log/v.sum())-.25*float(log[r[i]['selected_index']]))
        val=group_average(r,val_ids,values);scheduler.step(val);improved=val<best
        if improved:best=val;bad=0
        else:bad+=1
        row=dict(epoch=epoch,updates=updates,training_loss=float(np.mean(cost)),validation_group_loss=val,lr=optimizer.param_groups[0]['lr'],sampled_success_states=int(success_flags[positions].sum()),sampled_success_fraction=float(success_flags[positions].mean()));history.append(row);save(improved);atomic_json(out/'history.json',history)
        print(json.dumps(dict(kind=kind,**row)),flush=True)
    save();atomic_json(out/'timing.json',dict(training_seconds=time.monotonic()-began,epochs=epoch,updates=updates));return model,history

def load_model(output,which='best'):
    payload,path=load_checkpoint(Path(output)/'checkpoints',which)
    if payload.get('candidate_spec')!=CANDIDATE_SPEC or payload.get('input_spec')!=INPUT_SPEC:raise ValueError('Policy input schema mismatch')
    model=PolicyNetwork(payload['kind'],payload['config']['width']);model.load_state_dict(payload['model']);model.eval();return model,payload,path
