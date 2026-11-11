"""Game/seed-pair analysis of the preregistered frozen-V comparison."""
import argparse,csv,json,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from frozen_v_pair_experiment import ROOT
from frozen_model_actual_play import write
from run_fresh_continuation import read_rows

def mean(xs):return float(np.mean(xs)) if xs else None
def percentile(xs,p):return float(np.percentile(xs,p)) if xs else None

def paired_ci(differences,groups,replicates=20000,seed=2026103102):
    """Resample independent seed groups, never individual decisions."""
    by=defaultdict(list)
    for x,g in zip(differences,groups):by[g].append(x)
    if len(by)<2:return None
    arrays=list(by.values());rng=np.random.default_rng(seed);samples=[]
    for ids in rng.integers(0,len(arrays),(replicates,len(arrays))):samples.append(np.mean([x for i in ids for x in arrays[i]]))
    return [float(x) for x in np.percentile(samples,[2.5,97.5])]

def valid_game(result,meta):
    return bool(result.get('natural_go') and not result.get('errors') and result.get('score_conserved') and not meta.get('failure') and not meta.get('quarantined'))

def attach_groups(pairs):
    parent=list(range(len(pairs)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    seen={}
    for i,p in enumerate(pairs):
        for prefix in [p['initial8_C'],p['initial8_D']]:
            if prefix in seen:parent[find(i)]=find(seen[prefix])
            else:seen[prefix]=i
    for i,p in enumerate(pairs):p['group']='seed_group_'+str(min(q['seed'] for j,q in enumerate(pairs) if find(j)==find(i)))
    return pairs

def error_buckets(rows):
    by=defaultdict(list)
    for r in rows:
        for kind in ['density','height_band','phase','score_band','watermelon_phase']:
            by[kind+':'+r[kind]].append(r)
        if r['phase']=='last5' and not r['predicted_GO']:by['supplement:last5_predicted_non_GO'].append(r)
    return {k:dict(decisions=len(rs),MAE=mean([abs(r['error']) for r in rs]),bias=mean([r['error'] for r in rs]),mean_realized_return=mean([r['realized'] for r in rs]),mean_prediction=mean([r['prediction'] for r in rs])) for k,rs in by.items()}

def audit(folder):
    result_path=folder/'result.json';result=json.loads(result_path.read_text()) if result_path.exists() else json.loads((folder/'incomplete_result.json').read_text())
    cfg=json.loads((folder/'config.json').read_text());meta=json.loads((folder/'comparison_metadata.json').read_text());rows=list(read_rows(folder/'trace.jsonl'))
    start=next(r for r in rows if r['evt']=='start');end=next((r for r in reversed(rows) if r['evt']=='end'),None);decisions=[r for r in rows if r['evt']=='decision'];actions=[r for r in rows if r['evt']=='action'];natural=valid_game(result,meta)
    # Include a last release that ended in GO before the 25-tick observation.
    events=(end or {}).get('actual_events') or {};known=events.get('source')=='actual_game' and events.get('known') is True
    wm=events.get('watermelons_created') if known else None
    first_wm=next((e['drop_count'] for e in events.get('events',[]) if e['kind']=='first_watermelon'),None)
    final_score=end['score'] if natural else None;errors=[];danger=[];timing=[];positions=Counter();samples=[];opportunities=[];unexecuted=0
    for d in decisions:
        turn=d['drops']+1;path=folder/'bridge'/f'prediction_{turn:04d}.json'
        if not path.exists():errors.append('missing_prediction:'+str(turn));continue
        p=json.loads(path.read_text());req=json.loads((folder/'bridge'/f'request_{turn}.json').read_text());service=json.loads((folder/'bridge'/f'service_{turn:04d}.json').read_text());x=d['command']['x'];index=round(x*4);c=req['candidates'][index];state=p['state'];positions[str(x)]+=1
        safe=[i for i,a in enumerate(req['candidates']) if a['drop'] and not a['go']]
        if c['go']:danger.append(dict(turn=turn,x=x,score=state['score'],safe_alternatives=bool(safe)))
        completion=next((a['command']['completion_tick'] for a in actions if a['drops']==d['drops']),d['tick'])
        if d['tick']!=completion:errors.append('extra_idle_ticks:'+str(turn))
        if state['score']!=d['score']:errors.append('source_score_changed:'+str(turn))
        timing.append(dict(turn=turn,actor_ms=d['actor_ms'],V_inference_ms=service['V_inference_ms'],python_service_ms=service['service_ms'],bridge_wait_ms=d['bridge_ms'],
            polling_and_IPC_residual_ms=max(0,d['bridge_ms']-service['service_ms']),physics_ms=req['physics_ms'],mode=cfg['mode']))
        h_index=round(req['native_x']*4);v_index=round(p['choices']['C']*4)
        if h_index!=v_index:
            opportunities.append(dict(turn=turn,score=state['score'],fruit_count=len(state['fruits']),heuristic_x=req['native_x'],V_x=p['choices']['C'],
                heuristic_predicted_immediate=req['candidates'][h_index]['reward'],V_predicted_immediate=req['candidates'][v_index]['reward'],V_forecast_at_heuristic=p['V'][h_index],V_forecast_at_V=p['V'][v_index],
                warning='Other action return unobserved; this is not a correct/incorrect action label.'))
        if natural:
            fruit_count=len(state['fruits']);density='0-9' if fruit_count<10 else '10-19' if fruit_count<20 else '20-29' if fruit_count<30 else '30+'
            floor,go=state['geometry'][2:4];top=max([f['y'] for f in state['fruits'] if f['has_collided']]+[floor]);height=(top-floor)/(go-floor);height_band='<0.6' if height<.6 else '0.6-0.8' if height<.8 else '>=0.8'
            prediction=p['V'][index];realized=final_score-state['score'];phase='last5' if turn>len(decisions)-5 else 'earlier'
            wphase='unknown' if not known else 'no_watermelon_game' if first_wm is None else 'after_first_watermelon' if d['drops']>=first_wm else 'before_first_watermelon_in_success_game'
            samples.append(dict(turn=turn,score=state['score'],x=x,prediction=prediction,realized=realized,error=prediction-realized,density=density,height_band=height_band,phase=phase,
                score_band='>=2000' if state['score']>=2000 else '<2000',watermelon_phase=wphase,predicted_immediate=c['reward'],predicted_future=prediction-c['reward'],predicted_GO=c['go'],
                gain_before_next_observation=(next((a['score'] for a in actions if a['drops']==turn),final_score)-state['score'])))
    for a in actions:
        if a['command']['completion_tick']-a['command']['drop_tick']!=25:errors.append('post_drop_not25')
    n=len(decisions);ms=[t['actor_ms'] for t in timing];elapsed=result.get('wall_seconds');state=(end or {}).get('state')
    counter=dict(selected_predicted_GO=len(danger),unsafe_selected_with_safe_alternative=sum(r['safe_alternatives'] for r in danger),decisions=n)
    return dict(seed=cfg['seed'],mode=cfg['mode'],natural_go=natural,reason=result.get('reason'),final_score=final_score,last_observed_score=(end or {}).get('score'),
        drops=events.get('drop_count'),watermelons_created=wm,double_watermelons=events.get('double_watermelons') if known else None,events_known=known,initial_state=start['state'],
        public_series=result.get('public_series',[]),initial8=','.join(map(str,result.get('public_series',[])[:8])),wall_seconds=elapsed,game_wall_seconds=result.get('game_wall_seconds'),
        mean_actor_ms=mean(ms),p95_actor_ms=percentile(ms,95),total_actor_seconds=sum(ms)/1000,mean_bridge_wait_ms=mean([t['bridge_wait_ms'] for t in timing]),p95_bridge_wait_ms=percentile([t['bridge_wait_ms'] for t in timing],95),
        mean_V_inference_ms=mean([t['V_inference_ms'] for t in timing]),mean_python_service_ms=mean([t['python_service_ms'] for t in timing]),mean_IPC_poll_residual_ms=mean([t['polling_and_IPC_residual_ms'] for t in timing]),
        offline_shadow_seconds=meta['offline_shadow_seconds'],position_counts=dict(positions),position_rates={k:v/n for k,v in positions.items()} if n else {},danger=counter,danger_cases=danger,final5_samples=samples[-5:],
        final_state=state,GO_fruits=[f for f in (state or {}).get('fruits',[]) if f['has_collided'] and f['y']>state['geometry'][3]] if state else [],
        V_error_buckets=error_buckets(samples),samples=samples,timing=timing,opportunities=opportunities,invariant_errors=errors,run_errors=result.get('errors'),quarantined=meta['quarantined'],retained_scenes=(end or {}).get('retained_scenes'))

def summarize(games,plan):
    valid=[g for g in games if g['natural_go'] and not g['invariant_errors'] and not g['run_errors']];by=defaultdict(dict)
    for g in valid:by[g['seed']][g['mode']]=g
    pairs=[]
    for seed in plan['seeds']:
        at=by[seed]
        if set(at)!={'C','D'}:continue
        c,d=at['C'],at['D'];common=min(len(c['public_series']),len(d['public_series']));a,b=c['public_series'][:common],d['public_series'][:common]
        pair=dict(seed=seed,heuristic=d['final_score'],V=c['final_score'],difference=c['final_score']-d['final_score'],initial_states_equal=c['initial_state']==d['initial_state'],common_public_fruits=common,
            public_series_equal=a==b,first_public_difference=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),None),initial8_C=c['initial8'],initial8_D=d['initial8'],same_initial8=c['initial8']==d['initial8'],
            V_minus_H_mean_actor_ms=c['mean_actor_ms']-d['mean_actor_ms'],V_minus_H_wall_seconds=c['wall_seconds']-d['wall_seconds'])
        pairs.append(pair)
    attach_groups(pairs)
    stats={}
    for mode in ['D','C']:
        rs=[g for g in valid if g['mode']==mode];scores_=[g['final_score'] for g in rs];known=[g for g in rs if g['events_known']]
        if not rs:continue
        stats[mode]=dict(n=len(rs),independent_initial8_groups=len({r['initial8'] for r in rs}),mean_score=mean(scores_),median_score=float(np.median(scores_)),max_score=max(scores_),min_score=min(scores_),std_score=float(np.std(scores_,ddof=1)) if len(rs)>1 else None,
            watermelon_games=sum(g['watermelons_created']>0 for g in known),watermelon_denominator=len(known),watermelon_rate=sum(g['watermelons_created']>0 for g in known)/len(known) if known else None,
            mean_drops=mean([g['drops'] for g in rs]),mean_game_wall_seconds=mean([g['wall_seconds'] for g in rs]),mean_game_total_actor_seconds=mean([g['total_actor_seconds'] for g in rs]),
            mean_of_game_mean_actor_ms=mean([g['mean_actor_ms'] for g in rs]),mean_of_game_p95_actor_ms=mean([g['p95_actor_ms'] for g in rs]),
            pooled_p95_actor_ms=percentile([t['actor_ms'] for g in rs for t in g['timing']],95),
            mean_inference_ms=mean([g['mean_V_inference_ms'] for g in rs]),mean_service_ms=mean([g['mean_python_service_ms'] for g in rs]),mean_IPC_poll_residual_ms=mean([g['mean_IPC_poll_residual_ms'] for g in rs]),
            decisions=sum(g['danger']['decisions'] for g in rs),unsafe_with_safe_alt=sum(g['danger']['unsafe_selected_with_safe_alternative'] for g in rs),
            predicted_GO_selections=sum(g['danger']['selected_predicted_GO'] for g in rs),game_macro_selected_GO_rate=mean([g['danger']['selected_predicted_GO']/g['danger']['decisions'] for g in rs if g['danger']['decisions']]),
            game_macro_position_rates={str(x):mean([g['position_rates'].get(str(x),0) for g in rs]) for x in [0.,.25,.5,.75,1.]})
        buckets=defaultdict(list)
        for g in rs:
            for k,bucket in g['V_error_buckets'].items():buckets[k].append(bucket)
        stats[mode]['V_prediction_errors_game_macro']={k:dict(games=len(bs),decisions=sum(b['decisions'] for b in bs),MAE=mean([b['MAE'] for b in bs]),bias=mean([b['bias'] for b in bs]),mean_prediction=mean([b['mean_prediction'] for b in bs]),mean_realized_return=mean([b['mean_realized_return'] for b in bs])) for k,bs in buckets.items()}
    ds=[p['difference'] for p in pairs];groups=[p['group'] for p in pairs]
    paired=dict(n=len(pairs),independent_groups=len(set(groups)),V_wins=sum(x>0 for x in ds),V_losses=sum(x<0 for x in ds),ties=sum(x==0 for x in ds),mean_difference=mean(ds),median_difference=float(np.median(ds)) if ds else None,
        paired_cluster_bootstrap95=paired_ci(ds,groups),leave_one_pair_out_mean_range=[min((sum(ds)-d)/(len(ds)-1) for d in ds),max((sum(ds)-d)/(len(ds)-1) for d in ds)] if len(ds)>1 else None,
        max_absolute_difference=max(map(abs,ds)) if ds else None)
    return dict(games=games,stats=stats,pairs=pairs,paired=paired,planned_seed_count=len(plan['seeds']),planned_games=24,observed_games=len(games),natural_games=len(valid),
        incomplete=[dict(seed=g['seed'],mode=g['mode'],reason=g['reason'],last_score=g['last_observed_score'],errors=g['invariant_errors']+g['run_errors']) for g in games if g not in valid],
        unstarted=[dict(seed=s,mode=m) for s in plan['seeds'] for m in ['D','C'] if not any(g['seed']==s and g['mode']==m for g in games)],
        note='Development only; no model selection/tuning on Test19, no independent-decision significance. Behavior-policy dependent returns, not optimal-action ground truth. Shared GO predicate but frozen all-GO fallback differs.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'analysis_final.json');args=parser.parse_args();plan=json.loads((ROOT/'plan.json').read_text());games=[]
    for s in plan['seeds']:
        for m in ['D','C']:
            p=ROOT/f'seed_{s}'/m
            if (p/'result.json').exists() or (p/'incomplete_result.json').exists():
                try:games.append(audit(p))
                except Exception as e:
                    games.append(dict(seed=s,mode=m,natural_go=False,reason='audit_exception',last_observed_score=None,invariant_errors=[str(e)],run_errors=[]))
    report=summarize(games,plan);write(args.output,report)
    csvpath=args.output.with_suffix('.csv')
    columns=['seed','mode','natural_go','final_score','last_observed_score','drops','watermelons_created','mean_actor_ms','p95_actor_ms','wall_seconds','reason']
    with csvpath.open('x',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows({k:g.get(k) for k in columns} for g in games)
    print(json.dumps(dict(stats=report['stats'],paired=report['paired']),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
