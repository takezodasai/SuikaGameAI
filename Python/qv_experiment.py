"""Frozen selected-action MC Q/V experiment. Never launches collection or edits old data."""
import argparse,json,time,hashlib,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import torch
from torch import nn
from suika_ai.long_value_data import load
from suika_ai.long_value_model import PackedBoards,GeometryValueNetwork,geometry_features,infer
from suika_ai.long_value_train import macro_mse,load_trained
from suika_ai.value_checkpoint import load_checkpoint

ROOT=Path('Python/outputs/qv_compare_01')
VALUE=Path('Python/outputs/value_reliability_01/dataset')
POLICY=Path('Python/outputs/policy_success_01/dataset')

def write(p,obj):
    with Path(p).open('x',encoding='utf8') as f:json.dump(obj,f,indent=2)

def prepare():
    ROOT.mkdir(exist_ok=False)
    vm=json.loads((VALUE/'manifest.json').read_text());pm=json.loads((POLICY/'manifest.json').read_text())
    eps={e['id']:e for e in vm['episodes'] if e['split'] in ['train','validation']}
    protected={e['id'] for e in pm['episodes'] if e['split']=='test'}
    if set(eps)&protected:raise ValueError('Historical policy Test overlap')
    selected=[];groups=set()
    for e in sorted(eps.values(),key=lambda e:(e['group'],e['seed'],e['id'])):
        if e['split']=='validation' and e['group'] not in groups and e['id'] in {x['id'] for x in pm['episodes']}:
            selected.append(e);groups.add(e['group'])
            if len(selected)==2:break
    plan=dict(seeds=[20261101,20261102,20261103],epochs=12,patience=3,batch_size=128,lr=.001,weight_decay=.0001,threads=1,
        sampling='uniform group -> episode -> matched selected action, replacement; common sampler for Q/V',
        loss='MC MSE points/1000; no ranking loss; no TD',selection='Validation group/episode macro MC MSE only',
        scheduler='StepLR(8,.5)',next_dropout=.5,test='No Test evaluation or selection',
        branch_budget_seconds=900,branch_process_cap_seconds=180,branch_roots=selected,candidate_x=[0.,.37],
        future_seeds=[20261111,20261112],branch_policy='fresh actual heuristic5/25tick',
        branch_use='Frozen models evaluated once; no fitting or threshold tuning on branches',
        fingerprints={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [VALUE/'manifest.json',POLICY/'manifest.json']})
    write(ROOT/'plan.json',plan)

def data():
    post=PackedBoards(load(VALUE));idx={(r['episode'],r['action_id']):i for i,r in enumerate(post.records) if r['split'] in ['train','validation']}
    pmeta=json.loads((POLICY/'manifest.json').read_text());ep={e['id']:e for e in pmeta['episodes']}
    with np.load(POLICY/'features.npz') as archive:z={k:archive[k] for k in archive.files}
    prefr=[];preg=[];records=[];postids=[];actions=[];off=[0];rejected=Counter()
    audit_path=ROOT/'terminal_drop_audit.json';drop_audit=json.loads(audit_path.read_text()) if audit_path.exists() else None
    with (POLICY/'records.jsonl').open() as f:
        for j,l in enumerate(f):
            r=json.loads(l);i=idx.get((r['episode'],r['action_id']))
            if i is None:rejected['not in frozen Train/Validation pair']+=1;continue
            if r['episode'] not in ep or ep[r['episode']]['split']=='test':raise ValueError('Protected Test used')
            v=post.records[i];x=float(r['selected_x']);reward=v['score']-r['score']
            if drop_audit is not None and v['game_over'] and drop_audit['confirmed'].get(r['episode']+'#'+str(r['action_id'])) is not True:
                rejected['terminal drop not observed successful']+=1;continue
            if not 0<=x<=1 or reward<0 or abs(r['future_points']-r['post_future_points']-reward)>1e-5 or abs(post.targets[i]*1000-r['post_future_points'])>.001:raise ValueError('Action/return conservation mismatch')
            vals=z['fruits'][z['offsets'][j]:z['offsets'][j+1]];prefr.append(vals);off.append(off[-1]+len(vals));preg.append(z['globals'][j]);postids.append(i);actions.append(x)
            records.append(dict(v,target=r['future_points'],post_target=r['post_future_points'],immediate=reward,selected_x=x,post_game_over=v['game_over'],before_game_over=False,
                score=r['score'],fruit_count=r['fruit_count'],actual_iterations=r['actual_iterations'],requested_iterations=r['requested_iterations'],depth=r['depth'],
                stop_reason=r['stop_reason'],watermelon_success=r['watermelon_success'],watermelon_known=r['watermelon_success_known']))
    extra=ROOT.parent/'latest'
    if ROOT.name=='latest_models':
        er=json.loads((extra/'records.json').read_text());z=np.load(extra/'features.npz');base=len(post.records)
        if (extra/'observed_action_index.json').exists():
            for item in json.loads((extra/'observed_action_index.json').read_text()):er[item['record']]['action_id']=item['action_id']
        combined_post_records=post.records+[dict(r,target=r['post_target'],score=r['score']+r['immediate']) for r in er]
        post=PackedBoards((post.manifest,combined_post_records,np.r_[post.offsets,post.offsets[-1]+z['post_offsets'][1:]],np.concatenate([post.globals,z['post_globals']]),np.r_[post.targets,np.asarray([r['post_target']/1000 for r in er],dtype='float32')],np.concatenate([post.fruits,z['post_fruits']])))
        postids.extend(range(base,base+len(er)));actions.extend(r['selected_x'] for r in er);off.extend((off[-1]+z['pre_offsets'][1:]).tolist());preg.extend(z['pre_globals']);prefr.append(z['pre_fruits']);records.extend(er)
    pre=PackedBoards((post.manifest,records,np.asarray(off),np.asarray(preg),np.asarray([r['target']/1000 for r in records],dtype='float32'),np.concatenate(prefr)))
    return pre,post,np.asarray(postids),np.asarray(actions,dtype='float32'),records

class ActionValue(GeometryValueNetwork):
    def __init__(self):
        super().__init__();self.head=nn.Sequential(nn.Linear(225,128),nn.ReLU(),nn.Linear(128,64),nn.ReLU(),nn.Linear(64,1),nn.Softplus())
    def forward(self,f,m,g,geo,x):
        z=self.phi(f);n=m.sum(1,keepdim=True);mean=(z*m.unsqueeze(-1)).sum(1)/n.clamp_min(1)
        mx=z.masked_fill(~m.unsqueeze(-1),-torch.inf).max(1).values;mx=torch.where(n>0,mx,torch.zeros_like(mx))
        a=torch.stack([x,x*x,x-g[:,24]],1)
        return self.head(torch.cat([mean,mx,g,geo,a],1)).squeeze(-1)*(1-g[:,35])

def predict(model,kind,pre,post,pi,x,ids,marginal=False):
    result=[];model.eval()
    with torch.inference_mode():
        for a in range(0,len(ids),128):
            at=np.asarray(ids[a:a+128]);inputs=pre.batch(at) if kind=='Q' else post.batch(pi[at])
            if kind=='Q':p=model(*inputs,torch.tensor(x[at]))
            elif marginal:
                values=[]
                for t in range(5):
                    gg=inputs[2].clone();gg[:,11:22]=0;gg[:,11+t]=1;gg[:,23]=1
                    values.append(model(inputs[0],inputs[1],gg,inputs[3]))
                p=torch.stack(values).mean(0)
            else:p=model(*inputs)
            result.extend((p*1000).tolist())
    return np.asarray(result)

def metrics(rs,ids,pred,truth):
    err=pred-truth
    def subset(at):
        if not at:return dict(states=0,groups=0)
        e=err[at];return dict(states=len(at),games=len({rs[ids[j]]['episode'] for j in at}),groups=len({rs[ids[j]]['group'] for j in at}),mae=float(abs(e).mean()),rmse=float(np.sqrt((e*e).mean())),bias=float(e.mean()),overprediction=float(np.maximum(e,0).mean()))
    out=dict(all=subset(list(range(len(ids)))))
    for key,test in [('near_go',lambda r:r['near_go']),('high_score',lambda r:r['score']>=2000),('large_return',lambda r:r['target']>=1000),('wm_pre',lambda r:r['wm_window']=='pre_observed'),('wm_post',lambda r:r['wm_window']=='post_observed'),('off_grid5',lambda r:min(abs(r['selected_x']-a) for a in [0,.25,.5,.75,1])>1e-5)]:
        out[key]=subset([j for j,i in enumerate(ids) if test(rs[i])])
    groups=defaultdict(list)
    for i,e in zip(ids,err):groups[rs[i]['group']].append(float(e))
    out['per_group']={g:dict(states=len(e),mae=float(np.mean(abs(np.asarray(e)))),bias=float(np.mean(e))) for g,e in groups.items()}
    return out

def audit(pre,post,pi,x,rs):
    out={}
    for split in ['train','validation']:
        ids=[i for i,r in enumerate(rs) if r['split']==split];r=[rs[i] for i in ids]
        out[split]=dict(games=len({a['episode'] for a in r}),groups=len({a['group'] for a in r}),states=len(r),
            actions=dict(Counter(str(round(float(x[i]),6)) for i in ids)),scores=dict(Counter('0-499' if a['score']<500 else '500-999' if a['score']<1000 else '1000-1999' if a['score']<2000 else '2000-2999' if a['score']<3000 else '3000+' for a in r)),
            profiles=dict(Counter(str((a['requested_iterations'],a['depth'])) for a in r)),wm_windows=dict(Counter(a['wm_window'] for a in r)),
            successful_watermelon_games=len({a['episode'] for a in r if a['watermelon_known'] and a['watermelon_success']}),
            x037_exact=sum(abs(float(x[i])-.37)<1e-5 for i in ids),grid5=sum(min(abs(float(x[i])-a) for a in [0,.25,.5,.75,1])<1e-5 for i in ids))
    write(ROOT/'data_audit.json',out)
    write(ROOT/'matched_records.json',rs)
    return out

def train_all():
    plan=json.loads((ROOT/'plan.json').read_text());torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    pre,post,pi,x,rs=data();audit(pre,post,pi,x,rs);ids=np.array([i for i,r in enumerate(rs) if r['split']=='train']);val=[i for i,r in enumerate(rs) if r['split']=='validation']
    sizes=Counter(rs[i]['episode'] for i in ids);ge=defaultdict(set)
    for i in ids:ge[rs[i]['group']].add(rs[i]['episode'])
    weights=torch.tensor([1/(sizes[rs[i]['episode']]*len(ge[rs[i]['group']])) for i in ids],dtype=torch.float64);summary=[]
    for seed in plan['seeds']:
        for kind in ['V','Q']:
            out=ROOT/f'{kind}_{seed}';out.mkdir();torch.manual_seed(seed);model=ActionValue() if kind=='Q' else GeometryValueNetwork()
            opt=torch.optim.AdamW(model.parameters(),lr=plan['lr'],weight_decay=plan['weight_decay']);sched=torch.optim.lr_scheduler.StepLR(opt,8,.5);sampler=torch.Generator().manual_seed(seed+1);torch.manual_seed(seed+2)
            target=np.array([r['target'] if kind=='Q' else r['post_target'] for r in rs],dtype='float32')/1000;best=float('inf');bad=0;history=[];start=time.monotonic()
            for epoch in range(1,plan['epochs']+1):
                model.train();order=ids[torch.multinomial(weights,len(ids),replacement=True,generator=sampler).numpy()]
                for a in range(0,len(order),plan['batch_size']):
                    at=order[a:a+plan['batch_size']];inputs=pre.batch(at) if kind=='Q' else post.batch(pi[at]);g=inputs[2];hidden=torch.rand(len(at))<plan['next_dropout'];g[hidden,11:22]=0;g[hidden,23]=0
                    pred=model(*inputs,torch.tensor(x[at])) if kind=='Q' else model(*inputs);loss=(pred-torch.tensor(target[at])).square().mean()
                    if not torch.isfinite(loss):raise FloatingPointError('Nonfinite loss')
                    opt.zero_grad(set_to_none=True);loss.backward();opt.step()
                p=predict(model,kind,pre,post,pi,x,val);criterion=macro_mse(rs,val,p/1000-target[val]);sched.step();history.append(dict(epoch=epoch,validation_macro_mse=criterion))
                if criterion<best:
                    best=criterion;bad=0;torch.save(dict(model=model.state_dict(),kind=kind,seed=seed,epoch=epoch,criterion=criterion,parameters=sum(v.numel() for v in model.parameters())),out/'best.pt')
                else:bad+=1
                print(kind,seed,epoch,round(criterion,5),flush=True)
                if bad>=plan['patience']:break
            payload=torch.load(out/'best.pt',weights_only=True);model.load_state_dict(payload['model']);result=dict(kind=kind,seed=seed,epoch=payload['epoch'],parameters=payload['parameters'],seconds=time.monotonic()-start,metrics={})
            for split,at in [('train',ids.tolist()),('validation',val)]:
                p=predict(model,kind,pre,post,pi,x,at);p=p+(np.array([rs[i]['immediate'] for i in at]) if kind=='V' else 0);truth=np.array([rs[i]['target'] for i in at]);result['metrics'][split]=metrics(rs,at,p,truth)
                np.save(out/f'{split}_selected_return_predictions.npy',p)
                if split=='validation' and kind=='V':
                    q=predict(model,kind,pre,post,pi,x,at,True)+np.array([rs[i]['immediate'] for i in at]);result['metrics']['validation_C_marginalized']=metrics(rs,at,q,truth)
            write(out/'result.json',result);write(out/'history.json',history);summary.append(result)
    # Frozen AC evaluated once as a baseline, not adjusted on this Validation.
    old,k,_,path=load_trained(Path('Python/outputs/step8ac_01/geometry'));truth=np.array([rs[i]['target'] for i in val]);immediate=np.array([rs[i]['immediate'] for i in val]);p=predict(old,'V',pre,post,pi,x,val)+immediate
    baselines=dict(frozen_AC=dict(checkpoint=str(path),metrics=metrics(rs,val,p,truth)),frozen_AC_C_marginalized=metrics(rs,val,predict(old,'V',pre,post,pi,x,val,True)+immediate,truth))
    # Stronger simple reference: train-only standardized ridge on public pre-state globals/geometry/action.
    a=np.column_stack([pre.globals,pre.geometry,x,x*x]);mean=a[ids].mean(0);sd=a[ids].std(0);sd[sd<1e-6]=1;design=np.column_stack([np.ones(len(a)),(a-mean)/sd]);y=np.array([r['target'] for r in rs]);coef=np.linalg.solve(design[ids].T@design[ids]+10*np.eye(design.shape[1]),design[ids].T@y[ids]);ridge=design[val]@coef
    baselines['ridge_Q']=metrics(rs,val,ridge,truth);baselines['constant']=metrics(rs,val,np.full(len(val),y[ids].mean()),truth)
    np.savez(ROOT/'ridge.npz',mean=mean,sd=sd,coef=coef)
    write(ROOT/'summary.json',dict(trials=summary,baselines=baselines,limitation='Selected-action validation, not evidence on unobserved coordinates. V observed afterstate has information unavailable at root; C marginalized variant still uses the actual afterstate, not a predicted Scene.'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','train']);p.add_argument('--verified',action='store_true');p.add_argument('--latest',action='store_true');a=p.parse_args()
    if a.verified or a.latest:
        parent=ROOT;ROOT=ROOT/('latest_models' if a.latest else 'verified');ROOT.mkdir(exist_ok=False)
        write(ROOT/'plan.json',dict(json.loads((parent/'plan.json').read_text()),audit_correction='Exclude one completed plan without an actual drop; original trials preserved, same hyperparameters'))
        write(ROOT/'terminal_drop_audit.json',json.loads((parent/'terminal_drop_audit.json').read_text()))
    prepare() if a.command=='prepare' else train_all()
