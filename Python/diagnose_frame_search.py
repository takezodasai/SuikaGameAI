"""Bounded STEP8-F single-game sync/frames diagnostics; never full episodes."""
import argparse, json, os, subprocess, sys, threading, time, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import UnityEnv
from suika_ai.parallel_play import player_command,worker_specs
from diagnose_runtime import restore,sample

def run(output,fixture,execution,depth,video,port,stages,tick_slicing=False):
    output.mkdir(parents=True,exist_ok=False)
    spec=worker_specs(1,port,749100)[0]
    env=UnityEnv(server=('127.0.0.1',spec.listen_port),local=('127.0.0.1',spec.python_port),expected_game_id=spec.game_id)
    mapping='Local\\Suika8f_'+uuid.uuid4().hex if video else None
    command=player_command(Path('../Unity/Builds/Step6/SuikaGameAI.exe').resolve(),spec,output/'player.log',not video,audio=False,video_map=mapping)
    command+=['-suikaRuntimeProbe',str(output/'runtime.jsonl'),'-suikaProbeFixture',str(fixture.resolve())]
    child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW)
    viewer=None;stop=threading.Event();resources=[];rows=[]
    def monitor():
        while not stop.wait(.1):resources.append(dict(wall=time.monotonic(),process=sample(child.pid)))
    thread=threading.Thread(target=monitor);thread.start()
    try:
        deadline=time.monotonic()+30
        while True:
            try:env.receive_state(1);break
            except (TimeoutError,ConnectionResetError):
                if time.monotonic()>deadline:raise
        env.reset();environment=env.get_environment()
        (output/'environment.json').write_text(json.dumps(environment),encoding='utf-8')
        if video:
            (output/'run.json').write_text(json.dumps(dict(video_maps={spec.game_id:mapping},workers=[dict(game_id=spec.game_id,pid=child.pid)])),encoding='utf-8')
            viewer=subprocess.Popen([sys.executable,'-m','suika_ai.video_viewer','--run',str(output),'--metrics',str(output/'viewer.json'),'--metrics-interval','1'],env=dict(os.environ,PYTHONPATH=str(Path('src').resolve())),creationflags=subprocess.CREATE_NO_WINDOW,stdout=(output/'viewer.log').open('w'),stderr=subprocess.STDOUT)
        for stage in stages:
            before=restore(env) if stage=='dense' else env.receive_state(3) if stage=='play' else env.reset()
            start=time.monotonic()
            try:
                state,reward,done,info=env.plan_step(dict(ai_mode='mcts',execution_mode=execution,mcts_iterations=32,mcts_max_depth=depth,frame_tick_slicing=tick_slicing),timeout=32)
                row=dict(stage=stage,execution=execution,depth=depth,before=before,state=state,reward=reward,done=done,info=info,wall_seconds=time.monotonic()-start)
            except Exception as e:row=dict(stage=stage,error=repr(e),wall_seconds=time.monotonic()-start)
            rows.append(row)
            with (output/'decisions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
            report=row.get('info',{}).get('planning',{}).get('frame_search')
            compact={k:report.get(k) for k in ('adopted','final_policy','reason','attempts','retries','fallbacks','wall_ms','work_ms','max_slice_ms','update_frames','video_frames')} if report else None
            print(json.dumps(dict(output=str(output),stage=stage,error=row.get('error'),frame_search=compact)),flush=True)
            if 'error' in row:break
        time.sleep(1.1)
    finally:
        stop.set();thread.join(2);env.close()
        for process in (viewer,child):
            if process is not None and process.poll() is None:process.terminate();process.wait(timeout=5)
        (output/'resources.json').write_text(json.dumps(resources),encoding='utf-8')
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--execution',choices=('sync','frames','frames_adaptive'),nargs='+',default=['sync','frames']);p.add_argument('--depth',type=int,nargs='+',default=[3,4]);p.add_argument('--video',action='store_true');p.add_argument('--stages',nargs='+',choices=('early','dense','play'),default=['early','dense']);p.add_argument('--base-port',type=int,default=34200)
    p.add_argument('--frame-tick-slicing',action='store_true')
    a=p.parse_args()
    if any(d not in (3,4,5,6) for d in a.depth):p.error('Use a bounded depth 3..6')
    a.output.mkdir(parents=True,exist_ok=False);index=0
    for execution in a.execution:
        for depth in a.depth:
            run((a.output/f'{execution}_d{depth}').resolve(),a.fixture,execution,depth,a.video,a.base_port+index*4,a.stages,a.frame_tick_slicing);index+=1
if __name__=='__main__':main()
