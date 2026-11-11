"""Bounded single-Player reliability diagnostic, separate from active collection."""
import argparse,json,subprocess,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--capsules',action='store_true');p.add_argument('--timeout',type=float,default=180);p.add_argument('--base-port',type=int,default=41940);a=p.parse_args()
    cfg=json.loads(a.config.read_text(encoding='utf-8-sig'));out=Path(cfg['output']);folder=out.parent
    if any((folder/name).exists() for name in [out.name,'player.log','runtime.jsonl','capsules.jsonl']):raise FileExistsError('Use a fresh diagnostic destination')
    folder.mkdir(parents=True,exist_ok=True)
    args=[str(a.exe.resolve()),'-batchmode','-nographics','-job-worker-count','1','--suika-audio','0','--suika-events','1','--suika-listen-port',str(a.base_port),'--suika-python-port',str(a.base_port+1),'-logFile',str((folder/'player.log').resolve()),'-suikaRuntimeProbe',str((folder/'runtime.jsonl').resolve()),'-suikaPhysicsAudit',str(a.config.resolve())]
    if a.capsules:args+=['-suikaDecisionCapsules',str((folder/'capsules.jsonl').resolve())]
    start=time.monotonic();child=subprocess.Popen(args,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
    try:
        child.wait(timeout=a.timeout)
        if child.returncode:raise RuntimeError(f'Player exit {child.returncode}; inspect {folder}')
        rows=[json.loads(line) for line in out.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        if len(rows)!=len(cfg['cases'])*len(cfg['positions']):raise RuntimeError('Incomplete diagnostic')
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=10)
    (folder/'execution.json').write_text(json.dumps(dict(seconds=time.monotonic()-start,command=args,rows=len(rows)),indent=2),encoding='utf8')
    print(json.dumps(dict(rows=len(rows),seconds=time.monotonic()-start)))

if __name__=='__main__':main()
