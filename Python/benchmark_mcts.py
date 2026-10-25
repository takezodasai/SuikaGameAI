"""Bounded fixed-root A/B benchmark; never collects full games or edits fixtures."""
import argparse,json,os,subprocess,sys,threading,time
from pathlib import Path
from diagnose_runtime import sample

def run(output,games,fixtures,repeats,mode,verify=True):
    output.mkdir(parents=True,exist_ok=False)
    children=[];resources=[];gpus=[];stop=threading.Event()
    def monitor():
        while not stop.wait(.25):
            resources.append(dict(wall=time.monotonic(),processes={str(p.pid):sample(p.pid) for p in children}))
    def gpu_monitor():
        while not stop.is_set():
            try:
                result=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,utilization.memory,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,creationflags=subprocess.CREATE_NO_WINDOW)
                gpus.append(dict(wall=time.monotonic(),system_gpu=result.stdout.strip(),error=result.stderr.strip()))
            except (OSError,subprocess.TimeoutExpired) as e:gpus.append(dict(error=str(e)))
            stop.wait(.75)
    threads=[threading.Thread(target=monitor),threading.Thread(target=gpu_monitor)]
    try:
        exe=Path(__file__).resolve().parent.parent/'Unity/Builds/Step6/SuikaGameAI.exe'
        for i in range(games):
            dest=(output/f'game_{i:02}.jsonl').resolve();cfg=(output/f'config_{i:02}.json').resolve()
            cfg.write_text(json.dumps(dict(output=str(dest),fixtures=[str(f.resolve()) for f in fixtures],repeats=repeats,verify=verify,mode=mode)))
            cmd=[str(exe),'--suika-game-id',f'bench_{i:02}','--suika-listen-port',str(31000+2*i),'--suika-python-port',str(31001+2*i),'--suika-seed','745000','-batchmode','-nographics','-logFile',str((output/f'player_{i:02}.log').resolve()),'-suikaRuntimeProbe',str((output/f'runtime_{i:02}.jsonl').resolve()),'-suikaMctsBenchmark',str(cfg)]
            children.append(subprocess.Popen(cmd,creationflags=subprocess.CREATE_NO_WINDOW))
        for t in threads:t.start()
        deadline=time.monotonic()+180
        while any(p.poll() is None for p in children):
            if time.monotonic()>deadline:raise TimeoutError('Bounded benchmark exceeded 180 seconds')
            time.sleep(.2)
        codes=[p.returncode for p in children]
        if any(c!=0 for c in codes):raise RuntimeError(f'Native benchmark failed {codes}; inspect logs')
    finally:
        stop.set()
        for t in threads:
            if t.ident is not None:t.join(4)
        for p in children:
            if p.poll() is None:p.terminate();p.wait(5)
        with (output/'resources.json').open('x') as f:json.dump(resources,f)
        with (output/'gpu.json').open('x') as f:json.dump(gpus,f)
    print(json.dumps(dict(output=str(output),games=games,codes=codes)),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--games',type=int,choices=(1,4),default=1);p.add_argument('--fixtures',type=Path,nargs='+',required=True);p.add_argument('--repeats',type=int,choices=(1,2,3),default=2);p.add_argument('--mode',choices=('mcts','mcts_value'),default='mcts');p.add_argument('--timing-only',action='store_true');a=p.parse_args()
    if len(a.fixtures)>4:p.error('At most four fixed boards')
    run(a.output,a.games,a.fixtures,a.repeats,a.mode,not a.timing_only)
if __name__=='__main__':main()
