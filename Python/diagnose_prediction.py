"""Short reconstructed-layout GO diagnostics. No claim to restore native contact caches."""
import argparse,json,subprocess,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from diagnose_runtime import restore
from suika_ai.unity_env import UnityEnv
from suika_ai.parallel_play import player_command,worker_specs

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',type=Path,nargs='+',required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);rows=[]
 for i,fixture in enumerate(a.fixture):
  directory=a.output/fixture.stem;directory.mkdir();spec=worker_specs(1,29400+10*i,744300)[0]
  with UnityEnv(server=('127.0.0.1',spec.listen_port),local=('127.0.0.1',spec.python_port),expected_game_id=spec.game_id) as env:
   command=player_command(Path('../Unity/Builds/Step6/SuikaGameAI.exe').resolve(),spec,(directory/'player.log').resolve(),True)+['-suikaRuntimeProbe',str((directory/'runtime.jsonl').resolve()),'-suikaProbeFixture',str(fixture.resolve())]
   child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW)
   result=dict(fixture=str(fixture),limitation='Recorded kinematics restored into new real scene; native cache/RNG history unavailable')
   try:
    deadline=time.monotonic()+25
    while True:
     try:env.receive_state(1);break
     except (TimeoutError,ConnectionResetError):
      if time.monotonic()>deadline:raise
    env.reset();env.get_environment();loaded=restore(env);result['loaded']=loaded
    x=json.loads(fixture.read_text()).get('x',.25)
    state,reward,done,info=env.step(x,timeout=20,_path_probe=dict(path_probe_phase=1,path_second_x=.75));result['first']=dict(state=state,info=info)
    if not done:
     state,_,_,info=env.step(.75,timeout=20,_path_probe=dict(path_probe_phase=2));result['second']=dict(state=state,info=info)
    result['status']='completed';print(json.dumps(dict(fixture=fixture.stem,loaded_go=loaded['game_over'],first_go=done,drop= result['first']['info'].get('drop_success'),status=info.get('path_comparison',{}).get('status'))),flush=True)
   except Exception as e:result['status']='error';result['error']=repr(e);print(result['error'],flush=True)
   finally:
    if child.poll() is None:child.terminate();child.wait(timeout=5)
   (directory/'result.json').write_text(json.dumps(result,indent=2));rows.append(result)
 (a.output/'results.json').write_text(json.dumps(rows,indent=2))
if __name__=='__main__':main()
