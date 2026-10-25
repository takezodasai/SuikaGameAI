"""Opt-in bounded STEP8-C diagnostics. Never performs a full game collection."""
import argparse,ctypes,concurrent.futures,json,os,statistics,subprocess,sys,threading,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import UnityEnv
from suika_ai.parallel_play import player_command,worker_specs
from suika_ai import video_viewer

class FileTime(ctypes.Structure):_fields_=[('low',ctypes.c_ulong),('high',ctypes.c_ulong)]
class Memory(ctypes.Structure):_fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
K=ctypes.windll.kernel32;K.OpenProcess.restype=ctypes.c_void_p;K.GetProcessTimes.argtypes=[ctypes.c_void_p]+[ctypes.POINTER(FileTime)]*4;K.CloseHandle.argtypes=[ctypes.c_void_p]
P=ctypes.windll.psapi;P.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Memory),ctypes.c_ulong]
def ft(x):return ((x.high<<32)+x.low)/1e7
def sample(pid):
 h=K.OpenProcess(0x1000|0x10,False,pid)
 if not h:return None
 try:
  a,b,c,d=FileTime(),FileTime(),FileTime(),FileTime();m=Memory();m.cb=ctypes.sizeof(m)
  if not K.GetProcessTimes(h,ctypes.byref(a),ctypes.byref(b),ctypes.byref(c),ctypes.byref(d)):return None
  P.GetProcessMemoryInfo(h,ctypes.byref(m),m.cb);return dict(cpu_seconds=ft(c)+ft(d),working_set=m.ws,peak_working_set=m.peak_ws)
 finally:K.CloseHandle(h)
def distribution(xs):
 xs=sorted(xs)
 return dict(n=len(xs),p50=statistics.median(xs),p95=xs[min(len(xs)-1,int(len(xs)*.95))],maximum=max(xs),mean=statistics.mean(xs)) if xs else None

def restore(env):
 before=env.receive_state(5);req=uuid.uuid4().hex;command=dict(command='probe_fixture',stream_id=before['stream_id'],episode_id=before['episode_id'],request_id=req)
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  env._send(command)
  try:s=env.receive_state(.5)
  except TimeoutError:continue
  if s['reset_request_id']==req:
   # Private diagnostic client: adopt the new episode just as reset() does.
   env._action_episode=s['episode_id'];env._action_id=0;env._pending_step=None
   return s
 raise TimeoutError('Fixture acknowledgement absent')

def run_condition(output,fixture,mode,games,video,port,samples,sweep=False,baseline=False):
 output.mkdir(exist_ok=False);specs=worker_specs(games,port,744100);maps={s.game_id:'Local\\Suika8c_'+uuid.uuid4().hex for s in specs} if video else {}
 children=[];envs=[];viewer=None;memory=[];stop=threading.Event();results=[]
 settings=dict(ai_mode=mode,candidate_count=5,mcts_iterations=32,mcts_max_depth=4,post_drop_steps=25)
 try:
  for spec in specs:
   envs.append(UnityEnv(server=('127.0.0.1',spec.listen_port),local=('127.0.0.1',spec.python_port),expected_game_id=spec.game_id))
   command=player_command(Path('../Unity/Builds/Step6/SuikaGameAI.exe').resolve(),spec,(output/(spec.game_id+'_player.log')).resolve(),not video,audio=False,video_map=maps.get(spec.game_id))
   command+=['-suikaRuntimeProbe',str((output/(spec.game_id+'_runtime.jsonl')).resolve()),'-suikaProbeFixture',str(fixture.resolve())]
   if baseline:command+=['-suikaMctsBaseline']
   children.append(subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW))
  manifest=dict(video_maps=maps,workers=[dict(game_id=s.game_id,pid=p.pid) for s,p in zip(specs,children)])
  (output/'run.json').write_text(json.dumps(manifest))
  if video:
   viewer=subprocess.Popen([sys.executable,'-m','suika_ai.video_viewer','--run',str(output.resolve()),'--metrics',str((output/'viewer.json').resolve()),'--metrics-interval','1','--seconds','45'],env=dict(os.environ,PYTHONPATH=str(Path('src').resolve())),stdout=(output/'viewer_stdout.log').open('w'),stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  def monitor():
   while not stop.wait(.2):
    memory.append(dict(wall=time.monotonic(),processes={str(p.pid):sample(p.pid) for p in children+([viewer] if viewer else [])}))
  t=threading.Thread(target=monitor);t.start();barrier=threading.Barrier(games)
  def worker(spec,env):
   deadline=time.monotonic()+30
   while True:
    try:env.receive_state(1);break
    except (TimeoutError,ConnectionResetError):
     if time.monotonic()>deadline:raise
   env.reset();env.get_environment();barrier.wait(timeout=30);rows=[]
   for stage in ('early','dense'):
    for i in range(samples):
     if stage=='dense':restore(env)
     elif i==0:env.reset()
     start=time.monotonic();state,reward,done,info=env.plan_step(settings,timeout=30)
     rows.append(dict(stage=stage,trial=i,wall_seconds=time.monotonic()-start,done=done,score=state['score'],reward=reward,info=info))
     if done and stage=='early':break
   if sweep and spec.game_id=='game_00':
    restore(env);s=env.receive_state(2);env._send(dict(command='probe_sweep',stream_id=s['stream_id'],episode_id=s['episode_id'],request_id=uuid.uuid4().hex))
    time.sleep(.1)
    deadline=time.monotonic()+40
    log=output/(spec.game_id+'_runtime.jsonl')
    while 'sweep_complete' not in log.read_text(encoding='utf-8'):
     if time.monotonic()>deadline:raise TimeoutError('Sweep did not finish')
     time.sleep(.2)
   return dict(game_id=spec.game_id,rows=rows)
  with concurrent.futures.ThreadPoolExecutor(max_workers=games) as pool:
   fs=[pool.submit(worker,s,e) for s,e in zip(specs,envs)]
   for future in fs:results.append(future.result())
  time.sleep(1.2)
 finally:
  stop.set()
  if 't' in locals():t.join(2)
  for env in envs:env.close()
  for child in children+([viewer] if viewer else []):
   if child.poll() is None:child.terminate();child.wait(timeout=5)
 with (output/'results.json').open('x') as f:json.dump(dict(mode=mode,games=games,video=video,workers=results),f,indent=2)
 with (output/'resources.json').open('x') as f:json.dump(memory,f)
 print(json.dumps(dict(condition=output.name,mode=mode,games=games,video=video,decisions=sum(len(w['rows']) for w in results))),flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--samples',type=int,default=3);p.add_argument('--condition',choices=('h1v','h4v','m1v','m4v','m4h'),nargs='+',default=['h1v','h4v','m1v','m4v','m4h']);p.add_argument('--sweep',action='store_true');p.add_argument('--baseline',action='store_true',help='Diagnostic STEP8-D old readback/GO path');a=p.parse_args()
 if not 1<=a.samples<=5:p.error('Diagnostic samples must be 1..5')
 a.output.mkdir(exist_ok=False,parents=True)
 cases={'h1v':('heuristic',1,True),'h4v':('heuristic',4,True),'m1v':('mcts',1,True),'m4v':('mcts',4,True),'m4h':('mcts',4,False)}
 for i,key in enumerate(a.condition):run_condition(a.output/key,a.fixture,*cases[key],28000+i*20,a.samples,a.sweep and key=='m1v',a.baseline)
if __name__=='__main__':main()
