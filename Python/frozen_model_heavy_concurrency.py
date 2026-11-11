"""Additional bounded 2/4-worker test; never changes the overnight collector."""
import json,os,subprocess,sys,time
from pathlib import Path
import collection_concurrency_probe as probe
from frozen_model_actual_play import ROOT,write
from suika_ai.overnight_collection import process_memory

def main():
    base=ROOT/'heavy_concurrency';base.mkdir(exist_ok=False)
    if probe.active_players():write(base/'blocked.json',dict(reason='Active Player; no launch'));return
    plan=dict(collection_Player='Unity/Builds/SyncOptimized_03/SuikaGameAI.exe',benchmark=dict(depth=6,iterations=512,seeds=list(range(892610501,892610505)),drops=8,think_seconds=30,timeout=720,game_cap_seconds=65))
    write(base/'plan.json',plan);results={};started=time.monotonic()
    for workers in [2,4]:
        if probe.active_players() or time.monotonic()-started>300:break
        folder=base/f'workers_{workers}';folder.mkdir();children=[];logs=[]
        for i,ids in enumerate([[0,1,2,3]] if workers==2 else [[0,1],[2,3]]):
            log=(folder/f'group_{i}.log').open('x');logs.append(log)
            code='import collection_concurrency_probe as p;from pathlib import Path;p.ROOT=Path('+repr(str(base.resolve()))+');p.group(Path('+repr(str((folder/f'group_{i}').resolve()))+'),'+repr(ids)+')'
            children.append(subprocess.Popen([sys.executable,'-c',code],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        begin=time.monotonic();last=probe.cpu_times();samples=[];owned=set();timed_out=False
        try:
            while any(p.poll() is None for p in children):
                time.sleep(1);now=probe.cpu_times();cpu=100*(1-(now[0]-last[0])/(now[1]-last[1])) if now and last and now[1]>last[1] else None;last=now
                for manifest in folder.rglob('run.json'):
                    try:owned.update(w['pid'] for w in json.loads(manifest.read_text())['workers'])
                    except (ValueError,KeyError):pass
                memory=[m for pid in owned if (m:=process_memory(pid))];samples.append(dict(seconds=time.monotonic()-begin,cpu=cpu,private=sum(m['private_bytes'] for m in memory),working_set=sum(m['working_set_bytes'] for m in memory)))
                if time.monotonic()-begin>150:timed_out=True;break
        finally:
            # These exact PIDs belong only to newly launched manifests.
            if any(p.poll() is None for p in children):
                for pid in owned:
                    try:os.kill(pid,15)
                    except OSError:pass
                for child in children:
                    if child.poll() is None:child.terminate();child.wait(10)
            for log in logs:log.close()
        try:r=probe.summarize(folder,time.monotonic()-begin,samples)
        except Exception as e:r=dict(error=str(e),seconds=time.monotonic()-begin)
        r['phase_cap_reached']=timed_out;r['note']='512 iterations/depth6, early <=8 drops; step/wall capped, not natural GO. Global CPU, one fixed-order trial.'
        r['supervisor_exits']=[p.returncode for p in children];write(folder/'samples.json',samples);write(folder/'result.json',r);results[str(workers)]=r
    write(base/'summary.json',results)

if __name__=='__main__':main()
