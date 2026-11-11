"""Predeclared, paired-seed MC/TD experiment. No Unity, no Test inference."""
import argparse,copy,hashlib,json,math,time
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
import torch
from suika_ai.long_value_data import load
from suika_ai.long_value_model import PackedBoards,GeometryValueNetwork,infer,FEATURE_SPEC
from suika_ai.value_data import INPUT_SPEC
from suika_ai.value_checkpoint import save_checkpoint,load_checkpoint,atomic_json
from mc_td_data import prepare,load_restricted

CONFIG=dict(seeds=[20261030,20261031,20261032],td_weights=dict(MC=0.,TD=1.,mix25=.25,mix50=.5),gamma=1.,n=3,epochs=15,patience=4,batch_size=128,lr=.001,weight_decay=.0001,scheduler='StepLR(step_size=8,gamma=.5); identical epoch schedule',threads=1,normalization='points/1000; unchanged AC input features',rank_auxiliary=0.,next_mask_probability=.5,target_update='hard copy at start of every epoch; frozen for that entire epoch; terminal bootstrap zero',selection='Validation group -> episode -> state macro MC MSE; terminal excluded',test='No Test evaluation or selection',sampling='uniform seed-group -> episode -> nonterminal state, replacement',cases=['mixed_policies','homogeneous128'])

def fingerprint(model):
    h=hashlib.sha256()
    for k,v in sorted(model.state_dict().items()):h.update(k.encode());h.update(v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()

def metrics(records,ids,prediction,temporal):
    errors=np.array(prediction)-np.array([records[i]['target'] for i in ids]);by_ep=defaultdict(list);ep_group={}
    for j,i in enumerate(ids):by_ep[records[i]['episode']].append(j);ep_group[records[i]['episode']]=records[i]['group']
    by_group=defaultdict(list)
    for ep,at in by_ep.items():by_group[ep_group[ep]].append(dict(mae=float(np.mean(abs(errors[at]))),mse=float(np.mean(errors[at]**2))))
    def subset(condition):
        at=[j for j,i in enumerate(ids) if condition(records[i],i)]
        if not at:return dict(states=0,games=0,groups=0)
        e=errors[at];return dict(states=len(at),games=len({records[ids[j]]['episode'] for j in at}),groups=len({records[ids[j]]['group'] for j in at}),mae=float(abs(e).mean()),rmse=float(np.sqrt(np.mean(e**2))),bias=float(e.mean()),overprediction=float(np.maximum(e,0).mean()),underprediction=float(np.maximum(-e,0).mean()))
    return dict(all=subset(lambda r,i:True),near_go=subset(lambda r,i:0<temporal['distance'][i]<=4),score2000=subset(lambda r,i:r['score']>=2000),score3000=subset(lambda r,i:r['score']>=3000),large_return=subset(lambda r,i:r['target']>=1000),wm_pre=subset(lambda r,i:r['wm_window']=='pre_observed'),wm_post=subset(lambda r,i:r['wm_window']=='post_observed'),group_macro_mae=float(np.mean([np.mean([x['mae'] for x in v]) for v in by_group.values()])),group_macro_mse=float(np.mean([np.mean([x['mse'] for x in v]) for v in by_group.values()]))/1e6,groups={k:dict(mae=float(np.mean([x['mae'] for x in v])),mse=float(np.mean([x['mse'] for x in v])),games=len(v)) for k,v in by_group.items()})

def bootstrap_targets(target_model,boards,ids,temporal):
    """Only same-Train-episode future states, in normalized point units."""
    rewards=np.array(temporal['reward'],copy=True)/1000;next_ids=temporal['next_index'];done=temporal['terminal']
    at=np.asarray(ids)[~done[ids]];future=sorted(set(int(next_ids[i]) for i in at))
    if future:
        if max(future)>=len(boards.records):raise ValueError('External terminal sent to network')
        if any(boards.records[j]['split']!='train' for j in future):raise ValueError('Non-Train bootstrap leakage')
        pred=infer(target_model,'geometry',boards,future)/1000;lookup=dict(zip(future,pred))
        for i in at:rewards[i]+=lookup[int(next_ids[i])]
    return torch.tensor(rewards,dtype=torch.float32)

def train_trial(root,boards,temporal,case,variant,seed):
    records=boards.records;selected=temporal['homogeneous'] if case=='homogeneous128' else np.ones(len(records),dtype=bool)
    ids=np.array([i for i,r in enumerate(records) if r['split']=='train' and not r['game_over'] and selected[i]]);val=[i for i,r in enumerate(records) if r['split']=='validation' and not r['game_over'] and selected[i]]
    out=root/case/variant/str(seed);out.mkdir(parents=True,exist_ok=False)
    torch.manual_seed(seed);model=GeometryValueNetwork();target_model=copy.deepcopy(model);initial=fingerprint(model)
    for p in target_model.parameters():p.requires_grad_(False)
    opt=torch.optim.AdamW(model.parameters(),lr=CONFIG['lr'],weight_decay=CONFIG['weight_decay']);scheduler=torch.optim.lr_scheduler.StepLR(opt,step_size=8,gamma=.5)
    sample_gen=torch.Generator().manual_seed(seed+100);mask_gen=torch.Generator().manual_seed(seed+200)
    ep_size=Counter(records[i]['episode'] for i in ids);group_eps=defaultdict(set)
    for i in ids:group_eps[records[i]['group']].add(records[i]['episode'])
    weights=torch.tensor([1/(ep_size[records[i]['episode']]*len(group_eps[records[i]['group']])) for i in ids],dtype=torch.float64)
    mc=torch.tensor(boards.targets);alpha=CONFIG['td_weights'][variant];best=float('inf');bad=0;history=[];updates=0;started=time.monotonic()
    atomic_json(out/'run.json',dict(case=case,variant=variant,seed=seed,config=CONFIG,initial_model_sha256=initial,parameters=sum(p.numel() for p in model.parameters()),train_states=len(ids),validation_states=len(val)))
    for epoch in range(1,CONFIG['epochs']+1):
        if alpha:target_model.load_state_dict(model.state_dict());target_model.eval();td=bootstrap_targets(target_model,boards,ids,temporal)
        order=ids[torch.multinomial(weights,len(ids),replacement=True,generator=sample_gen).numpy()];mask_digest=hashlib.sha256();model.train();losses=[]
        for at in range(0,len(order),CONFIG['batch_size']):
            batch=order[at:at+CONFIG['batch_size']];inputs=boards.batch(batch);hidden=torch.rand(len(batch),generator=mask_gen)<CONFIG['next_mask_probability'];inputs[2][hidden,11:22]=0;inputs[2][hidden,23]=0;mask_digest.update(hidden.numpy().tobytes())
            pred=model(*inputs);mc_loss=(pred-mc[batch]).square().mean();loss=(1-alpha)*mc_loss
            if alpha:loss=loss+alpha*(pred-td[batch]).square().mean()
            if not torch.isfinite(loss):raise FloatingPointError('Nonfinite loss; do not silently clip/bootstrap')
            opt.zero_grad(set_to_none=True);loss.backward();opt.step();updates+=1;losses.append(float(loss.detach()))
        prediction=infer(model,'geometry',boards,val);score=metrics(records,val,prediction,temporal);criterion=score['group_macro_mse'];scheduler.step();improved=criterion<best
        if improved:best=criterion;bad=0
        else:bad+=1
        h=dict(epoch=epoch,loss=float(np.mean(losses)),validation=score,lr=opt.param_groups[0]['lr'],sample_order_sha256=hashlib.sha256(order.tobytes()).hexdigest(),augmentation_sha256=mask_digest.hexdigest())
        if alpha:
            err=(td[ids]-mc[ids])*1000;h['train_td_target_bias_vs_MC']=float(err.mean());h['train_td_target_mae_vs_MC']=float(err.abs().mean())
        history.append(h)
        save_checkpoint(out/'checkpoints',dict(checkpoint_version=1,epoch=epoch,updates=updates,kind='geometry',config=CONFIG,variant=variant,seed=seed,model=model.state_dict(),target_model=target_model.state_dict() if alpha else None,optimizer=opt.state_dict(),scheduler=scheduler.state_dict(),sampler_rng=sample_gen.get_state(),augmentation_rng=mask_gen.get_state(),initial_model_sha256=initial,input_spec=dict(base=INPUT_SPEC,geometry=FEATURE_SPEC),dataset_fingerprint=hashlib.sha256((root/'dataset/manifest.json').read_bytes()).hexdigest(),history=history),improved)
        atomic_json(out/'history.json',history);print(case,variant,seed,epoch,round(score['all']['mae'],2),round(score['all']['bias'],2),flush=True)
        if bad>=CONFIG['patience']:break
    payload,path=load_checkpoint(out/'checkpoints','best');model.load_state_dict(payload['model']);vp=infer(model,'geometry',boards,val);tp=infer(model,'geometry',boards,ids)
    result=dict(case=case,variant=variant,seed=seed,epoch=payload['epoch'],epochs_run=epoch,seconds=time.monotonic()-started,checkpoint=str(path),checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),validation=metrics(records,val,vp,temporal),train=metrics(records,ids,tp,temporal))
    atomic_json(out/'result.json',result)
    with (out/'validation_predictions.jsonl').open('x',encoding='utf8') as f:
        for i,pred in zip(val,vp):f.write(json.dumps(dict(index=i,episode=records[i]['episode'],group=records[i]['group'],prediction=float(pred),target=records[i]['target']))+'\n')
    return result

def summarize(root,results):
    summary={}
    for case in CONFIG['cases']:
        variants={}
        for variant in CONFIG['td_weights']:
            rows=[r for r in results if r['case']==case and r['variant']==variant];metrics_={}
            for cohort in ['all','near_go','score2000','score3000','large_return','wm_pre','wm_post']:
                metrics_[cohort]={}
                for field in ['mae','rmse','bias','overprediction','underprediction']:
                    vals=[r['validation'][cohort][field] for r in rows if field in r['validation'][cohort]]
                    if vals:metrics_[cohort][field]=dict(mean=float(np.mean(vals)),sd=float(np.std(vals,ddof=1)),values=vals)
                metrics_[cohort]['counts']={k:rows[0]['validation'][cohort][k] for k in ('states','games','groups')}
            variants[variant]=dict(validation=metrics_,selection_macro_mse_mean=float(np.mean([r['validation']['group_macro_mse'] for r in rows])),train_mae_mean=float(np.mean([r['train']['all']['mae'] for r in rows])),seconds=sum(r['seconds'] for r in rows),epochs=[r['epoch'] for r in rows])
        mixed=min(['mix25','mix50'],key=lambda k:variants[k]['selection_macro_mse_mean']);summary[case]=dict(variants=variants,selected_mixed=mixed,selection='mean Validation macro MC MSE across 3 initialization seeds; not Test')
    # Pairing audit is over every common epoch, not just final selected checkpoints.
    audit=[]
    for case in CONFIG['cases']:
        for seed in CONFIG['seeds']:
            runs=[root/case/v/str(seed) for v in CONFIG['td_weights']];hist=[json.loads((p/'history.json').read_text()) for p in runs];initial={json.loads((p/'run.json').read_text())['initial_model_sha256'] for p in runs};common=min(map(len,hist));same=all(len({h[e]['sample_order_sha256'] for h in hist})==1 and len({h[e]['augmentation_sha256'] for h in hist})==1 for e in range(common))
            audit.append(dict(case=case,seed=seed,initialization_equal=len(initial)==1,sampling_and_masks_equal=same,common_epochs=common))
    if not all(a['initialization_equal'] and a['sampling_and_masks_equal'] for a in audit):raise ValueError('Paired learning conditions diverged')
    atomic_json(root/'summary.json',dict(cases=summary,paired_audit=audit,test_evaluated=False,standard_adoption=False));return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    atomic_json(a.output/'experiment_plan.json',CONFIG);audit=prepare(a.output);print(json.dumps(audit),flush=True)
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True);boards=PackedBoards(load_restricted(a.output/'dataset'));temporal=np.load(a.output/'dataset/temporal.npz');results=[]
    for case in CONFIG['cases']:
        for seed in CONFIG['seeds']:
            for variant in CONFIG['td_weights']:results.append(train_trial(a.output,boards,temporal,case,variant,seed))
    summary=summarize(a.output,results);print(json.dumps({k:{v:round(x['validation']['all']['mae']['mean'],2) for v,x in s['variants'].items()} for k,s in summary.items()}),flush=True)

if __name__=='__main__':main()
