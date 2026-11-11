"""Common-seed natural-only scoring, plus throughput including censored work."""
import argparse,json,statistics
from pathlib import Path

def analyze(root):
    root=Path(root);games=[]
    for p in root.rglob('result.json'):
        g=json.loads(p.read_text())
        if g.get('mode') in ('heuristic','mcts') and 'natural_go' in g:games.append(dict(g,result_path=str(p)))
    # An interrupted process may leave transitions without any terminal/result.
    # Retain its observed cost, never invent a final score or a natural-GO label.
    interrupted=[]
    for p in root.rglob('run.json'):
        if (p.parent/'result.json').exists():continue
        manifest=json.loads(p.read_text());mode=manifest.get('settings',{}).get('ai_mode')
        if mode not in ('heuristic','mcts'):continue
        log=p.parent/'game_00.jsonl'
        if not log.exists():continue
        last=None;end=False;n=0;seconds=0.
        with log.open() as f:
            for line in f:
                try:r=json.loads(line)
                except ValueError:break
                if r.get('event')=='episode_end':end=True
                if r.get('event')=='transition':
                    n+=1;last=r;info=r.get('info',{});seconds=max(seconds,info.get('completion_wall',0),info.get('decision_finish_wall',0))
        interrupted.append(dict(folder=str(p.parent),has_episode_end=end,transitions=n,last_observed_score=last.get('score') if last else None,observed_seconds_lower_bound=seconds))
        games.append(dict(mode=mode,seed=manifest['workers'][0]['seed'],natural_go=False,final_score=None,errors=['interrupted_or_unaudited_run'],startup_inclusive_wall_seconds=seconds,cost_is_lower_bound=True,result_path=None))
    valid=[g for g in games if g['natural_go'] and not g['errors']];pairs=[]
    for seed in sorted({g['seed'] for g in games}):
        at={m:next((g for g in valid if g['mode']==m and g['seed']==seed),None) for m in ['heuristic','mcts']}
        if not all(at.values()):continue
        a,b=at['heuristic'],at['mcts'];n=min(len(a['public_series']),len(b['public_series']))
        if a['environment_id']!=b['environment_id'] or a['public_series'][:n]!=b['public_series'][:n]:raise ValueError('Unfair paired environment/fruit stream')
        pairs.append(dict(seed=seed,heuristic=a['final_score'],mcts=b['final_score'],difference=b['final_score']-a['final_score'],common_fruit_draws=n,series_equal=True))
    stats={}
    for mode in ['heuristic','mcts']:
        attempts=[g for g in games if g['mode']==mode];rs=[g for g in valid if g['mode']==mode];paired=[g for g in rs if g['seed'] in {p['seed'] for p in pairs}];total=sum(g['startup_inclusive_wall_seconds'] for g in attempts)
        def describe(values):
            if not values:return None
            return dict(games=len(values),mean=statistics.mean(g['final_score'] for g in values),median=statistics.median(g['final_score'] for g in values),scores=[g['final_score'] for g in values],mean_decision_ms=statistics.mean(t for g in values for t in g['planning_ms_per_action']),mean_game_seconds=statistics.mean(g['game_wall_seconds'] for g in values),watermelon_known=sum(g['double_watermelon_known'] for g in values),watermelon_games=sum((g['actual_events'] or {}).get('watermelons_created',0)>0 for g in values),score_rates={str(k):sum(g['final_score']>=k for g in values)/len(values) for k in [2000,3000,4000,5000]})
        stats[mode]=dict(attempts=len(attempts),natural_games=len(rs),censored=sum(not g['natural_go'] for g in attempts),total_attempt_seconds=total,valid_natural_games_per_hour_including_censoring=3600*len(rs)/total if total else None,all_complete_descriptive=describe(rs),paired_only=describe(paired))
    return dict(pairs=pairs,stats=stats,games=games,interrupted=interrupted,limitations='Scores compared only in common natural-GO seeds; hourly rates include all attempts. Interrupted run time is only a lower bound, so throughput is an upper-bound extrapolation, not an hour-long benchmark.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.root)
    with a.output.open('x',encoding='utf8') as f:json.dump(r,f,indent=2)
    print(json.dumps(dict(pairs=r['pairs'],stats=r['stats']),indent=2))
