"""Run exactly one bounded, isolated diagnostic Player; never touches collectors."""
import argparse
import json
import subprocess
import time
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--timeout',type=float,default=120);p.add_argument('--base-port',type=int,default=41900);a=p.parse_args()
    config=json.loads(a.config.read_text(encoding='utf-8-sig'));output=Path(config['output']);folder=output.parent
    files=[output,folder/'player.log',folder/'runtime.jsonl']
    if any(x.exists() for x in files):raise FileExistsError('Use a fresh output location')
    args=[str(a.exe.resolve()),'-batchmode','-nographics','-job-worker-count','1','--suika-audio','0','--suika-events','1',
          '--suika-listen-port',str(a.base_port),'--suika-python-port',str(a.base_port+1),'-logFile',str((folder/'player.log').resolve()),
          '-suikaRuntimeProbe',str((folder/'runtime.jsonl').resolve()),'-suikaCounterfactualProbe',str(a.config.resolve())]
    start=time.monotonic();flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
    child=subprocess.Popen(args,creationflags=flags)
    try:
        child.wait(timeout=a.timeout)
        if child.returncode:raise RuntimeError(f'Diagnostic Player failed ({child.returncode}); see {folder / "player.log"}')
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=10)
    result=dict(elapsed_seconds=time.monotonic()-start,returncode=child.returncode,command=args)
    (folder/'execution.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
