"""One prospective MCTS seed retry, preserving all censored pilot attempts."""
import argparse,json
from pathlib import Path
from suika_ai.parallel_play import run_parallel,validate_run
from compare_mcts_ai import episode,RULES_VERSION
from compare_mcts_budget import sha,assembly_sha
from episode_events import audit_events

def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,required=True);p.add_argument('--seconds',type=float,default=1200);a=p.parse_args();plan=json.loads(a.plan.read_text());exe=Path(plan['exe'])
    if sha(exe)!=plan['exe_sha256'] or assembly_sha(exe)!=plan['assembly_sha256']:raise ValueError('Frozen comparison Player changed')
    if a.seed not in plan['seeds']:raise ValueError('Retry only a predeclared seed')
    result=run_parallel(exe,a.output,games=1,episodes=1,max_steps=10000,base_port=42020,seed=a.seed,headless=True,settings=plan['settings']['mcts'],main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION,episode_events=True,max_episode_seconds=a.seconds,step_timeout=90)
    manifest=json.loads((a.output/'run.json').read_text());ep=episode(a.output,manifest,manifest['workers'][0],expected_settings=plan['settings']['mcts']);ep['run_audit']=validate_run(a.output)
    with (a.output/'game_00.jsonl').open() as f:ep.update(audit_events(json.loads(line) for line in f))
    ep['startup_inclusive_wall_seconds']=result['wall_seconds'];ep['retry_reason']='Original 420s observation was censored, not a score failure';ep['first_go_tick_known']=False
    with (a.output/'result.json').open('x',encoding='utf8') as f:json.dump(ep,f,indent=2)
    print(json.dumps(dict(natural_go=ep['natural_go'],score=ep['final_score'],seconds=ep['game_wall_seconds'],errors=ep['errors'])))

if __name__=='__main__':main()
