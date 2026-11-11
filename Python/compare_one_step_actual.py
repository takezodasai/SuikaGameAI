"""Few paired natural-GO games, existing heuristic vs unchanged MCTS128/depth4."""
import argparse,json,time,statistics
from pathlib import Path
from compare_mcts_ai import episode,paired_ci,RULES_VERSION
from compare_mcts_budget import sha,assembly_sha
from episode_events import audit_events
from suika_ai.parallel_play import run_parallel,validate_run
from suika_ai.unity_env import validate_planning_settings

def summarize(root,plan):
    games=[json.loads(p.read_text()) for p in sorted(root.glob('seed_*/*/result.json'))];valid=[g for g in games if g['natural_go'] and not g['errors']];by={m:[g for g in valid if g['mode']==m] for m in ['heuristic','mcts']};pairs=[]
    for seed in plan['seeds']:
        at={g['mode']:g for g in valid if g['seed']==seed}
        if len(at)!=2:continue
        a,b=at['heuristic'],at['mcts'];n=min(len(a['public_series']),len(b['public_series']));pairs.append(dict(seed=seed,heuristic=a['final_score'],mcts=b['final_score'],mcts_minus_heuristic=b['final_score']-a['final_score'],fruit_common_prefix_length=n,fruit_series_prefix_equal=a['public_series'][:n]==b['public_series'][:n],initial_held_next_equal=a['public_series'][:2]==b['public_series'][:2]))
    stats={}
    for mode,rs in by.items():
        if not rs:continue
        scores=[r['final_score'] for r in rs];times=[t for r in rs for t in r['planning_ms_per_action']];stats[mode]=dict(games=len(rs),mean_score=statistics.mean(scores),median_score=statistics.median(scores),maximum=max(scores),minimum=min(scores),mean_game_wall_seconds=statistics.mean(r['game_wall_seconds'] for r in rs),mean_decision_ms=statistics.mean(times),serial_games_per_hour_estimate=3600*len(rs)/sum(r['startup_inclusive_wall_seconds'] for r in rs),watermelon_known=sum(r['double_watermelon_known'] for r in rs),watermelon_games=sum((r['actual_events'] or {}).get('watermelons_created',0)>0 for r in rs),score_rates={str(k):sum(s>=k for s in scores)/len(scores) for k in [2000,3000,4000,5000]})
    report=dict(games=games,valid_games=len(valid),pairs=pairs,stats=stats,paired_ci95=paired_ci([r['mcts_minus_heuristic'] for r in pairs]),limitation='Few seeds, descriptive only; hourly throughput extrapolated from serial headless runs. Different actions have different timing.')
    # Only this new experiment's derived summary is refreshed; raw results are exclusive.
    (root/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf8');return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seeds',type=int,nargs='+',default=[882610281,882610282]);p.add_argument('--game-seconds',type=float,default=420);p.add_argument('--base-port',type=int,default=42020);p.add_argument('--total-seconds',type=float,default=1200);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    if a.analyze_only:summarize(a.output,json.loads((a.output/'plan.json').read_text()));return
    a.output.mkdir(parents=True,exist_ok=False);base=dict(candidate_count=5,post_drop_steps=25,mcts_iterations=128,mcts_max_depth=4,mcts_seed=8191,execution_mode='sync',rollout_policy='random',candidate_policy='grid',mcts_budget_mode='fixed',mcts_widening=False)
    plan=dict(exe=str(a.exe.resolve()),exe_sha256=sha(a.exe),assembly_sha256=assembly_sha(a.exe),seeds=a.seeds,settings={mode:validate_planning_settings(dict(base,ai_mode=mode)) for mode in ['heuristic','mcts']},game_wall_limit=a.game_seconds,iteration_limit=128,depth=4,max_steps=10000,base_port=a.base_port)
    (a.output/'plan.json').write_text(json.dumps(plan,indent=2));started=time.monotonic()
    for si,seed in enumerate(a.seeds):
        for mode in (['heuristic','mcts'] if si%2==0 else ['mcts','heuristic']):
            if time.monotonic()-started>=a.total_seconds:summarize(a.output,plan);return
            folder=a.output/f'seed_{seed}'/mode;print(json.dumps(dict(event='start_game',seed=seed,mode=mode)),flush=True)
            result=run_parallel(a.exe,folder,games=1,episodes=1,max_steps=10000,base_port=a.base_port,seed=seed,headless=True,settings=plan['settings'][mode],main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION,episode_events=True,max_episode_seconds=a.game_seconds,step_timeout=90)
            manifest=json.loads((folder/'run.json').read_text());ep=episode(folder,manifest,manifest['workers'][0],expected_settings=plan['settings'][mode]);ep['run_audit']=validate_run(folder)
            with (folder/'game_00.jsonl').open() as f:ep.update(audit_events(json.loads(line) for line in f))
            rows=[json.loads(x) for x in (folder/'game_00.jsonl').read_text().splitlines()];end=next(r for r in reversed(rows) if r.get('event')=='episode_end');meta=json.loads((folder/'metadata/game_00.json').read_text())['environment'];height=meta['game_over_y']
            ep['go_observed_eligible_fruits']=[{k:f[k] for k in ['type','x','y','has_collided']} for f in end['state']['fruits'] if f.get('has_collided') and not f.get('is_merging') and f['y']>height];ep['go_rule']=meta['game_over_rule'];ep['first_go_tick_known']=False;ep['startup_inclusive_wall_seconds']=result['wall_seconds']
            with (folder/'result.json').open('x',encoding='utf8') as f:json.dump(ep,f,indent=2)
            summarize(a.output,plan);print(json.dumps(dict(event='end_game',seed=seed,mode=mode,natural_go=ep['natural_go'],score=ep['final_score'],errors=ep['errors'])),flush=True)
            if any(not e.startswith('not_natural_go:') for e in ep['errors']):raise RuntimeError('Integrity failure; retain data, do not count as valid comparison')

if __name__=='__main__':main()
