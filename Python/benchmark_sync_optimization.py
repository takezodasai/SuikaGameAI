"""Bounded exact-root cache A/B; never collects full games or changes live rules."""
import argparse,json,statistics,subprocess,time
from pathlib import Path

def run(exe,output,fixtures,specs,repeats=2,verify=True,profile=False):
 output=Path(output);output.mkdir(parents=True,exist_ok=False);cfg=output/'config.json';trace=output/'trace.jsonl'
 cfg.write_text(json.dumps(dict(output=str(trace.resolve()),fixtures=[str(Path(p).resolve()) for p in fixtures],specs=specs,repeats=repeats,verify=verify,profile=profile)))
 command=[str(Path(exe).resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-listen-port','41100','--suika-python-port','41101','-logFile',str((output/'player.log').resolve()),'-suikaRuntimeProbe',str((output/'runtime.jsonl').resolve()),'-suikaExactOptimization',str(cfg.resolve())]
 child=subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));start=time.monotonic()
 try:
  while child.poll() is None:
   if time.monotonic()-start>300:raise TimeoutError('Bounded diagnostic exceeded300seconds')
   time.sleep(.2)
  if child.returncode:raise RuntimeError('Native probe failed; see player.log and trace.jsonl')
 finally:
  if child.poll() is None:child.terminate();child.wait(timeout=10)
 rows=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()];pairs=[r for r in rows if r['evt']=='pair']
 if any(not r['equal'] for r in pairs):raise ValueError('Exact search mismatch')
 if any(not r['source_unchanged'] or r['lifetime']['retained_scenes']!=1 or r['lifetime']['pending_unloads']!=0 for r in rows if r['evt']=='search'):raise ValueError('Root mutation or unexpected prediction lifetime')
 result=[]
 for fixture in fixtures:
  for spec in specs:
   group=[r for r in rows if r['evt']=='search' and not r['warmup'] and r['fixture']==str(Path(fixture).resolve()) and r['iterations']==spec['iterations'] and r['depth']==spec['depth']]
   base=[r['elapsed_ms'] for r in group if not r['cache']];new=[r['elapsed_ms'] for r in group if r['cache']]
   if not base or len(base)!=len(new):raise ValueError('Missing measurements')
   a=statistics.median(base);b=statistics.median(new);result.append(dict(fixture=Path(fixture).name,**spec,samples=len(base),baseline_median_ms=a,optimized_median_ms=b,time_reduction_percent=(a-b)/a*100,baseline_min_ms=min(base),baseline_max_ms=max(base),optimized_min_ms=min(new),optimized_max_ms=max(new)))
 report=dict(exact_pairs=len(pairs),verify_full_leaf_states=verify,profile=profile,results=result)
 (output/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/SyncOptimized_03/SuikaGameAI.exe'));p.add_argument('--output',type=Path,required=True);p.add_argument('--fixtures',type=Path,nargs='+',required=True);p.add_argument('--specs',nargs='+',default=['32:4','128:4','32:16']);p.add_argument('--repeats',type=int,choices=[1,2,3,4,5],default=2);p.add_argument('--timing',action='store_true');p.add_argument('--profile',action='store_true');a=p.parse_args();specs=[dict(zip(['iterations','depth'],map(int,s.split(':')))) for s in a.specs]
 if len(a.fixtures)>4 or len(specs)>4 or any(not 32<=s['iterations']<=256 or not 2<=s['depth']<=16 for s in specs):p.error('Bounded diagnostic requires<=4fixtures/specs, iterations32..256/depth2..16')
 run(a.exe,a.output,a.fixtures,specs,a.repeats,not a.timing,a.profile)
if __name__=='__main__':main()
