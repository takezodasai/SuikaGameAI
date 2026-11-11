"""Bounded 2 vs 4 worker test; intentional step caps are never natural-GO samples."""
import argparse,concurrent.futures,ctypes,json,os,subprocess,sys,time
from pathlib import Path
from action_decision_plan import ROOT,write
from suika_ai.parallel_play import run_parallel,validate_run
from suika_ai.overnight_collection import settings,process_memory

def group(folder,indices):
    plan=json.loads((ROOT/'plan.json').read_text());cfg=plan['benchmark'];folder=Path(folder);folder.mkdir(exist_ok=False)
    def job(i):
        return run_parallel(Path(plan['collection_Player']),folder/f'game_{i}',games=1,episodes=1,max_steps=cfg['drops'],base_port=44200+10*i,seed=cfg['seeds'][i],headless=True,settings=settings(dict(depth=cfg['depth'],iterations=cfg['iterations']),8191,cfg['think_seconds']),main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version='step8e-all-fruit-go-v2',episode_events=True,max_episode_seconds=cfg['game_cap_seconds'],step_timeout=cfg['timeout'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(job,indices))

def cpu_times():
    idle,kernel,user=ctypes.c_ulonglong(),ctypes.c_ulonglong(),ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):return None
    return idle.value,kernel.value+user.value

def active_players():
    p=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process SuikaGameAI -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) | ConvertTo-Json -Compress"],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    s=p.stdout.strip();v=json.loads(s) if s else [];return v if isinstance(v,list) else [v]

def summarize(folder,seconds,samples):
    games=[];ms=[];iterations=[];caps=0;errors=0
    for p in sorted(folder.rglob('run.json')):
        rows=[json.loads(l) for l in (p.parent/'game_00.jsonl').read_text().splitlines()];end=next((r for r in reversed(rows) if r.get('event')=='episode_end'),{});actions=[r for r in rows if r['event']=='transition']
        for r in actions:
            m=r['info']['planning'].get('mcts') or {};iterations.append(m.get('completed_iterations',0));ms.append(m.get('elapsed_ms',0));caps+=int(m.get('budget_stop_reason')=='time_limit' or m.get('elapsed_ms',0)>=30000)
        audit=validate_run(p.parent);worker_errors=[r for r in rows if r['event']=='worker_error'];errors+=len(worker_errors)
        games.append(dict(seed=json.loads(p.read_text())['workers'][0]['seed'],actions=len(actions),natural_go=end.get('game_over') is True and not end.get('truncated'),reason=end.get('reason'),conserved=end.get('conserved'),audit=audit,errors=worker_errors))
    n=len(ms);return dict(games=games,seconds=seconds,decisions=n,decisions_per_hour=n*3600/seconds if seconds else None,iterations=sum(iterations),minimum_iterations=min(iterations) if iterations else None,maximum_iterations=max(iterations) if iterations else None,cap_rate=caps/n if n else None,mean_decision_ms=sum(ms)/n if n else None,errors=errors,natural_completed=sum(g['natural_go'] for g in games),natural_games_per_hour=None,cpu_percent_mean=sum(s['cpu'] for s in samples if s['cpu'] is not None)/max(1,sum(s['cpu'] is not None for s in samples)),peak_private_bytes=max((s['private'] for s in samples),default=0),peak_working_set_bytes=max((s['working_set'] for s in samples),default=0),unexpected_incomplete=sum(not g['reason'] or not g['conserved'] for g in games),note='Step-capped games are not natural-GO. Global CPU includes supervisor/OS. Fixed256/depth4, early24 drops only, not all weighted collection profiles.')

def main():
    base=ROOT/'concurrency';base.mkdir(exist_ok=False);plan=json.loads((ROOT/'plan.json').read_text());overall=time.monotonic();results={}
    for workers in [2,4]:
        existing=active_players()
        if existing:
            write(base/f'blocked_{workers}.json',dict(existing_pids=existing,reason='Do not interfere with active collection'));break
        if time.monotonic()-overall>=plan['benchmark']['budget_seconds']:break
        folder=base/f'workers_{workers}';folder.mkdir();indices=[[0,1,2,3]] if workers==2 else [[0,1],[2,3]];children=[]
        for i,ids in enumerate(indices):children.append(subprocess.Popen([sys.executable,__file__,'group','--output',str(folder/f'group_{i}'),'--indices',*map(str,ids)],stdout=(folder/f'group_{i}.log').open('w'),stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        start=time.monotonic();last=cpu_times();samples=[];owned=set()
        while any(p.poll() is None for p in children):
            time.sleep(1);now=cpu_times();cpu=None
            if now and last and now[1]>last[1]:cpu=100*(1-(now[0]-last[0])/(now[1]-last[1]))
            last=now
            for p in folder.rglob('run.json'):
                try:owned.update(w['pid'] for w in json.loads(p.read_text())['workers'])
                except (ValueError,KeyError):pass
            memory=[m for pid in owned if (m:=process_memory(pid))];samples.append(dict(seconds=time.monotonic()-start,cpu=cpu,private=sum(m['private_bytes'] for m in memory),working_set=sum(m['working_set_bytes'] for m in memory)))
            if time.monotonic()-start>plan['benchmark']['phase_cap_seconds']:
                # Only exact PIDs launched by these new manifests; no existing run is touched.
                for pid in owned:
                    try:os.kill(pid,15)
                    except OSError:pass
                for p in children:
                    if p.poll() is None:p.terminate()
                write(folder/'timeout.json',dict(reason='Own phase deadline; no natural-GO labels'));break
        seconds=time.monotonic()-start;write(folder/'samples.json',samples)
        try:result=summarize(folder,seconds,samples)
        except Exception as e:result=dict(error=str(e),seconds=seconds)
        result['supervisor_exits']=[p.poll() for p in children];write(folder/'result.json',result);results[str(workers)]=result
    write(base/'summary.json',results)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','group']);p.add_argument('--output',type=Path);p.add_argument('--indices',type=int,nargs='+');a=p.parse_args();group(a.output,a.indices) if a.mode=='group' else main()
