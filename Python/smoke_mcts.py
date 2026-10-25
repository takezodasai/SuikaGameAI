"""Bounded STEP8-B real UDP smoke: no full game collection or training."""
import argparse,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import UnityEnv
from suika_ai.parallel_play import player_command,worker_specs

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=743302)
    p.add_argument('--base-port',type=int,default=27400);p.add_argument('--warmup',type=int,default=10)
    a=p.parse_args()
    if not 0<=a.warmup<=16:p.error('Warmup limited to 0..16')
    a.output.mkdir(parents=True,exist_ok=False);spec=worker_specs(1,a.base_port,a.seed)[0]
    results=dict(decisions=[],comparisons=[])
    with UnityEnv(server=('127.0.0.1',spec.listen_port),local=('127.0.0.1',spec.python_port),expected_game_id=spec.game_id) as env:
        exe=Path('../Unity/Builds/Step6/SuikaGameAI.exe').resolve()
        child=subprocess.Popen(player_command(exe,spec,(a.output/'player.log').resolve(),True),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+30
            while True:
                try:env.receive_state(1);break
                except (TimeoutError,ConnectionResetError):
                    if time.monotonic()>deadline:raise
            env.reset();results['environment']=env.get_environment()
            for mode in ('mcts','mcts_value','heuristic','value','two_step'):
                env.reset()
                for turn in range(2):
                    state,reward,done,info=env.plan_step(dict(ai_mode=mode,candidate_count=2 if mode=='two_step' else 5,mcts_iterations=16,mcts_max_depth=3),timeout=30)
                    plan=info.get('planning')
                    if plan:
                        chosen=plan['candidates'][plan['selected_index']]
                        if info['drop_success'] and abs(info['applied_normalized_x']-plan['selected_x'])>1e-5:raise AssertionError('Action mismatch')
                        if chosen['predicted_game_over'] and not plan['all_predicted_terminal']:raise AssertionError('Unsafe root choice')
                        if 'mcts' in plan:
                            if not plan['mcts']['source_unchanged'] or not plan['mcts']['prefixes_match']:raise AssertionError('Source contamination')
                            if sum(row['visits'] for row in plan['mcts']['nodes'][0]['actions'])!=16:raise AssertionError('Lost iteration')
                        results['decisions'].append(dict(mode=mode,turn=turn+1,state=state,info=info,chosen_go_match=chosen['predicted_game_over']==done))
                        print(json.dumps(dict(mode=mode,turn=turn+1,score=state['score'],reward=reward,go=done,x=plan['selected_x'],ms=plan['elapsed_ms'])),flush=True)
                    if done:break
            # Same-root native-vs-live diagnostics, with exact public chance conditioning
            # and measured between-action idle physics ticks. Both free and contact boards.
            for warmup in (0,a.warmup):
                env.reset()
                for _ in range(warmup):
                    _,_,done,_=env.step(.5)
                    if done:break
                else:
                    _,_,done,first=env.step(.25,timeout=30,_path_probe=dict(path_probe_phase=1,path_second_x=.75))
                    if done:results['comparisons'].append(dict(warmup=warmup,first=first));continue
                    _,_,_,second=env.step(.75,timeout=30,_path_probe=dict(path_probe_phase=2))
                    report=second.get('path_comparison')
                    if not report:raise AssertionError('Comparison absent')
                    results['comparisons'].append(dict(warmup=warmup,report=report))
                    print(json.dumps(dict(warmup=warmup,comparison_status=report['status'],first=report.get('first'),second=report.get('second'))),flush=True)
            with (a.output/'results.json').open('x',encoding='utf-8') as f:json.dump(results,f,indent=2,allow_nan=False)
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=5)
if __name__=='__main__':main()
