"""Bounded two-action comparison, owned Player only. No long games or training."""
import argparse,json,sys,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import UnityEnv
from suika_ai.parallel_play import player_command,worker_specs

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'));p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=743100);p.add_argument('--base-port',type=int,default=26000);p.add_argument('--warmup',type=int,nargs='+',default=[0,8]);a=p.parse_args()
    if any(n<0 or n>12 for n in a.warmup):p.error('Smoke warmup limited to 0..12 actions')
    a.output.mkdir(parents=True,exist_ok=False);spec=worker_specs(1,a.base_port,a.seed)[0]
    with UnityEnv(server=('127.0.0.1',spec.listen_port),local=('127.0.0.1',spec.python_port),expected_game_id=spec.game_id) as env:
        child=subprocess.Popen(player_command(a.exe.resolve(),spec,(a.output/'player.log').resolve(),True),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            ready=time.monotonic()+30
            while True:
                try:env.receive_state(1);break
                except (TimeoutError,ConnectionResetError):
                    if time.monotonic()>ready:raise
            results=[]
            for warmup in a.warmup:
                env.reset();env.get_environment()
                for i in range(warmup):
                    state,_,done,_=env.step(.5)
                    if done:raise RuntimeError('Warmup ended in GO')
                first,_,done,info1=env.step(.25,timeout=30,_path_probe=dict(path_probe_phase=1,path_second_x=.75))
                if done:results.append(dict(warmup=warmup,status='actual_first_go',info=info1));continue
                second,_,done,info2=env.step(.75,timeout=30,_path_probe=dict(path_probe_phase=2))
                report=info2.get('path_comparison')
                if not report or report['status'] not in ('completed','prediction_terminal_before_second'):raise RuntimeError(report)
                results.append(dict(warmup=warmup,report=report))
                print(json.dumps(dict(warmup=warmup,status=report['status'],first=report.get('first'),second=report.get('second'),idle=report['idle_physics_ticks'])),flush=True)
                if warmup and not done:
                    _,_,_,contact_info=env.plan_step(dict(ai_mode='two_step',search_leaf='reward',candidate_count=2),timeout=30)
                    results[-1]['contact_search']=contact_info['planning']
                    print(json.dumps(dict(contact_search_ms=contact_info['planning']['elapsed_ms'],prefixes=contact_info['planning']['two_step']['prefixes_match'])),flush=True)
            # A few decisions only: all three leaf evaluators, plus legacy modes.
            modes=[]
            for mode,leaf in [('heuristic','reward'),('value','reward'),('two_step','reward'),('two_step','heuristic'),('two_step','value')]:
                env.reset()
                state,reward,done,info=env.plan_step(dict(ai_mode=mode,search_leaf=leaf,candidate_count=2),timeout=30)
                plan=info['planning'];modes.append(plan)
                print(json.dumps(dict(mode=mode,leaf=leaf,x=plan['selected_x'],ms=plan['elapsed_ms'],search=plan.get('two_step',{}).get('paths'))),flush=True)
            with (a.output/'results.json').open('x',encoding='utf-8') as f:json.dump(dict(comparisons=results,decisions=modes),f,indent=2)
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=5)
if __name__=='__main__':main()
