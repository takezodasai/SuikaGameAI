"""Bounded A/B/C value experiments. Historical tests and MCTS are untouched."""
import argparse,hashlib,json,math,time
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import torch
from torch import nn
from suika_ai.long_value_data import load
from suika_ai.long_value_model import GeometryValueNetwork,PackedBoards,FEATURE_SPEC,infer
from suika_ai.long_value_train import rank_loss,macro_mse,load_trained
from suika_ai.value_data import INPUT_SPEC
from suika_ai.value_checkpoint import save_checkpoint,load_checkpoint,atomic_json
from suika_ai.value_train import rng_state


class RiskValueNetwork(GeometryValueNetwork):
    def __init__(self):
        super().__init__();self.risk_head=nn.Linear(222,1)
    def forward(self,fruits,mask,globals_,geometry):
        z=self.phi(fruits);count=mask.sum(1,keepdim=True)
        mean=(z*mask.unsqueeze(-1)).sum(1)/count.clamp_min(1)
        mx=z.masked_fill(~mask.unsqueeze(-1),-torch.inf).max(1).values;mx=torch.where(count>0,mx,torch.zeros_like(mx))
        context=torch.cat([mean,mx,globals_,geometry],1)
        return self.head(context).squeeze(-1)*(1-globals_[:,35]),self.risk_head(context).squeeze(-1)


def evaluate(model,boards,ids,risk_weight=1):
    score=[];risks=[];model.eval()
    with torch.inference_mode():
        for start in range(0,len(ids),128):
            result=model(*boards.batch(ids[start:start+128]))
            if isinstance(result,tuple):
                value,logits=result;risks.extend(torch.sigmoid(logits-math.log(risk_weight)).tolist())
            else:value=result
            score.extend((value*1000).tolist())
    return np.asarray(score),np.asarray(risks)


def metrics(records,ids,prediction,risk=None):
    truth=np.array([records[i]['target'] for i in ids]);errors=prediction-truth
    groups=defaultdict(list)
    for i,e in zip(ids,errors):groups[records[i]['group']].append(e)
    def subset(name,condition):
        at=[j for j,i in enumerate(ids) if condition(records[i])]
        if not at:return dict(states=0,groups=0)
        es=errors[at];return dict(states=len(at),groups=len({records[ids[j]]['group'] for j in at}),mae=float(np.mean(abs(es))),rmse=float(np.sqrt(np.mean(es**2))),bias=float(np.mean(es)),mean_overprediction=float(np.mean(np.maximum(es,0))))
    out=dict(all=subset('all',lambda r:not r['game_over']),near_go=subset('near',lambda r:r['near_go']),
        wm_pre=subset('pre',lambda r:r['wm_window']=='pre_observed'),wm_post=subset('post',lambda r:r['wm_window']=='post_observed'),
        group_macro_mae=float(np.mean([np.mean(abs(np.asarray(e))) for e in groups.values()])))
    if risk is not None and len(risk):
        keep=[j for j,i in enumerate(ids) if not records[i]['game_over']];y=np.asarray([records[ids[j]]['risk3'] for j in keep],dtype=float);p=risk[keep]
        pos=np.flatnonzero(y==1);neg=np.flatnonzero(y==0)
        auc=float(np.mean([(np.sum(p[k]>p[neg])+.5*np.sum(p[k]==p[neg]))/len(neg) for k in pos])) if len(pos) and len(neg) else None
        out['risk3']=dict(states=len(y),positive=int(y.sum()),brier=float(np.mean((p-y)**2)),roc_auc=auc,mean_probability=float(p.mean()))
    return out


def train(root,variant):
    root=Path(root);data=load(root/'dataset');boards=PackedBoards(data);records=boards.records;out=root/variant;out.mkdir(exist_ok=False)
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True);torch.manual_seed(20261029)
    model=RiskValueNetwork() if variant=='C' else GeometryValueNetwork()
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    ids=np.array([i for i,r in enumerate(records) if r['split']=='train']);val=[i for i,r in enumerate(records) if r['split']=='validation']
    ep_size=Counter(records[i]['episode'] for i in ids);group_eps=defaultdict(set)
    for i in ids:group_eps[records[i]['group']].add(records[i]['episode'])
    weights=torch.tensor([1/(ep_size[records[i]['episode']]*len(group_eps[records[i]['group']])) for i in ids],dtype=torch.float64)
    generator=torch.Generator().manual_seed(20261030);torch.manual_seed(20261031)
    target=torch.tensor(boards.targets);labels=torch.tensor([float(r['risk3']) for r in records]);near=torch.tensor([r['near_go'] for r in records])
    positive=float(labels[ids].mean());risk_weight=min(20,(1-positive)/positive)
    best=float('inf');bad=0;updates=0;history=[];start=time.monotonic();fingerprint=hashlib.sha256((root/'dataset/manifest.json').read_bytes()).hexdigest()
    atomic_json(out/'run.json',dict(variant=variant,parameters=sum(p.numel() for p in model.parameters()),risk_weight=risk_weight,config=json.loads((root/'evaluation_plan.json').read_text()),dataset_fingerprint=fingerprint))
    for epoch in range(1,11):
        model.train();order=ids[torch.multinomial(weights,len(ids),replacement=True,generator=generator).numpy()]
        for at in range(0,len(order),128):
            batch=order[at:at+128];inputs=boards.batch(batch,hide_next=True);result=model(*inputs)
            if variant=='C':prediction,logits=result
            else:prediction=result
            mse=(prediction-target[batch]).square()
            if variant=='B':w=1+3*near[batch].float();loss=(mse*w).sum()/w.sum()
            else:loss=mse.mean()
            ranking,_=rank_loss(prediction,target[batch],inputs[2][:,27],boards.group_ids[batch],.1,.1);loss=loss+.05*ranking
            if variant=='C':loss=loss+.1*nn.functional.binary_cross_entropy_with_logits(logits,labels[batch],pos_weight=torch.tensor(risk_weight))
            if not torch.isfinite(loss):raise FloatingPointError('Nonfinite loss')
            opt.zero_grad(set_to_none=True);loss.backward();opt.step();updates+=1
        pred,risk=evaluate(model,boards,val,risk_weight);criterion=macro_mse(records,val,pred/1000-boards.targets[val]);improved=criterion<best
        if improved:best=criterion;bad=0
        else:bad+=1
        history.append(dict(epoch=epoch,validation_group_mse=criterion,validation=metrics(records,val,pred,risk)))
        save_checkpoint(out/'checkpoints',dict(checkpoint_version=1,epoch=epoch,updates=updates,kind='safety' if variant=='C' else 'geometry',variant=variant,model=model.state_dict(),optimizer=opt.state_dict(),rng=rng_state(),sampler_rng=generator.get_state(),risk_weight=risk_weight,input_spec=dict(base=INPUT_SPEC,geometry=FEATURE_SPEC),dataset_fingerprint=fingerprint,split=boards.manifest['split_groups'],history=history),improved)
        atomic_json(out/'history.json',history);print(variant,epoch,round(criterion,6),flush=True)
        if bad>=3:break
    atomic_json(out/'timing.json',dict(seconds=time.monotonic()-start,epochs=epoch))


def assess(root,test=False):
    root=Path(root);destination=root/('test_evaluation.json' if test else 'validation_evaluation.json')
    if destination.exists():raise FileExistsError(destination)
    torch.set_num_threads(1);boards=PackedBoards(load(root/'dataset'));records=boards.records
    split='test' if test else 'validation';ids=[i for i,r in enumerate(records) if r['split']==split];models={};output={}
    if test and not (root/'selection.json').exists():raise ValueError('Freeze Validation selection first')
    frozen=json.loads((root/'selection.json').read_text())['frozen_models'] if test else None
    for variant in ['A','B','C']:
        payload,path=load_checkpoint(root/variant/'checkpoints','best');model=RiskValueNetwork() if variant=='C' else GeometryValueNetwork();model.load_state_dict(payload['model']);models[variant]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),epoch=payload['epoch'])
        if payload['dataset_fingerprint']!=hashlib.sha256((root/'dataset/manifest.json').read_bytes()).hexdigest():raise ValueError('Dataset changed')
        if test and frozen[variant]!=models[variant]:raise ValueError('Model changed after Validation selection')
        pred,risk=evaluate(model,boards,ids,payload['risk_weight']);output[variant]=metrics(records,ids,pred,risk)
        if not test:
            tr=[i for i,r in enumerate(records) if r['split']=='train'];tp,rr=evaluate(model,boards,tr,payload['risk_weight']);output[variant]['train']=metrics(records,tr,tp,rr)
        with (root/f'{variant}_{split}_predictions.jsonl').open('x',encoding='utf8') as f:
            for j,i in enumerate(ids):f.write(json.dumps(dict(index=i,**records[i],prediction=float(pred[j]),risk3_probability=float(risk[j]) if len(risk) else None))+'\n')
    old,kind,_,_=load_trained(Path('Python/outputs/step8ac_01/geometry'));pred=infer(old,kind,boards,ids);output['frozen_AC']=metrics(records,ids,pred)
    train=[i for i,r in enumerate(records) if r['split']=='train'];x=np.array([[1,records[i]['score']/1000,records[i]['fruit_count']/64] for i in train]);y=boards.targets[train]*1000
    coef=np.linalg.solve(x.T@x+.01*np.eye(3),x.T@y);tx=np.array([[1,records[i]['score']/1000,records[i]['fruit_count']/64] for i in ids]);output['ridge_score_count']=metrics(records,ids,tx@coef)
    atomic_json(destination,dict(split=split,states=len(ids),groups=len({records[i]['group'] for i in ids}),models=models,metrics=output))
    if not test:
        chosen=min(['A','B','C'],key=lambda v:load_checkpoint(root/v/'checkpoints','best')[0]['history'][models[v]['epoch']-1]['validation_group_mse'])
        atomic_json(root/'selection.json',dict(chosen=chosen,criterion='validation group macro MSE',frozen_models=models))
    else:
        frozen=json.loads((root/'selection.json').read_text())['frozen_models']
        if frozen!=models:raise ValueError('Models changed after selection')
    print(json.dumps(dict(split=split,metrics=output),indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['train','validation','test']);p.add_argument('--root',type=Path,required=True);p.add_argument('--variant',choices=['A','B','C']);a=p.parse_args()
    if a.command=='train':train(a.root,a.variant)
    else:assess(a.root,a.command=='test')
