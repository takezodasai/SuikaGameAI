"""Offline summary of bounded native A/B benchmarks (does not run games)."""
import argparse,json,os,statistics
from pathlib import Path
from collections import defaultdict

def distribution(values):
    a=sorted(values)
    return dict(n=len(a),mean=statistics.mean(a),median=statistics.median(a),p95=a[min(len(a)-1,int(len(a)*.95))],maximum=max(a)) if a else None

def summarize(directory):
    directory=Path(directory);groups=defaultdict(list);profiles=defaultdict(lambda:defaultdict(list));pairs=[];cleanup=[];sources=True;gc=defaultdict(list);cold=[]
    for f in sorted(directory.glob('game_*.jsonl')):
        with f.open(encoding='utf-8') as stream:
            for line in stream:
                r=json.loads(line)
                if r.get('evt')=='error':raise ValueError(r['error'])
                if r.get('evt')=='pair':
                    pairs.append(r)
                    if not r['equal']:raise ValueError('Search/physics mismatch')
                if r.get('variant')=='cleanup':cleanup.append(r);continue
                if r.get('variant') not in ('baseline','optimized'):continue
                sources &= r['source_unchanged'] and r['report']['source_unchanged'] and r['report']['prefixes_match']
                key=f"{Path(r['fixture']).stem}:{r['iterations']}:d{r['depth']}:{r['variant']}"
                if r['warmup']:cold.append(dict(key=key,ms=r['wall_ms']));continue
                groups[key].append(r['wall_ms']);gc[key].append(r['gc0'])
                for m in r['report'].get('profile') or []:profiles[key][m['name']].append(m)
    if not pairs or not groups:raise ValueError('No complete native benchmark pairs')
    if any(r['scenes_after']!=0 for r in cleanup):raise ValueError('Prediction scenes not released')
    if not sources:raise ValueError('Live source or replay guard failed')
    totals={k:distribution(v) for k,v in groups.items()}
    improvements={}
    for key in groups:
        if key.endswith(':baseline'):
            other=key.removesuffix(':baseline')+':optimized'
            improvements[key.removesuffix(':baseline')]=dict(baseline=totals[key],optimized=totals[other],speedup=totals[key]['median']/totals[other]['median'])
    profile={key:{name:dict(calls_mean=statistics.mean(m['calls'] for m in ms),inclusive_mean_ms=statistics.mean(m['inclusive_ms'] for m in ms),exclusive_mean_ms=statistics.mean(m['exclusive_ms'] for m in ms)) for name,ms in categories.items()} for key,categories in profiles.items()}
    resources=json.loads((directory/'resources.json').read_text());cpu=0;peak=0
    pids=set(pid for row in resources for pid in row['processes'])
    for pid in pids:
        xs=[(r['wall'],r['processes'][pid]) for r in resources if r['processes'].get(pid)]
        if len(xs)>1:cpu+=(xs[-1][1]['cpu_seconds']-xs[0][1]['cpu_seconds'])/(xs[-1][0]-xs[0][0])
    for r in resources:peak=max(peak,sum(v['working_set'] for v in r['processes'].values() if v))
    gpu=[]
    for r in json.loads((directory/'gpu.json').read_text()):
        if r.get('system_gpu'):
            try:gpu.append(float(r['system_gpu'].split(',')[0]))
            except ValueError:pass
    return dict(comparisons=improvements,profiles=profile,warmups=cold,equal_pairs=len(pairs),all_sources_unchanged=sources,
        scenes_all_released=all(r['scenes_after']==0 for r in cleanup),cleanup_window_ms=distribution([r['cleanup_window_ms'] for r in cleanup]),
        gc0={k:distribution(v) for k,v in gc.items()},owned_cpu_core_equivalents=cpu,owned_cpu_percent_total_logical=100*cpu/os.cpu_count(),sampled_peak_rss_mib=peak/2**20,
        system_gpu_percent=distribution(gpu),resource_scope='entire bounded run including warmup/initialization; GPU is system-wide, not per-player')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=summarize(a.input)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    for key,row in result['comparisons'].items():print(key,round(row['baseline']['median'],2),round(row['optimized']['median'],2),round(row['speedup'],3))
if __name__=='__main__':main()
