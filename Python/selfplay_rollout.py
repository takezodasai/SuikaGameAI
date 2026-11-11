"""Nightly self-play -> durable natural-GO experience -> new versioned policy."""
import argparse,json,secrets
from pathlib import Path
from rollout_selfplay import ROOT,DEFAULT_MODEL,DEFAULT_EXE,collect,summary,exclusive_lock,atomic,reservations

def known_seeds():
    found=set(reservations()[0]);outputs=ROOT/'Python/outputs'
    manifest=outputs/'policy_success_01/dataset/manifest.json'
    found.update(e['seed'] for e in json.loads(manifest.read_text())['episodes'])
    for name in ['job.json','config.json']:
        for path in outputs.rglob(name):
            try:
                r=json.loads(path.read_text());s=r.get('game_seed',r.get('source_seed'))
                if isinstance(s,int):found.add(s)
            except (OSError,ValueError):pass
    return sorted(found)

def update(out,model,extras=()):
    from rollout_experience_learning import train_generation
    with exclusive_lock(Path(out)/'learning.lock'):
        result=train_generation(out,model,extras)
        if result.get('validation') and result.get('parent'):
            result['validation_proxy_improved']=result['validation']['weighted_loss']<result['parent']['validation']['weighted_loss'];result['recommendation']='experimental_only_not_promoted' if result['validation_proxy_improved'] else 'keep_parent_default'
        atomic(Path(out)/'latest_training.json',result);print(json.dumps(result,indent=2));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('collect');c.add_argument('--output',type=Path);c.add_argument('--resume',action='store_true');c.add_argument('--model',type=Path,default=DEFAULT_MODEL);c.add_argument('--exe',type=Path,default=DEFAULT_EXE);c.add_argument('--workers',type=int,default=4);c.add_argument('--hours',type=float,default=8);c.add_argument('--base-port',type=int,default=44000);c.add_argument('--seed-base',type=int);c.add_argument('--mixture',type=float,default=.5);c.add_argument('--max-jobs',type=int,default=1000);c.add_argument('--max-drops',type=int,default=100000);c.add_argument('--game-seconds',type=float,default=14400);c.add_argument('--stall-seconds',type=float,default=720);c.add_argument('--no-train',action='store_true');c.add_argument('--dry-run',action='store_true')
    t=sub.add_parser('train');t.add_argument('--output',type=Path,required=True);t.add_argument('--model',type=Path);t.add_argument('--extra-trace',type=Path,action='append',default=[])
    s=sub.add_parser('summary');s.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='summary':
        result={k:v for k,v in summary(a.output,persist=False).items() if k!='jobs'}
        for name in ['runtime.json','latest_training.json']:
            if (a.output/name).exists():result[name]=json.loads((a.output/name).read_text())
        print(json.dumps(result,indent=2));return
    if a.command=='train':
        actor=a.model or json.loads((a.output/'collection.json').read_text())['model'];update(a.output,actor,a.extra_trace);return
    if a.output is None:
        if a.resume:p.error('--resume requires the existing --output folder')
        import datetime,uuid
        a.output=ROOT/'Python/outputs'/('rollout_selfplay_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    print('Output: '+str(a.output.resolve()),flush=True)
    if a.resume:cfg=json.loads((a.output/'collection.json').read_text())
    else:
        cfg=dict(exe=str(a.exe),model=str(a.model),workers=a.workers,hours=a.hours,base_port=a.base_port,seed_base=a.seed_base if a.seed_base is not None else secrets.randbelow(1500000000)+400000000,mixture=a.mixture,max_jobs=a.max_jobs,max_drops=a.max_drops,game_seconds=a.game_seconds,stall_seconds=a.stall_seconds,iterations=256,depth=4,max_attempts=2,excluded_seeds=known_seeds(),train_after=not a.no_train)
    if a.dry_run:
        print(json.dumps({k:v for k,v in cfg.items() if k!='excluded_seeds'},indent=2));print('No Player started. Historical excluded seeds:',len(cfg.get('excluded_seeds',[])));return
    result=collect(a.output,cfg,a.resume);print(json.dumps({k:v for k,v in result.items() if k!='jobs'},indent=2))
    if cfg.get('train_after',True) and not a.no_train:
        try:update(a.output,cfg['model'])
        except KeyboardInterrupt:print('Training interrupted; raw games and parent model preserved. Run train again into a new attempt.')

if __name__=='__main__':main()
