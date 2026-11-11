"""Descriptive only: few development games, no model fitting or Test selection."""
import csv,json,statistics
from collections import Counter
from pathlib import Path
from frozen_model_actual_play import ROOT,write,choose,XS
from run_fresh_continuation import read_rows

def game_audit(folder):
    result=json.loads((folder/'result.json').read_text());decisions=[];actions=[];native=[];end=None;start=None
    for r in read_rows(folder/'trace.jsonl'):
        if r['evt']=='start':start=r
        elif r['evt']=='decision':decisions.append(r)
        elif r['evt']=='action':actions.append(r)
        elif r['evt']=='native_plan':native.append(r)
        elif r['evt']=='end':end=r
    predictions=[json.loads(p.read_text()) for p in sorted((folder/'bridge').glob('prediction_*.json'))]
    config=json.loads((folder/'config.json').read_text());byturn={p['id']:p for p in predictions};risk=[]
    for d in decisions:
        p=byturn[d['drops']+1];x=d['command']['x'];i=round(x*4)
        if p['predicted_GO'][i]:risk.append(dict(turn=p['id'],score=p['state']['score'],x=x,safe_alternatives=any(not g for g in p['predicted_GO'])))
    last=[];seed_disagreement=Counter();terminal_overprediction=[]
    for p in predictions:
        request=json.loads((folder/'bridge'/f"request_{p['id']}.json").read_text());cs=request['candidates']
        qxs=[XS[choose(v,cs,False)] for v in p['Q_seeds']]
        vxs=[XS[choose([row[j] for row in p['V_seeds']],cs,True)] for j in range(3)]
        seed_disagreement['Q']+=len(set(qxs))>1;seed_disagreement['V']+=len(set(vxs))>1
        if result['natural_go'] and p['id']>len(decisions)-5:
            d=decisions[p['id']-1];i=round(d['command']['x']*4);terminal_overprediction.append(dict(turn=p['id'],realized_additional=result['score']-p['state']['score'],Q=p['Q'][i],V=p['V'][i]))
    for d in decisions[-5:]:
        p=byturn[d['drops']+1];i=round(d['command']['x']*4)
        last.append(dict(turn=p['id'],score=p['state']['score'],x=d['command']['x'],Q=p['Q'][i],V=p['V'][i],predicted_GO=p['predicted_GO'][i],choices=p['choices']))
    seq=result['public_series'];test=json.loads(Path('Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())
    geom=end['state']['geometry'];go_fruits=[f for f in end['state']['fruits'] if f['has_collided'] and f['y']>geom[3]]
    histogram=Counter(d['command']['x'] for d in decisions);n=len(decisions)
    audit=dict(seed=config['seed'],mode=config['mode'],initial_state=start['state'],natural_go=result['natural_go'],score=result['score'],actual_drop_count=result['actual_events']['drop_count'],completed_post25_actions=len(actions),
        wall_seconds=result['wall_seconds'],mean_actor_ms=result['mean_actor_ms'],total_actor_ms=result['total_actor_ms'],
        actual_events=result['actual_events'],fruit_counts=dict(Counter(f['type'] for f in end['state']['fruits'])),GO_fruits=go_fruits,
        errors=result['errors'],score_conserved=result['score_conserved'],selected_x_histogram={str(k):v for k,v in histogram.items()},most_frequent_fraction=max(histogram.values())/n if n else None,
        selected_predicted_GO=risk,last_five=last,disagreements=result['disagreements'],QV_disagreements=[r for r in result['disagreements'] if r['choices']['B']!=r['choices']['C']],public_series=seq,training_seed_choice_disagreement=dict(seed_disagreement),last_five_realized_vs_predictions=terminal_overprediction,
        Test19_seed_overlap=config['seed'] in {e['seed'] for e in test['episodes']},Test19_initial8_overlap=','.join(map(str,seq[:8])) in {e['initial_sequence'] for e in test['episodes']},
        native_iterations=dict(Counter(r['mcts']['completed_iterations'] for r in native)) if config['mode']=='A' else None,
        native_depths=dict(Counter(r['mcts']['max_depth'] for r in native)) if config['mode']=='A' else None,
        prediction_state_score_match=all(p['state']['score']==d['score'] for p,d in zip(sorted(predictions,key=lambda p:p['id']),decisions)),
        final_retained_scenes=result['final_retained_scenes'],post_drop_tick_audit=all(r['command']['completion_tick']-r['command']['drop_tick']==25 for r in actions),
        decision_idle_tick_gaps=[d['tick']-next((r['command']['completion_tick'] for r in actions if r['drops']==d['drops']),d['tick']) for d in decisions])
    return audit

def main():
    games=[game_audit(p.parent) for p in sorted(ROOT.glob('seed_*/*/result.json'))]
    recovery=ROOT/'recovery/A/result.json'
    if recovery.exists():
        r=game_audit(recovery.parent);r['technical_recovery']=True;games.append(r)
    valid=[g for g in games if g['natural_go'] and not g['errors'] and g['score_conserved']];pairs=[]
    for seed in sorted({g['seed'] for g in valid}):
        at={g['mode']:g for g in valid if g['seed']==seed}
        if len(at)!=4:continue
        n=min(len(g['public_series']) for g in at.values());seq=at['A']['public_series'][:n]
        pairs.append(dict(seed=seed,scores={m:g['score'] for m,g in at.items()},minus_MCTS={m:g['score']-at['A']['score'] for m,g in at.items() if m!='A'},common_public_prefix=n,all_common_public_fruits_equal=all(g['public_series'][:n]==seq for g in at.values()),initial_states_equal=all(g['initial_state']==at['A']['initial_state'] for g in at.values())))
    stats={}
    for mode in 'ABCD':
        rs=[g for g in valid if g['mode']==mode]
        if rs:stats[mode]=dict(n=len(rs),mean_score=statistics.mean(g['score'] for g in rs),median_score=statistics.median(g['score'] for g in rs),mean_game_wall_seconds=statistics.mean(g['wall_seconds'] for g in rs),decision_weighted_mean_actor_ms=sum(g['total_actor_ms'] for g in rs)/sum(sum(g['selected_x_histogram'].values()) for g in rs),watermelon_games=sum(g['actual_events']['watermelons_created']>0 for g in rs))
    write(ROOT/'actual_summary.json',dict(games=games,pairs=pairs,stats=stats,note='Development seeds only. Actual executed actions, frozen 3-model ensemble Q/V. No sampling CI or high-score adoption from two games. Wall includes shadow instrumentation.'))
    with (ROOT/'games.csv').open('x',newline='',encoding='utf-8-sig') as f:
        columns=['seed','mode','technical_recovery','natural_go','final_score','last_observed_score','drops','watermelons','mean_actor_ms','wall_seconds','reason']
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for g in games:writer.writerow(dict(seed=g['seed'],mode=g['mode'],technical_recovery=g.get('technical_recovery',False),natural_go=g['natural_go'],final_score=g['score'] if g['natural_go'] else '',last_observed_score=g['score'],drops=g['actual_drop_count'],watermelons=g['actual_events']['watermelons_created'],mean_actor_ms=g['mean_actor_ms'],wall_seconds=g['wall_seconds'],reason='natural_go' if g['natural_go'] else 'censored'))

if __name__=='__main__':main()
