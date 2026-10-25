"""Read-only STEP8-F timing/validity summary. Refuses an existing output file."""
import argparse,json,statistics
from pathlib import Path

def distribution(values):
    values=sorted(values)
    return dict(n=len(values),mean=statistics.mean(values),p50=statistics.median(values),p95=values[min(len(values)-1,int(len(values)*.95))],maximum=max(values)) if values else None

def analyze(root):
    results=[]
    for folder in sorted(Path(root).iterdir()):
        if not (folder/'decisions.jsonl').is_file():continue
        runtime=[json.loads(l) for l in (folder/'runtime.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
        windows=[r for r in runtime if r.get('evt')=='window'];gaps={key:[] for key in ('update_gaps_ms','fixed_gaps_ms')}
        for window in windows:
            for key in gaps:
                end=window['wall']
                for value in reversed(window[key]):gaps[key].append((end,value));end-=value/1000
        resources=json.loads((folder/'resources.json').read_text());valid=[r for r in resources if r['process']]
        cpu=(valid[-1]['process']['cpu_seconds']-valid[0]['process']['cpu_seconds'])/(valid[-1]['wall']-valid[0]['wall']) if len(valid)>1 else None
        viewer=json.loads((folder/'viewer.json').read_text())['games']['game_00'] if (folder/'viewer.json').is_file() else {}
        decisions=[]
        for line in (folder/'decisions.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row.get('error'):
                decisions.append(dict(stage=row['stage'],error=row['error']));continue
            plan=row['info']['planning'];frame=plan.get('frame_search')
            d=dict(stage=row['stage'],wall_step_ms=row['wall_seconds']*1000,plan_report_ms=plan['elapsed_ms'],selected_x=plan['selected_x'],score_before=row['info']['score_before'],reward=row['reward'],score_after=row['state']['score'],reward_conserved=row['info']['reward_accounting']['conserved'])
            if frame:
                d.update({k:frame[k] for k in ('adopted','final_policy','reason','attempts','retries','fallbacks','work_ms','wall_ms','max_slice_ms','update_frames','video_frames','start_tick','scheduled_tick','commit_tick')})
                d['video_during_search_fps']=frame['video_frames']/(frame['wall_ms']/1000)
                d['errors']=[dict(rejection=a['rejection'],difference=a.get('difference')) for a in frame['history']]
                d['active_slice_ms']=distribution([v for v in frame['slice_ms'] if v>=.01])
                # Approximate endpoints reconstructed from each one-second probe window.
                # Include gaps overlapping commit, including a synchronous fallback.
                for key in gaps:d['during_search_'+key]=distribution([v for t,v in gaps[key] if t>=frame['start_wall'] and t-v/1000<=frame['commit_wall']])
            decisions.append(d)
        results.append(dict(condition=folder.name,cpu_core_equivalent=cpu,peak_RSS_MiB=max((r['process']['working_set'] for r in valid),default=0)/2**20,viewer_display_fps=viewer.get('active_display_fps'),viewer_p95_latency_ms=viewer.get('published_to_tk_submit_ms',{}).get('p95'),whole_update_ms=distribution([v for _,v in gaps['update_gaps_ms']]),whole_fixed_ms=distribution([v for _,v in gaps['fixed_gaps_ms']]),decisions=decisions))
    return dict(caution='Few fixed-fixture decisions, not a strength experiment; restored solver caches unavailable; CPU averaged over runs with different waiting durations; Tk submission is not photon presentation.',conditions=results)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.input)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    for r in result['conditions']:
        print(json.dumps(dict(condition=r['condition'],RSS_MiB=r['peak_RSS_MiB'],cpu_cores=r['cpu_core_equivalent'],viewer_fps=r['viewer_display_fps'],max_update_ms=r['whole_update_ms']['maximum'] if r['whole_update_ms'] else None,decisions=[{k:d.get(k) for k in ('stage','plan_report_ms','work_ms','wall_ms','adopted','attempts','fallbacks','reason','max_slice_ms')} for d in r['decisions']])))
if __name__=='__main__':main()
