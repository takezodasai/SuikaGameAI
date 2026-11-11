"""Frozen Train/Validation only; never evaluates reserved Test."""
import collections,hashlib,json,time,itertools
from pathlib import Path
import numpy as np
import torch
from learned_rollout import features,VERSION,GRID

def main():
    start=time.perf_counter();out=Path(__file__).parent/'outputs/learned_rollout_01';cfg=json.loads((out/'protocol.json').read_text());src=Path(__file__).parent/'outputs/policy_success_01/dataset'
    if (out/'training').exists():raise FileExistsError('Protect trained model; choose a new frozen experiment output')
    for name,h in cfg['data'].items():
        if hashlib.sha256((src/name).read_bytes()).hexdigest()!=h:raise ValueError('Changed frozen source')
    reservation=json.loads((Path(__file__).parent/'outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    seeds={r['seed'] for r in reservation};prefixes={r['initial_sequence'] for r in reservation}
    manifest=json.loads((src/'manifest.json').read_text());eps={e['id']:e for e in manifest['episodes']};samples=[];excluded=collections.Counter();groups={}
    for record,state in itertools.zip_longest((src/'records.jsonl').open(encoding='utf8'),(src/'states.jsonl').open(encoding='utf8')):
        if record is None or state is None:raise ValueError('Mismatched state/teacher lengths')
        r=json.loads(record);s=json.loads(state)
        assert (r['episode'],r['action_id'])==(s['episode'],s['action_id'])
        if r['split'] not in ['train','validation']:excluded['protected_test']+=1;continue
        e=eps[r['episode']]
        if e['seed'] in seeds or e['initial_sequence'] in prefixes:excluded['reserved_Test19']+=1;continue
        if not e['natural_go'] or r['candidate_x']!=GRID:excluded['non_grid5_or_incomplete']+=1;continue
        for key in [('seed',e['seed']),('initial8',e['initial_sequence']),('group',r['group'])]:
            if key in groups and groups[key]!=r['split']:raise ValueError('Split leakage')
            groups[key]=r['split']
        visits=np.asarray(r['visits'],dtype=float)
        if visits.sum()<=0:excluded['no_visits']+=1;continue
        target=visits/visits.sum();target=.75*target;target[r['selected_index']]+=.25
        samples.append((r,features(s['sample']),target))
    counts=collections.Counter(r['group'] for r,x,y in samples);xs=torch.tensor(np.stack([x for r,x,y in samples]),dtype=torch.float32);ys=torch.tensor(np.stack([y for r,x,y in samples]),dtype=torch.float32)
    weights=torch.tensor([r['quality_weight']/counts[r['group']] for r,x,y in samples]);tr=torch.tensor([i for i,(r,x,y) in enumerate(samples) if r['split']=='train']);va=torch.tensor([i for i,(r,x,y) in enumerate(samples) if r['split']=='validation'])
    torch.set_num_threads(1);torch.manual_seed(cfg['seed']);theta=torch.zeros(213,requires_grad=True);opt=torch.optim.Adam([theta],lr=cfg['lr']);history=[];best=float('inf');bestw=None
    def metrics(ids):
        with torch.no_grad():
            logp=(xs[ids]@theta).log_softmax(-1);ww=weights[ids];ce=(-(ys[ids]*logp).sum(-1)*ww).sum()/ww.sum();selected=torch.tensor([samples[i][0]['selected_index'] for i in ids.tolist()]);acc=((logp.argmax(-1)==selected)*ww).sum()/ww.sum()
            return dict(CE=float(ce),selected_match=float(acc),states=len(ids),groups=len({samples[i][0]['group'] for i in ids.tolist()}),games=len({samples[i][0]['episode'] for i in ids.tolist()}))
    for epoch in range(cfg['epochs']):
        opt.zero_grad();logp=(xs[tr]@theta).log_softmax(-1);loss=(-(ys[tr]*logp).sum(-1)*weights[tr]).sum()/weights[tr].sum()+cfg['l2']*(theta*theta).mean();loss.backward();opt.step();v=metrics(va);history.append(dict(epoch=epoch+1,train=metrics(tr),validation=v))
        if v['CE']<best:best=v['CE'];bestw=theta.detach().clone()
    with torch.no_grad():theta.copy_(bestw)
    model=dict(version=VERSION,weights=theta.detach().tolist(),grid=GRID,parameters=213,training_seed=cfg['seed'],input_note='Public current state and current simulated NEXT only; fixed scales; no future returns')
    dest=out/'training';dest.mkdir(exist_ok=False);(dest/'model.json').write_text(json.dumps(model,indent=2));evaluation=dict(train=metrics(tr),validation=metrics(va),excluded=dict(excluded),history=history,seconds=time.perf_counter()-start,scope='existing development validation only; no Test opened; no policy strength claim',target='.75 root visit distribution + .25 MCTS chosen onehot; quality/group weights')
    # Constant action-prior baseline, fitted only on Train.
    prior=(ys[tr]*weights[tr,None]).sum(0)/weights[tr].sum();evaluation['prior_validation_CE']=float((-(ys[va]*prior.clamp_min(1e-9).log()).sum(-1)*weights[va]).sum()/weights[va].sum())
    (dest/'evaluation.json').write_text(json.dumps(evaluation,indent=2));print(json.dumps({k:v for k,v in evaluation.items() if k!='history'},indent=2))
    # Public-only cross-runtime parity cases; never Test.
    cases=[]
    for line in (src/'states.jsonl').open(encoding='utf8'):
        s=json.loads(line)
        if s['split']!='train':continue
        if len(cases)>=12:break
        if not s['sample']['state']['fruits'] and cases:continue
        f=features(s['sample']);p=np.exp(f@np.asarray(model['weights'])-max(f@np.asarray(model['weights'])));p/=p.sum();sample=s['sample'];sample['state']['geometry']=sample['geometry'];cases.append(dict(state=sample['state'],probabilities=p.tolist()))
    (dest/'parity.json').write_text(json.dumps(dict(cases=cases)))

if __name__=='__main__':main()
