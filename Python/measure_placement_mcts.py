"""Bounded STEP8-U fixed-board comparisons, no natural-GO collection."""
import argparse,json,subprocess,time,statistics
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from adaptive_profiles import profile,audit_decision
from compare_mcts_budget import save,read
from analyze_adaptive_probe import physics
from measure_mcts_budget import rss

def summarize(rows):
 out=[]
 for fixture in sorted({r['fixture'] for r in rows}):
  for name in ['legacy','grid9','widening','legacy32']:
   rs=[r for r in rows if r['fixture']==fixture and r['name']==name];r=rs[0];d=dict(r['decision'],mcts=r['report']);m=r['report'];audit_decision(d)
   for other in rs[1:]:
    if m['nodes']!=other['report']['nodes'] or [physics(i) for i in m['iterations']]!=[physics(i) for i in other['report']['iterations']] or d['selected_x']!=other['decision']['selected_x']:raise ValueError('Seed repeat differs')
   adds=m['candidate_additions'] or [];nodes={n['id']:n for n in m['nodes']};stats=[]
   for a in adds:
    n=nodes[a['node_id']];edge=next(e for e in n['actions'] if abs(e['x']-a['x'])<1e-7);stats.append(dict(**a,visits=edge['visits'],revisits=max(0,edge['visits']-1)))
   out.append(dict(fixture=Path(fixture).stem,name=name,selected_x=d['selected_x'],iterations=m['completed_iterations'],configured_depth=m['max_depth'],reached_depth=max(i['depth'] for i in m['iterations']),root_candidates=len(m['nodes'][0]['actions']),root_positions=[e['x'] for e in m['nodes'][0]['actions']],root_visits=[e['visits'] for e in m['nodes'][0]['actions']],root_means=[e['mean_points'] for e in m['nodes'][0]['actions']],nonroot_actions=sum(e['visits']>0 for n in m['nodes'][1:] for e in n['actions']),nonroot_edge_revisits=sum(max(0,e['visits']-1) for n in m['nodes'][1:] for e in n['actions']),nodes=m['decision_nodes'],go_samples=sum(i['game_over'] for i in m['iterations']),physics_ticks=m['total_physics_ticks'],mean_ms=statistics.mean(r['wall_ms'] for r in rs),sd_ms=statistics.stdev(r['wall_ms'] for r in rs),addition_visits=stats,reproducible=True,peak_sampled_unity_bytes=max(r['report']['unity_allocated_sampled_peak_bytes'] for r in rs)))
 return out

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step8U/SuikaGameAI.exe'));a=p.parse_args();dest=a.output.resolve();dest.mkdir(parents=True,exist_ok=False);base=Path(__file__).resolve().parent
 fixtures=[base/'outputs/step8i_01/early_fixture.json',base/'outputs/step8i_01/mid_fixture.json',base/'outputs/step8c_01/dense_safe_fixture.json'];rows=[];process=[]
 for repeat in range(2):
  searches=[dict(name=n,settings=profile(n,iterations=128)) for n in ['legacy','grid9','widening']]+[dict(name='legacy32',settings=profile('legacy'))]
  if repeat:searches.reverse()
  output=dest/f'fixed_{repeat}.jsonl';config=dest/f'config_{repeat}.json';save(config,dict(output=str(output),fixtures=[str(p) for p in fixtures],searches=searches))
  child=subprocess.Popen([str(a.exe.resolve()),'-batchmode','-nographics','--suika-game-id','game_00','-suikaRuntimeProbe',str(dest/f'runtime_{repeat}.jsonl'),'-suikaAdaptiveProbe',str(config),'-logFile',str(dest/f'player_{repeat}.log')],creationflags=subprocess.CREATE_NO_WINDOW);start=time.monotonic();peak=0
  try:
   while child.poll() is None:
    if time.monotonic()-start>100:raise TimeoutError('Fixed diagnostic exceeded 100 seconds')
    peak=max(peak,rss(child.pid));time.sleep(.1)
   if child.returncode:raise RuntimeError('Diagnostic Player failed')
  finally:
   if child.poll() is None:child.terminate();child.wait(timeout=10)
  process.append(dict(repeat=repeat,wall_seconds=time.monotonic()-start,peak_rss=peak));rows.extend(json.loads(line) for line in output.read_text(encoding='utf-8-sig').splitlines())
  print(json.dumps(process[-1]),flush=True)
 result=summarize(rows);save(dest/'analysis.json',dict(searches=result,process=process));print(json.dumps(result),flush=True)
if __name__=='__main__':main()
