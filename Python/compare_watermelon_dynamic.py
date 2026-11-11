"""Predeclared paired actual-game continuations from approximate watermelon roots."""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from watermelon_lab import ROOT, sha, write, summarize


def active_players():
    command="Get-CimInstance Win32_Process | Where-Object Name -eq 'SuikaGameAI.exe' | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    r=subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip()
    return json.loads(r) if r else []


def run_game(root,fixture,mode,future,exe,seconds,drops=1000):
    from suika_ai.parallel_play import check_ports,worker_specs
    if active_players():raise RuntimeError('External Player active; do not interfere')
    check_ports(worker_specs(1,42930));root.mkdir(parents=True,exist_ok=False)
    cfg=dict(fixture=str(fixture),output=str((root/'trace.jsonl').resolve()),mode=mode,future_seed=future,search_seed=8191,iterations=128,depth=4,max_drops=drops,max_seconds=seconds,first_x=-1)
    write(root/'config.json',cfg)
    args=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(future),'--suika-listen-port','42930','--suika-python-port','42931',
          '-suikaRuntimeProbe',str((root/'runtime.jsonl').resolve()),'-suikaWatermelonDynamicLab',str((root/'config.json').resolve()),'-logFile',str((root/'player.log').resolve())]
    write(root/'launch.json',dict(command=args,exe_sha256=sha(exe),assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'),fixture_sha256=sha(fixture)))
    child=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS);start=time.monotonic();failure=None
    try:
        while child.poll() is None:
            if time.monotonic()-start>seconds+35:failure='process_timeout';break
            log=root/'player.log'
            if log.exists() and any(t in log.read_text(encoding='utf8',errors='replace') for t in ['NullReferenceException:','ArgumentException:','InvalidOperationException:']):failure='player_exception';break
            time.sleep(.5)
    except KeyboardInterrupt:failure='interrupted'
    finally:
        if child.poll() is None:child.terminate();child.wait(10)
    rows=[]
    if (root/'trace.jsonl').exists():
        for line in (root/'trace.jsonl').read_text(encoding='utf-8-sig').splitlines():
            try:rows.append(json.loads(line))
            except json.JSONDecodeError:failure=failure or 'incomplete_trace'
    r=summarize(rows);r.update(exit_code=child.returncode,process_error=failure,wall_seconds=time.monotonic()-start,mode=mode,future=future)
    if r['end'] is None:r['process_error']=r['process_error'] or 'missing_end'
    if child.returncode or r['process_error']:r['natural_go']=False
    write(root/'result.json',r)
    print(json.dumps(dict(event='game_end',folder=str(root),mode=mode,future=future,natural_go=r['natural_go'],score=r['end']['additional_score'] if r['end'] else None,drops=r['end']['accepted_drops'] if r['end'] else None,seconds=r['wall_seconds'],error=r['process_error'])),flush=True)
    return r


def sequence(plan):
    # Rotate roots within each future block; alternate condition order.
    jobs=[]
    for j,future in enumerate(plan['future_seeds']):
        for k in range(3):
            i=(k+j)%3
            modes=['baseline','refined'] if (j*3+k)%2==0 else ['refined','baseline']
            jobs.append(dict(root=i,future=future,modes=modes))
    return jobs


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=ROOT/'Unity/Builds/WatermelonDynamic_02/SuikaGameAI.exe');p.add_argument('--smoke',action='store_true');a=p.parse_args()
    root=a.output;plan=json.loads((root/'plan.json').read_text());exe=a.exe.resolve()
    for fixture,h in plan['fixture_hashes'].items():
        if sha(fixture)!=h:raise RuntimeError('Frozen fixture changed')
    if a.smoke:
        run_game(root/'smoke_refined',Path(plan['roots'][0]),'refined',plan['future_seeds'][0],exe,45,3);return
    if (root/'execution_start.json').exists():raise FileExistsError('Study already started; do not repeat silently')
    pilot=json.loads((root/'pilot_baseline/result.json').read_text());smoke=json.loads((root/'smoke_refined/result.json').read_text());spent_pilot=pilot['wall_seconds']+smoke['wall_seconds']
    if smoke['exit_code'] or smoke['process_error'] or not smoke['end']:raise RuntimeError('Smoke failed; do not start study')
    write(root/'execution_start.json',dict(pilot_seconds=pilot['wall_seconds'],smoke_seconds=smoke['wall_seconds'],pilot_natural_go=pilot['natural_go'],total_game_budget_seconds=plan['total_game_budget_seconds'],jobs=sequence(plan),exe_sha256=sha(exe),plan_sha256=sha(root/'plan.json')))
    start=time.monotonic();durations=[spent_pilot];games=0;stop=None
    try:
        for j in sequence(plan):
            remaining=plan['total_game_budget_seconds']-spent_pilot-(time.monotonic()-start)
            expected_pair=2*max(durations[-4:])*1.15+10
            if remaining<expected_pair:stop='remaining_budget_insufficient_for_expected_pair';break
            for k,mode in enumerate(j['modes']):
                remaining=plan['total_game_budget_seconds']-spent_pilot-(time.monotonic()-start)
                seconds=min(plan['per_game_seconds'],max(1,remaining-35))
                folder=root/f"root{j['root']}_f{j['future']}"/mode
                print(json.dumps(dict(event='game_start',game=games+1,root=j['root'],future=j['future'],mode=mode,remaining_seconds=remaining,max_seconds=seconds)),flush=True)
                r=run_game(folder,Path(plan['roots'][j['root']]),mode,j['future'],exe,seconds)
                durations.append(r['wall_seconds']);games+=1
                with (root/'progress.jsonl').open('a') as f:f.write(json.dumps(dict(root=j['root'],future=j['future'],mode=mode,natural_go=r['natural_go'],error=r['process_error']))+'\n')
                if r['process_error'] or r['exit_code'] or r['errors']:raise RuntimeError('Technical failure; stop without seed replacement')
    except KeyboardInterrupt:stop='user_interrupt'
    except Exception as e:stop=str(e)
    write(root/'execution_end.json',dict(games=games,reason=stop or 'planned_games_complete',elapsed_seconds=time.monotonic()-start,pilot_seconds=spent_pilot))


if __name__=='__main__':main()
