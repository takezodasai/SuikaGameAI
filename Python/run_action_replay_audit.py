"""One bounded actual-world replay diagnostic; never uses a prediction Scene."""
import argparse,json,subprocess,time
from pathlib import Path
from suika_ai.parallel_play import worker_specs,check_ports

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seeds',type=int,nargs='+',default=[99117,99118]);p.add_argument('--drops',type=int,default=12);p.add_argument('--repeats',type=int,default=3);p.add_argument('--timeout',type=float,default=180);p.add_argument('--base-port',type=int,default=41980);p.add_argument('--startup-seed',type=int,help='Control pre-Reset object allocation history as well as Reset RNG');p.add_argument('--branch-turn',type=int);p.add_argument('--branch-x',type=float);a=p.parse_args()
    if not 1<=a.drops<=24 or not 1<=len(a.seeds)<=3 or not 1<=a.repeats<=3:raise ValueError('Bounded diagnostic only')
    if (a.branch_turn is None)!=(a.branch_x is None) or a.branch_turn is not None and not (1<=a.branch_turn<=a.drops and 0<=a.branch_x<=1):raise ValueError('Legal branch turn/x required')
    check_ports(worker_specs(1,a.base_port));a.output.mkdir(parents=True,exist_ok=False)
    cfg=dict(output=str((a.output/'ticks.jsonl').resolve()),seeds=a.seeds,positions=([.25,.75,.5,0,1,.37]*4)[:a.drops],repeats=a.repeats,startup_seed=a.startup_seed)
    if a.branch_turn is not None:cfg['positions'][a.branch_turn-1]=a.branch_x
    cfg['branch_turn']=a.branch_turn;cfg['branch_x']=a.branch_x
    config=a.output/'config.json';config.write_text(json.dumps(cfg,indent=2),encoding='utf8')
    command=[str(a.exe.resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-listen-port',str(a.base_port),'--suika-python-port',str(a.base_port+1),'-logFile',str((a.output/'player.log').resolve()),'-suikaActionReplay',str(config.resolve())]
    if a.startup_seed is not None:command+=['--suika-seed',str(a.startup_seed)]
    started=time.monotonic();child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    try:
        child.wait(timeout=a.timeout)
        if child.returncode:raise RuntimeError(f'Replay exited {child.returncode}; saved partial data must not be used as verified replay')
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=10)
    result=dict(seconds=time.monotonic()-started,command=command,natural_go_return_labels=False)
    (a.output/'execution.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))

if __name__=='__main__':main()
