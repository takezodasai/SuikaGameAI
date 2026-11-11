"""Outcome-weighted policy update; group cross-fitted state baseline, no Test selection."""
import collections,hashlib,itertools,json,math,time
from pathlib import Path
import numpy as np
import torch
from learned_rollout import VERSION,GRID,features,probabilities
from rollout_selfplay import ROOT,sha,write,read_rows,job_results,audit_trace,reservations,atomic

BOOTSTRAP=ROOT/'Python/outputs/policy_success_01/dataset'

def from_trace(folder,parent_sha):
    folder=Path(folder);cfg=json.loads((folder/'config.json').read_text());rows,partial=read_rows(folder/'trace.jsonl')
    if partial:raise ValueError('Incomplete trace')
    if cfg.get('mode')!='learned' or not cfg.get('normal_start'):raise ValueError('Not actual learned-policy normal play')
    result=json.loads((folder/'result.json').read_text())
    if not result.get('natural_go') or result.get('exit_code',0)!=0 or result.get('process_error'):raise ValueError('Not complete natural GO')
    job=dict(index=result.get('job',0),game_seed=cfg['game_seed'],search_seed=cfg['search_seed']);a=audit_trace(folder,job,parent_sha,cfg['iterations'],0)
    if not a['valid_for_learning']:raise ValueError(str(a['errors']))
    end=next(r for r in reversed(rows) if r['evt']=='end');releases={r['command']['start_tick']:r for r in rows if r['evt']=='release'};actions={r['command']['start_tick']:r for r in rows if r['evt']=='action'};samples=[]
    for r in rows:
        if r['evt']!='decision' or r['command']['start_tick'] not in releases:continue
        selected=r['planning']['selected_index'];stats=r['search']['root'];xs=[c['x'] for c in stats]
        if xs!=GRID or r['command']['x']!=GRID[selected] or r['state']['score']>end['score']:raise ValueError('Action/return invariant')
        release=releases[r['command']['start_tick']];post=actions.get(r['command']['start_tick'],end)
        samples.append(dict(sample=dict(state=r['state'],geometry=r['state']['geometry']),selected_index=selected,visits=[c['visits'] for c in stats],mean_points=[c['mean_points'] for c in stats],return_points=end['score']-r['state']['score'],score=r['state']['score'],seed=cfg['game_seed'],initial8=a['initial8'],episode=str(folder.resolve()),source_kind='selfplay',original_split=None,actual_iterations=r['search']['completed_iterations'],depth=cfg['depth'],actor_sha256=parent_sha,action_id=r['command']['start_tick'],post_state=post['state'],post_phase='25_tick_action' if post['evt']=='action' else 'terminal_before_action_completion',raw_events=end['raw_events'],source_trace_sha256=a['trace_sha256']))
    return samples

def bootstrap_rows():
    manifest=json.loads((BOOTSTRAP/'manifest.json').read_text());episodes={e['id']:e for e in manifest['episodes']};out=[]
    for name in ['records.jsonl','states.jsonl']:
        if sha(BOOTSTRAP/name)!=manifest['files'][name]:raise ValueError('Changed bootstrap data')
    # The fixed historical test/validation membership is preserved; no Test scoring.
    for rline,sline in itertools.zip_longest((BOOTSTRAP/'records.jsonl').open(encoding='utf8'),(BOOTSTRAP/'states.jsonl').open(encoding='utf8')):
        if rline is None or sline is None:raise ValueError('Teacher/state length mismatch')
        r=json.loads(rline);s=json.loads(sline)
        if (r['episode'],r['action_id'])!=(s['episode'],s['action_id']):raise ValueError('Teacher identity mismatch')
        if r['split'] not in ['train','validation'] or r['candidate_x']!=GRID:continue
        ep=episodes[r['episode']]
        if not ep['natural_go']:continue
        out.append(dict(sample=s['sample'],selected_index=r['selected_index'],visits=r['visits'],return_points=r['future_points'],score=r['score'],seed=ep['seed'],initial8=ep['initial_sequence'],episode=r['episode'],source_kind='bootstrap',original_split=r['split'],actual_iterations=r['actual_iterations'],depth=r['depth'],action_id=r['action_id']))
    forbidden=[e for e in manifest['episodes'] if e['split'] not in ['train','validation']]
    return out,forbidden

def assign_groups(rows,forbidden,registry=None):
    if registry is None:registry={}
    seeds,prefix=reservations();seeds|={e['seed'] for e in forbidden};prefix|={e['initial_sequence'] for e in forbidden};valid=[];seen=set();excluded=collections.Counter()
    for r in rows:
        if r['seed'] in seeds or r['initial8'] in prefix:excluded['protected_test_group']+=1;continue
        key=(r['episode'],r['action_id'])
        if key in seen:excluded['duplicate_action']+=1;continue
        seen.add(key);valid.append(r)
    # A shared seed OR initial8 prefix links entire episodes, including sibling runs.
    ids={r['episode']:i for i,r in enumerate(valid)};parent={i:i for i in ids.values()};keys={}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    for r in valid:
        i=ids[r['episode']]
        for k in [('seed',r['seed']),('initial8',r['initial8'])]:
            if k in keys:parent[find(i)]=find(keys[k])
            else:keys[k]=i
    split={}
    for r in valid:
        g=find(ids[r['episode']]);r['group']=g
        if r['original_split']:
            if g in split and split[g]!=r['original_split']:raise ValueError('Historical Train/Validation collision')
            split[g]=r['original_split']
    for r in valid:
        for k in ['seed:'+str(r['seed']),'initial8:'+r['initial8']]:
            if k in registry:
                if r['group'] in split and split[r['group']]!=registry[k]:raise ValueError('Persistent split collision')
                split[r['group']]=registry[k]
    new_groups=sorted({r['group'] for r in valid if r['group'] not in split})
    count=sum(k.startswith('seed:') for k in registry)
    for g in new_groups:
        seed=min(r['seed'] for r in valid if r['group']==g)
        split[g]='validation' if count>=4 and int(hashlib.sha256(str(seed).encode()).hexdigest()[:8],16)%5==0 else 'train';count+=1
    for r in valid:r['split']=split[r['group']]
    for r in valid:
        if r['source_kind']=='selfplay':
            registry['seed:'+str(r['seed'])]=r['split'];registry['initial8:'+r['initial8']]=r['split']
    return valid,dict(excluded)

def fit_baseline(x,y,w,alpha=10.):
    mean=np.average(x,axis=0,weights=w);scale=np.sqrt(np.average((x-mean)**2,axis=0,weights=w));scale[scale<1e-6]=1;z=(x-mean)/scale;offset=float(np.average(y,weights=w));coef=np.linalg.solve(z.T@(w[:,None]*z)+alpha*np.eye(x.shape[1]),z.T@(w*(y-offset)))
    return dict(mean=mean.tolist(),scale=scale.tolist(),coef=coef.tolist(),offset=offset)

def baseline_predict(m,x):return m['offset']+((x-np.asarray(m['mean']))/np.asarray(m['scale']))@m['coef']

def advantage_weights(x,y,groups,train_mask,base_weights):
    train=np.flatnonzero(train_mask);g=sorted(set(groups[train].tolist()))
    if len(g)<3:raise ValueError('Need at least 3 independent Train groups for cross-fitted outcomes')
    # State only: mean candidate features has no chosen action or future label.
    pooled=x.mean(axis=1).astype(float);b=np.concatenate([pooled[:,:40]*5,pooled[:,200:]],axis=1);prediction=np.empty(len(y));fold={k:i%3 for i,k in enumerate(g)}
    for k in range(3):
        held=np.array([i for i in train if fold[groups[i]]==k]);other=np.array([i for i in train if fold[groups[i]]!=k]);m=fit_baseline(b[other],y[other],base_weights[other]);prediction[held]=baseline_predict(m,b[held])
    m=fit_baseline(b[train],y[train],base_weights[train]);val=np.flatnonzero(~train_mask);prediction[val]=baseline_predict(m,b[val]);residual=y-prediction;median=float(np.median(residual[train]));scale=max(100.,float(np.median(np.abs(residual[train]-median))*1.4826));weights=np.exp(np.clip(residual/scale,-math.log(2),math.log(2)))
    return weights,prediction,dict(model=m,scale=scale,fold_rule='3-fold whole source seed/prefix group cross fitting on Train; Validation predicted by Train only',rule='clip(exp((actual_remaining_points-state_baseline)/scale), 0.5, 2.0)',note='Observed-policy MC outcomes; not causal advantages or optimal returns')

def train_generation(collection,parent_model,extra_traces=()):
    began=time.perf_counter();collection=Path(collection).resolve();parent_model=Path(parent_model).resolve();parent_sha=sha(parent_model);parent=json.loads(parent_model.read_text());trace_paths=[]
    for r in job_results(collection):
        if r['valid_for_learning']:trace_paths.append(Path(r['attempt']))
    trace_paths+=list(map(Path,extra_traces));trace_paths=list(dict.fromkeys(p.resolve() for p in trace_paths));own=[];rejected=[];accepted=[]
    for path in trace_paths:
        try:own+=from_trace(path,parent_sha);accepted.append(path)
        except (OSError,ValueError,KeyError,AssertionError) as e:rejected.append(dict(path=str(path),reason=str(e)))
    if not own:return dict(status='skipped_no_valid_selfplay',rejected=rejected)
    bootstrap,forbidden=bootstrap_rows();registry=json.loads((collection/'split_registry.json').read_text()) if (collection/'split_registry.json').exists() else {};rows,excluded=assign_groups(bootstrap+own,forbidden,registry);atomic(collection/'split_registry.json',registry);trace_paths=accepted
    if not any(r['source_kind']=='selfplay' and r['split']=='train' for r in rows):return dict(status='skipped_no_new_train_group',rejected=rejected)
    fingerprint=hashlib.sha256(json.dumps(dict(parent=parent_sha,traces=[(str(p),sha(p/'trace.jsonl')) for p in trace_paths],bootstrap_manifest=sha(BOOTSTRAP/'manifest.json'),recipe='outcome-policy-v1:25epochs:lr.01:anchor.01:soft75chosen25:weight.5to2:baseline10'),sort_keys=True).encode()).hexdigest()
    target=collection/'generations'/('gen_'+fingerprint[:12]);target.parent.mkdir(exist_ok=True)
    if (target/'complete.json').exists():return {**json.loads((target/'complete.json').read_text()),'status':'already_trained'}
    if target.exists():target=target.with_name(target.name+'_attempt_'+__import__('uuid').uuid4().hex[:8])
    target.mkdir();write(target/'training_plan.json',dict(parent_model=str(parent_model),parent_sha256=parent_sha,fingerprint=fingerprint,source_traces=[str(p) for p in trace_paths],bootstrap_manifest_sha256=sha(BOOTSTRAP/'manifest.json'),seed=20261103,epochs=25,learning_rate=.01,anchor_regularization=.01,automatic_promotion=False))
    x=np.stack([features(r['sample']) for r in rows]).astype(np.float32);y=np.array([r['return_points'] for r in rows],dtype=float);groups=np.array([r['group'] for r in rows]);tm=np.array([r['split']=='train' for r in rows]);counts=collections.Counter(groups.tolist());base=np.array([min(2,max(.5,math.sqrt(r['actual_iterations']/256)))/counts[r['group']] for r in rows],dtype=np.float32);aw,pred,baseline=advantage_weights(x,y,groups,tm,base)
    torch.set_num_threads(1);torch.manual_seed(20261103);tx=torch.tensor(x);visits=torch.tensor(np.stack([np.array(r['visits'])/sum(r['visits']) for r in rows]),dtype=torch.float32);selected=torch.tensor([r['selected_index'] for r in rows]);bw=torch.tensor(base);weights=torch.tensor(aw,dtype=torch.float32);tr=torch.tensor(np.flatnonzero(tm));va=torch.tensor(np.flatnonzero(~tm))
    if len(va)==0:raise ValueError('Independent Validation missing')
    initial=torch.tensor(parent['weights'],dtype=torch.float32);theta=initial.clone().requires_grad_();opt=torch.optim.Adam([theta],lr=.01);best=float('inf');bestw=None;history=[]
    def metrics(ids):
        with torch.no_grad():
            lp=(tx[ids]@theta).log_softmax(-1);soft=-(visits[ids]*lp).sum(-1);hard=-lp[torch.arange(len(ids)),selected[ids]];w=bw[ids];weighted=(w*(.75*soft+.25*weights[ids]*hard)).sum()/(w*(.75+.25*weights[ids])).sum();ce=(w*(.75*soft+.25*hard)).sum()/w.sum();acc=(w*(lp.argmax(-1)==selected[ids])).sum()/w.sum();return dict(weighted_loss=float(weighted),imitation_CE=float(ce),selected_match=float(acc),states=len(ids),groups=len(set(groups[ids.tolist()].tolist())),games=len({rows[i]['episode'] for i in ids.tolist()}))
    parent_metrics=dict(train=metrics(tr),validation=metrics(va))
    for epoch in range(25):
        opt.zero_grad();lp=(tx[tr]@theta).log_softmax(-1);soft=-(visits[tr]*lp).sum(-1);hard=-lp[torch.arange(len(tr)),selected[tr]];loss=(bw[tr]*(.75*soft+.25*weights[tr]*hard)).sum()/(bw[tr]*(.75+.25*weights[tr])).sum()+.01*((theta-initial)**2).mean();loss.backward();opt.step();v=metrics(va);history.append(dict(epoch=epoch+1,train=metrics(tr),validation=v))
        if v['weighted_loss']<best:best=v['weighted_loss'];bestw=theta.detach().clone()
    with torch.no_grad():theta.copy_(bestw)
    model=dict(parent,weights=theta.detach().tolist(),parent_sha256=parent_sha,generation=fingerprint,learning='outcome-policy-v1; observed MC return minus cross-fitted public-state baseline; bounded selected-action weighting; not promoted')
    write(target/'model.json',model);write(target/'state_baseline.json',baseline)
    with (target/'experience.jsonl').open('x',encoding='utf8') as f:
        for i,r in enumerate(rows):
            f.write(json.dumps(dict(input=r['sample'],candidate_x=GRID,selected_index=r['selected_index'],root_visits=r['visits'],root_mean_points=r.get('mean_points'),source_seed=r['seed'],initial8=r['initial8'],seed_group=r['group'],split=r['split'],source_kind=r['source_kind'],episode=r['episode'],actor_sha256=r.get('actor_sha256'),source_trace_sha256=r.get('source_trace_sha256'),actual_iterations=r['actual_iterations'],depth=r['depth'],teacher=dict(actual_remaining_points=float(y[i]),state_baseline=float(pred[i]),outcome_weight=float(aw[i])),post_state=r.get('post_state'),post_phase=r.get('post_phase'),raw_events=r.get('raw_events')),ensure_ascii=False)+'\n')
    learned=dict(status='trained',generation=str(target),model=str(target/'model.json'),model_sha256=sha(target/'model.json'),parent_sha256=parent_sha,seconds=time.perf_counter()-began,selfplay_games=len({r['episode'] for r in rows if r['source_kind']=='selfplay'}),selfplay_states=sum(r['source_kind']=='selfplay' for r in rows),bootstrap_states=sum(r['source_kind']=='bootstrap' for r in rows),train=metrics(tr),validation=metrics(va),parent=parent_metrics,weight_min=float(aw.min()),weight_max=float(aw.max()),weight_under_one=int(sum(aw<1)),weight_over_one=int(sum(aw>1)),parameter_change_l2=float(torch.linalg.vector_norm(theta-initial)),automatic_promotion=False,rejected=rejected,excluded=excluded)
    write(target/'evaluation.json',dict(**learned,history=history))
    # Reload-only inference assertion, no future labels supplied to the policy.
    reloaded=json.loads((target/'model.json').read_text());p=probabilities(reloaded,rows[0]['sample']);assert np.isfinite(p).all() and abs(sum(p)-1)<1e-9
    write(target/'complete.json',learned)
    return learned
