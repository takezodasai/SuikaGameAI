"""Bounded presentation smoke/performance check; creates new outputs, never reuses ports/logs."""
import argparse,ctypes,json,subprocess,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from suika_ai.parallel_play import run_parallel,validate_run
from suika_ai.presentation import write_control
from ctypes import wintypes

class Memory(ctypes.Structure):
 _fields_=[("cb",wintypes.DWORD),("faults",wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('peak_ws','ws','peak_pool','pool','peak_nonpool','nonpool','page','peak_page')]
kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(ctypes.c_ulonglong)]*4
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
def resources(pid):
 handle=kernel.OpenProcess(0x1000|0x10,False,pid)
 if not handle:return None
 try:
  a,b,c,d=(ctypes.c_ulonglong() for _ in range(4));mem=Memory();mem.cb=ctypes.sizeof(mem)
  if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in (a,b,c,d)]):return None
  psapi.GetProcessMemoryInfo(handle,ctypes.byref(mem),mem.cb)
  return ((c.value+d.value)/1e7,mem.ws/1024**2)
 finally:kernel.CloseHandle(handle)

def benchmark(exe,out,port,headless,video,steps=8,controls=False):
 out=Path(out);done=threading.Event();record=[];viewer_record=[];viewer=None;sent=set();viewer_after=None
 def monitor():
  nonlocal viewer,viewer_after
  while not done.wait(.1):
   try:manifest=json.loads((out/'run.json').read_text())
   except (FileNotFoundError,json.JSONDecodeError):continue
   pid=manifest['workers'][0]['pid'];r=resources(pid)
   if r:record.append((time.monotonic(),*r))
   if video and viewer is None:
    viewer=subprocess.Popen([sys.executable,'-m','suika_ai.video_viewer','--map',manifest['video_map'],
     '--seconds','6','--metrics',str((out/'viewer_metrics.json').resolve())],env=dict(__import__('os').environ,PYTHONPATH=str(Path('src').resolve())))
   if viewer:
    vr=resources(viewer.pid)
    if vr:viewer_record.append((time.monotonic(),*vr))
   if viewer and viewer.poll() is not None and viewer_after is None:viewer_after=time.monotonic()
   if controls:
    try:rows=[json.loads(x) for x in (out/'game_00.jsonl').read_text().splitlines()]
    except (FileNotFoundError,json.JSONDecodeError):continue
    n=sum(x.get('event')=='transition' for x in rows)
    for turn,kind,enabled in [(2,'audio',False),(4,'video',False),(7,'audio',True),(9,'video',True)]:
     if n>=turn and turn not in sent:
      write_control(out,['game_00'],**{kind:enabled});sent.add(turn)
 thread=threading.Thread(target=monitor);thread.start()
 try:summary=run_parallel(exe,out,1,1,steps,port,12345,headless,{},0 if video else None,launch_viewer=False)
 finally:done.set();thread.join()
 if viewer:viewer.wait(timeout=10)
 rows=[json.loads(x) for x in (out/'game_00.jsonl').read_text().splitlines()]
 states=[x['state'] for x in rows if 'state' in x]
 elapsed=record[-1][0]-record[0][0] if len(record)>1 else 0
 perf=dict(samples=len(record),player_cpu_one_core_percent=100*(record[-1][1]-record[0][1])/elapsed if elapsed else None,
  player_peak_working_set_mb=max((r[2] for r in record),default=None),gpu_usage='not measured',
  viewer_cpu_one_core_percent=100*(viewer_record[-1][1]-viewer_record[0][1])/(viewer_record[-1][0]-viewer_record[0][0]) if len(viewer_record)>1 else None,
  viewer_peak_working_set_mb=max((r[2] for r in viewer_record),default=None),
  video_capture_ms=[s.get('video_capture_ms') for s in states],video_publish_ms=[s.get('video_publish_ms') for s in states],
  states=[{k:s.get(k) for k in ('state_id','score','audio_enabled','audio_revision','audio_played','audio_suppressed','video_enabled','video_revision','video_frames','video_readbacks','video_error','video_render_textures')} for s in states],
  transition_scores=[x['score'] for x in rows if x['event']=='transition'],
  actions=[x['selected_x'] for x in rows if x['event']=='transition'],integrity=validate_run(out),
  viewer_exited_before_game_finished=viewer_after is not None and viewer_after < time.monotonic()-1)
 (out/'presentation_test.json').write_text(json.dumps(perf,indent=2))
 return dict(output=str(out),**summary,**{k:perf[k] for k in ('player_cpu_one_core_percent','player_peak_working_set_mb','transition_scores','actions')})

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['old','new','visible','video','controls'],required=True);p.add_argument('--output',required=True);p.add_argument('--port',type=int,default=20400);p.add_argument('--baseline-exe',type=Path,help='Required for old mode: an existing pre-change build, not the rebuilt Player');a=p.parse_args()
 if a.mode=='old' and a.baseline_exe is None:p.error('old mode requires --baseline-exe; recorded baseline is in outputs/preview_perf_old_01')
 exe=a.baseline_exe if a.mode=='old' else Path('../Unity/Builds/Step6Preview/SuikaGameAI.exe')
 if a.mode=='old':
  import suika_ai.parallel_play as parallel
  original=parallel.player_command
  def old_command(*args,**kwargs):
   command=original(*args,**kwargs);i=command.index('--suika-audio');del command[i:i+2];return command
  parallel.player_command=old_command
 print(json.dumps(benchmark(exe,a.output,a.port,a.mode in ('old','new'),a.mode in ('video','controls'),14 if a.mode=='controls' else 8,a.mode=='controls')))
