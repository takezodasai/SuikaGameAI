"""Read-only audit: repeated runs are nested measurements, not independent roots."""
import argparse
import csv
import json
import statistics
from pathlib import Path

from branch_trial_registry import digest, trial_identity
from branch_pair_dataset import grouped_splits
from watermelon_lab import sha, write


def avg(xs):return statistics.mean(xs) if xs else None
def sd(xs):return statistics.stdev(xs) if len(xs)>1 else None
def rows(path):return [json.loads(s) for s in Path(path).open(encoding='utf8') if s.strip()]


def pair_statistics(repetitions):
    valid=[r for r in repetitions if r['delta_B_minus_A'] is not None]
    ds=[r['delta_B_minus_A'] for r in valid]
    return dict(repetitions=repetitions,valid_repetitions=len(ds),
        mean_return_A=avg([r['return_A'] for r in valid]),mean_return_B=avg([r['return_B'] for r in valid]),
        sd_return_A=sd([r['return_A'] for r in valid]),sd_return_B=sd([r['return_B'] for r in valid]),
        mean_delta=avg(ds),sd_delta=sd(ds),B_wins=sum(d>0 for d in ds),A_wins=sum(d<0 for d in ds),
        replicate_rank_flip=any(d>0 for d in ds) and any(d<0 for d in ds))


def event_value(r):
    return {k:r[k] for k in ['tick','score','additional_score','accepted_drops','merges','rng','state'] if k in r}


def physical_value(r):
    v=event_value(r)
    def clean(x):
        if isinstance(x,dict):return {k:clean(t) for k,t in x.items() if k!='id'}
        if isinstance(x,list):return [clean(t) for t in x]
        return x
    v=clean(v)
    if 'state' in v and 'fruits' in v['state']:
        v['state']['fruits'].sort(key=lambda f:json.dumps(f,sort_keys=True))
    return v


def compare_trace(reference, candidate):
    a,b=rows(reference),rows(candidate)
    root_equal=event_value(a[0])==event_value(b[0])
    def first(evt,fields):
        aa=[r for r in a if r['evt']==evt];bb=[r for r in b if r['evt']==evt]
        for i,(x,y) in enumerate(zip(aa,bb)):
            if fields(x)!=fields(y):
                keys=sorted(k for k in set(fields(x))|set(fields(y)) if fields(x).get(k)!=fields(y).get(k))
                return dict(ordinal=i+1,tick_A=x.get('tick'),tick_B=y.get('tick'),different_fields=keys)
        if len(aa)!=len(bb):return dict(ordinal=min(len(aa),len(bb))+1,different_fields=['event_count'])
        return None
    return dict(initial_logged_state_rng_tick_equal=root_equal,
        first_release_difference=first('release',event_value),
        first_action_difference=first('action',event_value),
        first_physical_release_difference=first('release',physical_value),
        first_physical_action_difference=first('action',physical_value),
        first_search_difference=first('decision',lambda r:dict(tick=r['tick'],root=r['search']['root'],
                 selected=r['planning']['selected_x'])),
        first_chosen_action_difference=first('decision',lambda r:dict(selected=r['planning']['selected_x'])),
        release_ticks_equal=[r['tick'] for r in a if r['evt']=='release']==[r['tick'] for r in b if r['evt']=='release'])


def choose_index(candidates, mode):
    valid=[c for c in candidates if c['visits']>0 and c['drop_success'] and not c['immediate_go']]
    if not valid:return None
    if mode=='C_max_mean':
        # Explicit diagnostic tie rule, rather than claiming this is legacy final selection.
        return max(valid,key=lambda c:(c['mean_points'],c['visits'],-c['index']))['index']
    best=valid[0]
    for c in valid[1:]:
        if c['visits']>best['visits'] or (c['visits']==best['visits'] and c['mean_points']>best['mean_points']+.001):best=c
    return best['index']


def audit(session,out):
    session,out=Path(session),Path(out);out.mkdir(parents=True,exist_ok=False)
    observations=[];identities={};references={};divergences=[];conditions={};plans={};inputs={};protocol=None
    selectors={};selection_statistics=[];baseline_samples=[]
    for batch in sorted(session.glob('batch_*')):
        plan=json.loads((batch/'plan.json').read_text());report=json.loads((batch/'teacher.json').read_text())
        plans[batch.name]=dict(path=str((batch/'plan.json').resolve()),sha256=sha(batch/'plan.json'))
        roots={r['id']:r for r in plan['roots']}
        proto=json.loads((batch/'dataset_protocol.json').read_text())
        if protocol is None:protocol=proto
        elif proto!=protocol:raise ValueError('Conflicting development split protocols across repetitions')
        for row in rows(batch/'dataset_final/ranking.jsonl'):
            if row['provenance']['report']==str((batch/'teacher.json').resolve()):
                seed=row['provenance']['source_seed'];old=inputs.setdefault(seed,row)
                if old['input']!=row['input']:raise ValueError('Input drift across repeated declarations')
        games={(g['root_id'],g['future_seed'],g['role']):g for g in report['games']}
        valid={(p['root_id'],p['future_seed']):p['valid_conditional_return_pair'] for p in report['pairs']}
        for root in plan['roots']:
            sel=json.loads((batch/(root['id']+'_selection.json')).read_text())
            selectors[(batch.name,root['source_seed'])]=sel
            selection_statistics.append(dict(batch=batch.name,source_seed=root['source_seed'],root_id=root['id'],**sel,
                C_index=choose_index(sel['candidates'],'C_max_mean'),D_index=choose_index(sel['candidates'],'D_max_visits')))
        for game in report['games']:
            root=roots[game['root_id']];condition=trial_identity(plan,root,game['future_seed'],game['first_x']);key=digest(condition)
            trace=Path(game['trajectory']);launch=json.loads((trace.parent/'launch.json').read_text())
            commit=json.loads((trace.parents[2]/'completion.json').read_text())
            result_path=trace.parent/commit.get('result_name','result.json')
            if commit['trace_sha256']!=sha(trace) or commit['result_sha256']!=sha(result_path):
                raise ValueError('Committed raw artifacts changed')
            result=json.loads(result_path.read_text())
            if result['natural_go']!=game['natural_go'] or result.get('process_error'):
                raise ValueError('Teacher summary disagrees with native completion')
            decision=None;initial=None
            with trace.open() as stream:
                for line in stream:
                    row=json.loads(line)
                    if row['evt']=='root':initial=row
                    if row['evt']=='decision':decision=row;break
            sample=dict(batch=batch.name,source_seed=root['source_seed'],source_initial_sequence=root['source_initial_sequence'],
                board_uid=root['board_uid'],snapshot=condition['snapshot'],role=game['role'],coordinate=game['first_x'],
                future_seed=game['future_seed'],condition_id=key,natural_go=game['natural_go'],
                valid_pair=valid[(game['root_id'],game['future_seed'])],actual_return=game['actual_return'],
                accepted_drops=game['accepted_drops'],wall_seconds=game['wall_seconds'],
                new_watermelons=game['new_watermelons'],second_watermelon=game['second_watermelon'],
                two_present=game['two_present'],doubles=game['doubles'],trajectory=str(trace),
                trace_sha256=sha(trace),initial_tick=initial['tick'],initial_rng=initial['rng'],
                actual_initial_search_matches_frozen_survey=decision['search']['root']==selectors[(batch.name,root['source_seed'])]['candidates'],
                launch_player={k:launch.get(k) for k in ['exe_sha256','assembly_sha256']})
            observations.append(sample);conditions.setdefault(key,[]).append(sample);identities[key]=condition
            ref=references.setdefault(key,str(trace))
            if ref!=str(trace):divergences.append(dict(condition_id=key,batch=batch.name,source_seed=root['source_seed'],
                future_seed=game['future_seed'],role=game['role'],reference=ref,candidate=str(trace),**compare_trace(ref,trace)))
        for future in plan['future_seeds']:
            for root in plan['roots']:
                a=games[(root['id'],future,'recommended')];b=games[(root['id'],future,'alternative')]
                sel=selectors[(batch.name,root['source_seed'])]
                indices={'A_MCTS':sel['recommended_index'],'B_alternative':sel['alternative_index'],
                         'C_max_mean':choose_index(sel['candidates'],'C_max_mean'),'D_max_visits':choose_index(sel['candidates'],'D_max_visits')}
                for name,index in indices.items():
                    role='recommended' if index==sel['recommended_index'] else 'alternative' if index==sel['alternative_index'] else None
                    g=a if role=='recommended' else b if role else None
                    baseline_samples.append(dict(batch=batch.name,source_seed=root['source_seed'],future_seed=future,method=name,
                        selected_index=index,observed=g is not None and g['natural_go'] and valid[(root['id'],future)],
                        actual_return=g['actual_return'] if g and g['natural_go'] and valid[(root['id'],future)] else None,
                        difference_from_A=g['actual_return']-a['actual_return'] if g and g['natural_go'] and valid[(root['id'],future)] else None))
    pairs=[];rootsummary=[];ranking=[]
    seeds=sorted({r['source_seed'] for r in observations})
    for seed in seeds:
        futures=sorted({r['future_seed'] for r in observations if r['source_seed']==seed});rootpairs=[]
        for future in futures:
            os=[r for r in observations if r['source_seed']==seed and r['future_seed']==future]
            reps=[]
            for batch in sorted({r['batch'] for r in os}):
                rr={r['role']:r for r in os if r['batch']==batch};a,b=rr['recommended'],rr['alternative']
                reps.append(dict(batch=batch,return_A=a['actual_return'],return_B=b['actual_return'],
                    delta_B_minus_A=b['actual_return']-a['actual_return'] if a['valid_pair'] and b['valid_pair'] else None,
                    drops_A=a['accepted_drops'],drops_B=b['accepted_drops']))
            item=dict(source_seed=seed,future_seed=future,**pair_statistics(reps))
            if item['valid_repetitions']==0:raise ValueError('No natural-GO comparable measurements for a declared condition')
            pairs.append(item);rootpairs.append(item)
        deltas=[r['mean_delta'] for r in rootpairs]
        rootsummary.append(dict(source_seed=seed,mean_delta=avg(deltas),future_sd=sd(deltas),
            mean_return_A=avg([r['mean_return_A'] for r in rootpairs]),mean_return_B=avg([r['mean_return_B'] for r in rootpairs]),
            future_rank_flip=any(d>0 for d in deltas) and any(d<0 for d in deltas)))
        row=inputs[seed]
        ranking.append(dict(schema='repeated-root-paired-return-v1',root_uid=row['root_uid'],input=row['input'],
            target=dict(mean_delta_B_minus_A=avg(deltas),mean_return_A=rootsummary[-1]['mean_return_A'],mean_return_B=rootsummary[-1]['mean_return_B']),
            uncertainty=dict(future_conditions=len(futures),repetitions_per_future=[r['valid_repetitions'] for r in rootpairs],
                mean_delta_per_future=deltas,future_sd=sd(deltas),repeat_sd_per_future=[r['sd_delta'] for r in rootpairs],true_optimal_label=False),
            provenance=row['provenance'],source_group=row['source_group'],split=row['split'],
            training_weight=1,teacher_scope='conditional on approximate reconstruction and fixed legacy continuation; development only'))
    grouped_splits(ranking,protocol)
    baselines={}
    for name in ['A_MCTS','B_alternative','C_max_mean','D_max_visits']:
        subset=[r for r in baseline_samples if r['method']==name];good=[r for r in subset if r['observed']]
        byseed={s:[r for r in good if r['source_seed']==s] for s in seeds}
        baselines[name]=dict(observed_evaluations=len(good),unobserved_evaluations=len(subset)-len(good),
            independent_groups_with_observations=sum(bool(v) for v in byseed.values()),
            mean_return_source_macro=avg([avg([r['actual_return'] for r in rs]) for rs in byseed.values() if rs]),
            mean_gain_source_macro=avg([avg([r['difference_from_A'] for r in rs]) for rs in byseed.values() if rs]),
            note='Unexecuted coordinates missing, never imputed; subset comparisons must use matched support.')
    varied=[k for k,rs in conditions.items() if len({r['actual_return'] for r in rs})>1]
    summary=dict(games=len(observations),natural_go=sum(r['natural_go'] for r in observations),independent_source_groups=len({r['source_group'] for r in ranking}),
        independent_boards=len({r['snapshot'] for r in observations}),paired_conditions=len(pairs),
        action_conditions=len(conditions),repetitions=sorted({len(rs) for rs in conditions.values()}),
        action_conditions_with_different_returns=len(varied),compared_repeat_to_first=len(divergences),
        return_differences_vs_first=sum(next(x for x in conditions[r['condition_id']] if x['batch']==r['batch'])['actual_return']!=conditions[r['condition_id']][0]['actual_return'] for r in divergences),
        initial_mismatch_vs_first=sum(not r['initial_logged_state_rng_tick_equal'] for r in divergences),
        initial_search_mismatch=sum(not r['actual_initial_search_matches_frozen_survey'] for r in observations),
        raw_logged_divergences=sum(r['first_search_difference'] is not None or r['first_release_difference'] is not None for r in divergences),
        physical_or_timing_divergences=sum(r['first_physical_release_difference'] is not None or r['first_physical_action_difference'] is not None for r in divergences),
        roots=rootsummary,baselines=baselines,
        batch_results={b:dict(natural_go=sum(r['natural_go'] for r in observations if r['batch']==b),
            mean_delta=avg([r['difference_from_A'] for r in baseline_samples if r['batch']==b and r['method']=='B_alternative' and r['observed']]),
            B_wins=sum(r['difference_from_A']>0 for r in baseline_samples if r['batch']==b and r['method']=='B_alternative' and r['observed'])) for b in plans},
        plans=plans,models_trained=False,independent_test_groups=0,
        weighting='Average repetitions within each future, then futures within root; source group macro. Each root weight 1, not 4.',
        hidden_solver_state_known=False)
    for name,value in [('audit.json',summary),('pair_repetitions.json',pairs),('divergences.json',divergences),('selectors.json',selection_statistics),('baseline_observations.json',baseline_samples)]:write(out/name,value)
    with (out/'observations.csv').open('x',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(observations[0]));writer.writeheader();writer.writerows(observations)
    flat=[]
    for pair in pairs:
        row={k:v for k,v in pair.items() if k!='repetitions'}
        for rep in pair['repetitions']:
            for field in ['return_A','return_B','delta_B_minus_A']:row[rep['batch']+'_'+field]=rep[field]
        flat.append(row)
    with (out/'paired_conditions.csv').open('x',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    write(out/'split_manifest.json',dict(roots=len(ranking),independent_groups=len({r['source_group'] for r in ranking}),
        splits={s:[r['provenance']['source_seed'] for r in ranking if r['split']==s] for s in sorted({r['split'] for r in ranking})},
        independent_test_groups=0,root_weight=1,replicates_do_not_increase_weight=True,
        protocol=protocol,models_trained=False))
    for name,rs in [('observations.jsonl',observations),('ranking.jsonl',ranking)]:
        with (out/name).open('x',encoding='utf8') as f:
            for row in rs:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    print(json.dumps(audit(a.session,a.output),ensure_ascii=False,indent=2))
