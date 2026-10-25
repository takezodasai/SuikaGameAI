"""Bounded fixed-board timing/reproducibility measurements; no live-game collection."""
import argparse,ctypes,json,statistics,subprocess,time
from pathlib import Path
from compare_mcts_budget import sha,save,read,settings
from analyze_two_step_probe import trace_search

def rss(pid):
    # Standard Windows API; no optional monitoring dependency.
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['peak','working','qpp','pp','qpnp','pnp','pagefile','peakpagefile']]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=wintypes.HANDLE;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    h=kernel.OpenProcess(0x410,False,pid)
    if not h:return 0
    try:
        c=Counters();c.cb=ctypes.sizeof(c);fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo;fn.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        return c.working if fn(h,ctypes.byref(c),c.cb) else 0
    finally:kernel.CloseHandle(h)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'));p.add_argument('--repeats',type=int,default=3);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    if not 2<=a.repeats<=5:p.error('Use 2..5 short repeats')
    root=Path(__file__).resolve().parents[1];b=a.output.resolve();
    if not a.analyze_only:b.mkdir(parents=True,exist_ok=False)
    exe=a.exe.resolve();script=root/'Unity/Assets/Scenes/Script'
    protected=read(b/'source_hashes_before.json') if a.analyze_only else {str(p):sha(p) for p in script.glob('*.cs')}
    if not a.analyze_only:save(b/'source_hashes_before.json',protected)
    fixtures=[root/'Python/outputs/step8i_01/early_fixture.json',root/'Python/outputs/step8i_01/mid_fixture.json',root/'Python/outputs/step8c_01/dense_safe_fixture.json'];allrows=[];runtime=[]
    orders=[[32,64,128,256],[256,128,64,32],[64,128,256,32]]
    for repeat in range(a.repeats):
        config=b/f'config_{repeat}.json';out=b/f'fixed_{repeat}.jsonl';log=b/f'player_{repeat}.log'
        if not a.analyze_only:
            save(config,dict(output=str(out),fixtures=[str(p) for p in fixtures],searches=[dict(policy='grid',candidates=5,iterations=n,seed=8191,common_chance=False) for n in orders[repeat%3]],scan=False,exhaustive=False,information_tests=False))
            child=subprocess.Popen([str(exe),'-batchmode','-nographics','--suika-game-id','game_00','-suikaRuntimeProbe',str(b/f'runtime_{repeat}.jsonl'),'-suikaCandidateProbe',str(config),'-logFile',str(log)],creationflags=subprocess.CREATE_NO_WINDOW)
            start=time.monotonic();peak=0
            try:
                while child.poll() is None:
                    if time.monotonic()-start>100:raise TimeoutError('Fixed-board process exceeded 100 seconds')
                    peak=max(peak,rss(child.pid));time.sleep(.05)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=10)
            if child.returncode:raise RuntimeError('Fixed-board Player failed')
            runtime.append(dict(repeat=repeat,wall_seconds=time.monotonic()-start,process_peak_rss=peak))
            save(b/f'process_{repeat}.json',runtime[-1])
        else:runtime.append(read(b/f'process_{repeat}.json'));peak=runtime[-1]['process_peak_rss']
        for line in out.read_text(encoding='utf-8-sig').splitlines():
            r=json.loads(line)
            if r.get('error') or not r['root_unchanged']:raise ValueError('Failed or mutated fixed board')
            m=r['report'];s=r['decision']['settings'];n=s['mcts_iterations']
            if m['completed_iterations']!=n or sum(z['visits'] for z in m['nodes'][0]['actions'])!=n:raise ValueError('Search count mismatch')
            trace_search(dict(decision=r['decision'],report=m));r['repeat']=repeat;allrows.append(r)
        print(json.dumps(dict(repeat=repeat,rows=len(allrows),peak_rss=peak)),flush=True)
    summary=[]
    def signature(r):return [dict((k,v) for k,v in i.items() if k!='elapsed_ms') for i in r['report']['iterations']]
    for fixture in fixtures:
        for n in [32,64,128,256]:
            rs=[r for r in allrows if r['fixture']==str(fixture) and r['decision']['settings']['mcts_iterations']==n]
            if len(rs)!=a.repeats or any(signature(r)!=signature(rs[0]) or r['report']['nodes']!=rs[0]['report']['nodes'] for r in rs):raise ValueError('Repeated fixed search differs')
            r=rs[0];m=r['report'];s=dict(fixture=fixture.stem,iterations=n,mean_ms=statistics.mean(z['wall_ms'] for z in rs),sd_ms=statistics.stdev(z['wall_ms'] for z in rs),min_ms=min(z['wall_ms'] for z in rs),max_ms=max(z['wall_ms'] for z in rs),physical_ticks=m['total_physics_ticks'],selected_x=r['decision']['selected_x'],root_visits=[z['visits'] for z in m['nodes'][0]['actions']],unique_full_sequences=len({tuple(i['actions']) for i in m['iterations']}),unique_two_sequences=len({tuple(i['actions'][:2]) for i in m['iterations'] if len(i['actions'])>=2}),depth4=sum(i['depth']==4 for i in m['iterations']),go_samples=sum(i['game_over'] for i in m['iterations']),unity_sampled_peak_range=[min(z['report']['unity_allocated_sampled_peak_bytes'] for z in rs),max(z['report']['unity_allocated_sampled_peak_bytes'] for z in rs)],gc0=[z['gc0'] for z in rs]);summary.append(s);print(json.dumps(s),flush=True)
    old=[json.loads(l) for l in (root/'Python/outputs/step8r_01/control.jsonl').read_text(encoding='utf-8-sig').splitlines()];checks=[]
    for r in allrows:
        if r['decision']['settings']['mcts_iterations']!=32:continue
        o=next(o for o in old if o['fixture']==r['fixture'] and not o['decision']['settings']['mcts_common_chance'])
        if signature(r)!=signature(o) or r['report']['nodes']!=o['report']['nodes']:raise ValueError('Previous 32-iteration result changed')
        checks.append(dict(fixture=r['fixture'],repeat=r['repeat'],equal=True))
    if any(sha(p)!=h for p,h in protected.items()):raise ValueError('Unity source changed')
    save(b/'summary.json',dict(measurements=summary,runtime=runtime,compatibility=checks,source_unchanged=True,note='Same search seed repeated, not independent strength samples; rotated order; sampled RSS is whole process, Unity peak includes deferred destruction.'))
if __name__=='__main__':main()
