"""STEP8-Q public NEXT diagnostic. Reads logs only; does not choose live actions."""
import argparse,json
from pathlib import Path

def eligible(p):return p['first']['drop_success'] and p['second']['drop_success'] and not p['game_over']
def best_pair(paths):
    safe=[p for p in paths if eligible(p)]
    return max(safe,key=lambda p:(p['final_evaluation']['value'],p['total_reward'],-p['second_index'])) if safe else None

def validate_pairs(r):
    if r.get('error'):raise ValueError(r['error'])
    if not all(r[k] for k in ['source_unchanged','root_unchanged','random_unchanged','unknown_next_invariant']):raise ValueError('State or hidden-fruit invariance failure')
    ps=r['pairs']
    if len(ps)!=25 or {(p['first_index'],p['second_index']) for p in ps}!={(i,j) for i in range(5) for j in range(5)}:raise ValueError('Incomplete 25-path grid')
    for p in ps:
        a,b=p['first'],p['second']
        if not p['prefix_match'] or p['total_reward']!=a['reward']+b['reward'] or p['ticks']!=a['physics_steps']+b['physics_steps'] or p['merges']!=a['merges']+b['merges']:raise ValueError('Prefix/reward/tick/merge conservation failure')
        if a['predicted_game_over'] and (b['drop_success'] or b['physics_steps']):raise ValueError('Second drop after GO')
        e=p['final_evaluation']
        if abs(e['value']-(p['total_reward']/55-.2*e['roughness']))>1e-5:raise ValueError('Final formula mismatch')
        one=r['one'][p['first_index']]
        if any(a[k]!=one[k] for k in ['reward','physics_steps','merges','predicted_game_over']):raise ValueError('Standalone/paired first move mismatch')
    if sum(p['ticks'] for p in ps)!=r['pair_ticks'] or sum(c['physics_steps'] for c in r['one'])!=r['one_ticks']:raise ValueError('Aggregate physical work mismatch')
    return True

def analyze(rows):
    results=[]
    for r in rows:
        validate_pairs(r);summaries=[]
        for i,c in enumerate(r['one']):
            paths=[p for p in r['pairs'] if p['first_index']==i];best=best_pair(paths);safe=[p for p in paths if eligible(p)]
            summaries.append(dict(x=i/4,one_reward=c['reward'],one_R=c['evaluation']['roughness'],one_value=c['evaluation']['value'],one_go=c['predicted_game_over'],max_two_reward_any=max(p['total_reward'] for p in paths),max_two_reward_safe=max((p['total_reward'] for p in safe),default=None),best_safe=best,two_value=None if best is None else best['final_evaluation']['value']))
        rank_a=sorted(range(5),key=lambda i:(r['one'][i]['predicted_game_over'] or not r['one'][i]['drop_success'],-summaries[i]['one_value'],i))
        rank_b=sorted(range(5),key=lambda i:(summaries[i]['two_value'] is None,-(summaries[i]['two_value'] or 0),i))
        delayed=[]
        if len(r.get('delayed',[]))!=5:raise ValueError('Delayed observations missing')
        for i,series in enumerate(r['delayed']):
            if [t['target_post_ticks'] for t in series['samples']]!=[50,100,150]:raise ValueError('Wrong wait horizons')
            last=0
            for t in series['samples']:
                if not last<=t['actual_wait_ticks']<=t['target_post_ticks']-25 or t['reward']<0 or t['merges']<0:raise ValueError('Invalid wait observation')
                last=t['actual_wait_ticks']
            delayed.append(dict(x=i/4,after25_reward=r['one'][i]['reward'],observations=series['samples']))
        results.append(dict(fixture=Path(r['fixture']).stem,held_type=r['held_type'],next_type=r['next_type'],initial_score=r['initial_score'],candidates=summaries,rank_one=[i/4 for i in rank_a],rank_two=[i/4 for i in rank_b],delayed=delayed,one_ms=r['one_ms'],pair_ms=r['pair_ms'],mcts_ms=r['mcts_ms'],one_plus_mcts_ms=r['one_ms']+r['mcts_ms'],pair_plus_mcts_ms=r['pair_ms']+r['mcts_ms'],initial_build_ms=r['initial_build_ms'],late_ms=r['late_ms'],one_ticks=r['one_ticks'],pair_ticks=r['pair_ticks'],late_ticks=r['late_ticks'],mcts_ticks=r['baseline']['total_physics_ticks'],pair_advances=r['pair_advances'],rebuild_ms=sum(p['rebuild_ms'] for p in r['pairs']),first_ms=sum(p['first_ms'] for p in r['pairs']),second_ms=sum(p['second_ms'] for p in r['pairs']),evaluate_ms=sum(p['evaluate_ms'] for p in r['pairs']),dispose_schedule_ms=sum(p['dispose_ms'] for p in r['pairs']),managed_delta_bytes=r['managed_end']-r['managed_start'],unity_sampled_delta_bytes=r['unity_sampled_peak']-r['unity_start'],measurement_total_ms=r['measured_total_ms'],invariance_checks_passed=True))
    return dict(fixtures=results,note='Diagnostic only; best of 25 is an optimistic two-action result, not a long-term value or real-game strength measurement. Combined timings are sums of measured phases, excluding unrelated wait/invariance tests; not an integrated production planner.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2,allow_nan=False)
    for x in r['fixtures']:print(json.dumps({k:x[k] for k in ['fixture','rank_one','rank_two','one_ms','pair_ms','mcts_ms','pair_plus_mcts_ms','one_ticks','pair_ticks']}))
if __name__=='__main__':main()
