"""Short 4-worker comparison: headless / one video / four videos. No game setting changes."""
import argparse,json,os,subprocess,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from benchmark_presentation import resources
from suika_ai.parallel_play import run_parallel,validate_run

def benchmark(output,views,port,steps=12,viewer_seconds=12):
 output=Path(output).resolve();done=threading.Event();samples={};viewer=None;exited_at=None;counts_at_exit={}
 def monitor():
  nonlocal viewer,exited_at
  while not done.wait(.1):
   try:manifest=json.loads((output/'run.json').read_text())
   except (FileNotFoundError,json.JSONDecodeError):continue
   for worker in manifest['workers']:
    value=resources(worker['pid'])
    if value:samples.setdefault(worker['game_id'],[]).append((time.perf_counter(),*value))
   if views and viewer is None:
    viewer=subprocess.Popen([sys.executable,'-m','suika_ai.video_viewer','--run',str(output),
      '--seconds',str(viewer_seconds),'--metrics',str(output/'viewer_metrics.json')],
      env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parent/'src')))
   if viewer:
    value=resources(viewer.pid)
    if value:samples.setdefault('viewer',[]).append((time.perf_counter(),*value))
    if viewer.poll() is not None and exited_at is None:
     exited_at=time.time()
     for worker in manifest['workers']:
      try:
       lines=(output/(worker['game_id']+'.jsonl')).read_text().splitlines()
       counts_at_exit[worker['game_id']]=sum(json.loads(line)['event']=='transition' for line in lines)
      except (FileNotFoundError,json.JSONDecodeError):counts_at_exit[worker['game_id']]=None
 thread=threading.Thread(target=monitor);thread.start()
 try:
  summary=run_parallel(Path(__file__).resolve().parents[1]/'Unity/Builds/Step6/SuikaGameAI.exe',output,
    games=4,episodes=1,max_steps=steps,base_port=port,seed=12345,headless=views==0,
    settings=dict(candidate_count=5,post_drop_steps=25),launch_viewer=False,view_games=views)
 finally:done.set();thread.join()
 if viewer:viewer.wait(timeout=max(20,viewer_seconds+2))
 usage={}
 for game,values in samples.items():
  elapsed=values[-1][0]-values[0][0]
  usage[game]=dict(cpu_one_core_percent=100*(values[-1][1]-values[0][1])/elapsed if elapsed else None,
    peak_working_set_mb=max(v[2] for v in values))
 transitions={};finals={};continued=[]
 for worker in json.loads((output/'run.json').read_text())['workers']:
  rows=[json.loads(line) for line in (output/(worker['game_id']+'.jsonl')).read_text().splitlines()]
  turns=[r for r in rows if r['event']=='transition']
  transitions[worker['game_id']]=[(r['selected_x'],r['score']) for r in turns]
  final=rows[-1]['state'];finals[worker['game_id']]={k:final.get(k) for k in ('audio_enabled','audio_played','audio_suppressed','video_enabled','video_frames','video_readbacks','video_render_textures','video_error')}
  before=counts_at_exit.get(worker['game_id'])
  if before is not None and len(turns)>before:continued.append(worker['game_id'])
 report=dict(summary=summary,resources=usage,integrity=validate_run(output),transitions=transitions,finals=finals,
    viewer_exit_unix=exited_at,steps_at_viewer_exit=counts_at_exit,games_with_steps_after_viewer_exit=continued,gpu_usage='not measured',note='CPU 100%=one core; sample window includes startup, peak sums are not simultaneous. Scene trajectories can diverge.')
 (output/'debug_viewer_test.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(dict(output=str(output),steps_per_second=summary['collection_steps_per_second'],resources=usage,integrity=report['integrity'],finals=finals)))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--views',type=int,choices=[0,1,4],required=True)
 p.add_argument('--port',type=int,default=22000);p.add_argument('--steps',type=int,default=12);p.add_argument('--viewer-seconds',type=float,default=12)
 a=p.parse_args();benchmark(a.output,a.views,a.port,a.steps,a.viewer_seconds)
