"""Summarize a new diagnose_runtime directory; no game execution or source changes."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnose_runtime import distribution

def analyze(directory):
 result={}
 for d in sorted(Path(directory).iterdir()):
  if not (d/'results.json').exists():continue
  recorded=json.loads((d/'results.json').read_text());all_plans=[];windows=[]
  by_stage={'early':[],'dense':[]}
  for w in recorded['workers']:
   rows=[json.loads(l) for l in (d/(w['game_id']+'_runtime.jsonl')).open(encoding='utf-8')]
   plans=[r for r in rows if r['evt']=='plan'];all_plans+=plans;windows += [r for r in rows if r['evt']=='window']
   # Every performance worker executes early then dense, without a sweep in final run.
   for stage in by_stage:by_stage[stage]+=[r['info']['planning']['elapsed_ms'] for r in w['rows'] if r['stage']==stage and r['info'].get('planning')]
  resources=json.loads((d/'resources.json').read_text());cpu=0;peak_memory=0
  for pid in resources[-1]['processes']:
   points=[(r['wall'],r['processes'][pid]) for r in resources if r['processes'].get(pid)]
   if len(points)>1:cpu+=(points[-1][1]['cpu_seconds']-points[0][1]['cpu_seconds'])/(points[-1][0]-points[0][0])
  for row in resources:peak_memory=max(peak_memory,sum(v['working_set'] for v in row['processes'].values() if v))
  value=dict(mode=recorded['mode'],games=recorded['games'],video=recorded['video'],stages={k:distribution(v) for k,v in by_stage.items()},
   main_thread_block_ms=distribution([p['elapsed_ms'] for p in all_plans]),
   all_plan_fixed_frame_udp_video_deltas_zero=all(p['fixed_delta']==p['frame_delta']==p['packet_delta']==p['video_delta']==0 for p in all_plans),
   unity_update_gaps_ms=distribution([x for w in windows for x in w['update_gaps_ms']]),unity_fixed_wall_gaps_ms=distribution([x for w in windows for x in w['fixed_gaps_ms']]),
   capture_ms=distribution([x for w in windows for x in w['capture_ms']]),readback_callback_ms=distribution([x for w in windows for x in w['readback_callback_ms']]),publish_ms=distribution([x for w in windows for x in w['publish_ms']]),
   gc_collections_in_plans=sum(p['gc0'] for p in all_plans),owned_cpu_core_equivalents=cpu,owned_cpu_percent_total_logical=100*cpu/os.cpu_count(),sampled_peak_working_set_mib=peak_memory/2**20,
   plan_unity_allocation_delta_mib=distribution([p['unity_delta']/2**20 for p in all_plans]))
  if (d/'viewer.json').exists():value['viewer']=json.loads((d/'viewer.json').read_text())
  result[d.name]=value
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=analyze(a.input)
 with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
 for key,r in result.items():print(key,json.dumps({k:r[k] for k in ('stages','owned_cpu_percent_total_logical','sampled_peak_working_set_mib')}))
if __name__=='__main__':main()
