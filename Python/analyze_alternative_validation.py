"""Separate first-action branches from every-turn alternative policy games."""
import argparse
import json
import random
import statistics
from pathlib import Path

from branch_action_teacher import compare_trials,records
from watermelon_lab import write


def avg(xs):return statistics.mean(xs) if xs else None
def stdev(xs):return statistics.stdev(xs) if len(xs)>1 else None
def percentile(xs,p):
    xs=sorted(xs)
    if not xs:return None
    at=(len(xs)-1)*p;lo=int(at);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(at-lo)


def root_bootstrap(deltas,seed=20261104,n=10000):
    if len(deltas)<2:return None
    rng=random.Random(seed);values=sorted(avg(rng.choices(deltas,k=len(deltas))) for _ in range(n))
    return [percentile(values,.025),percentile(values,.975)]


def analyze(study,out):
    study,out=Path(study),Path(out);out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((study/'branch_unseen_08/plan.json').read_text());teacher=json.loads((study/'branch_unseen_08/teacher.json').read_text())
    expected=len(plan['roots'])*len(plan['future_seeds'])*2;valid=[p for p in teacher['pairs'] if p['valid_conditional_return_pair']]
    games={(g['root_id'],g['future_seed'],g['role']):g for g in teacher['games']};roots=[];pairs=[]
    for root in plan['roots']:
        selection_file=study/'branch_unseen_08'/(root['id']+'_selection.json')
        selection=json.loads(selection_file.read_text()) if selection_file.exists() else None
        rp=[p for p in valid if p['root_id']==root['id']];deltas=[];drop_deltas=[]
        for pair in rp:
            a=games[(root['id'],pair['future_seed'],'recommended')];b=games[(root['id'],pair['future_seed'],'alternative')]
            delta=pair['alternative_minus_recommended'];deltas.append(delta);drop_deltas.append(b['accepted_drops']-a['accepted_drops'])
            pairs.append(dict(root_id=root['id'],source_seed=root['source_seed'],future_seed=pair['future_seed'],
                A_return=a['actual_return'],B_return=b['actual_return'],B_minus_A=delta,
                A_drops=a['accepted_drops'],B_drops=b['accepted_drops'],drop_difference=drop_deltas[-1],
                A_seconds=a['wall_seconds'],B_seconds=b['wall_seconds'],
                A_new_watermelons=a['new_watermelons'],B_new_watermelons=b['new_watermelons'],
                A_second=a['second_watermelon'],B_second=b['second_watermelon'],
                A_coexist=a['two_present'],B_coexist=b['two_present'],A_doubles=a['doubles'],B_doubles=b['doubles'],
                shared_observed_fruits=pair['comparison']['common_public_fruit_count'],
                shared_fruits_equal=pair['comparison']['common_public_fruits_equal'],initial_equal=pair['all_logged_initial_fields_equal']))
        roots.append(dict(root_id=root['id'],source_seed=root['source_seed'],phase=root['phase'],selection=selection,
            paired_futures=len(rp),planned_futures=len(plan['future_seeds']),complete=len(rp)==len(plan['future_seeds']),
            mean_delta=avg(deltas),sd_across_futures=stdev(deltas),mean_drop_difference=avg(drop_deltas),
            future_rank_flip=any(d>0 for d in deltas) and any(d<0 for d in deltas)))
    full=[r for r in roots if r['complete']];ds=[r['mean_delta'] for r in full]
    balanced_future_cohorts=[]
    for future in plan['future_seeds']:
        cohort=[p for p in pairs if p['future_seed']==future]
        deltas=[p['B_minus_A'] for p in cohort]
        balanced_future_cohorts.append(dict(future_seed=future,paired_roots=len(cohort),all_planned_roots_complete=len(cohort)==len(plan['roots']),
            mean_delta=avg(deltas),B_favorable=sum(d>0 for d in deltas),
            note='Single shared future series; not a replacement for two-future evaluation. Partial cohort coverage explicitly shown.'))
    branch=dict(planned_games=expected,recorded_games=len(teacher['games']),natural_go=sum(g['natural_go'] for g in teacher['games']),
        missing=teacher['missing'],invalid_pairs=[p for p in teacher['pairs'] if not p['valid_conditional_return_pair']],
        complete_independent_roots=len(full),B_favorable_complete_roots=sum(d>0 for d in ds),A_favorable_complete_roots=sum(d<0 for d in ds),
        root_macro_mean_delta=avg(ds),root_sd=stdev(ds),root_bootstrap_95ci=root_bootstrap(ds),
        balanced_future_cohorts=balanced_future_cohorts,
        roots=roots,pairs=pairs,
        primary_scope='Only roots with both planned futures complete. Partial roots listed, never silently dropped or assigned zero.',
        warning='Approximate reconstruction, fixed legacy continuation, two shared future seeds. Bootstrap is exploratory at small root count; not optimal-action labels.')
    normal=[];normal_rows={}
    for selector in ['legacy','alternative']:
        p=study/('normal_'+selector)
        if not (p/'result.json').exists():continue
        result=json.loads((p/'result.json').read_text());rs=records(p/'trace.jsonl');normal_rows[selector]=rs
        ds=[r for r in rs if r['evt']=='decision'];times=[r['planning_ms'] for r in ds]
        positions={str(x):sum(r['command']['x']==x for r in ds) for x in [0,.25,.5,.75,1]}
        last=result['end']
        normal.append(dict(selector=selector,seed=result['game_seed'],natural_go=result['natural_go'],
            final_score=last['score'] if last and result['natural_go'] else None,
            observed_score=last['score'] if last else None,drops=last['accepted_drops'] if last else None,
            seconds=result['wall_seconds'],mean_planning_ms=avg(times),p95_planning_ms=percentile(times,.95),
            decisions=len(ds),fallback_decisions=result['fallback_decisions'],selected_positions=positions,
            new_watermelons=last['new_watermelons'] if last else None,
            coexist=last['two_watermelons_present'] if last else None,doubles=last['double_watermelons'] if last else None,
            reason=last['reason'] if last else result['process_error'],
            max_retained_scenes=max(r['retained_scenes'] for r in rs),max_pending_unloads=max(r['pending_unloads'] for r in rs)))
    comparison=compare_trials(normal_rows['legacy'],normal_rows['alternative']) if len(normal_rows)==2 else None
    report=dict(branch=branch,normal_every_turn=normal,normal_comparison=comparison,
        normal_warning='One development seed only; every-turn B changes continuation, unlike first-action branch results.',models_trained=False)
    write(out/'analysis.json',report)
    write(out/'branch_summary.json',branch)
    write(out/'normal_summary.json',dict(games=normal,comparison=comparison))
    print(json.dumps(dict(branch_games=branch['recorded_games'],natural_go=branch['natural_go'],complete_roots=len(full),
        mean_delta=branch['root_macro_mean_delta'],B_favorable=branch['B_favorable_complete_roots'],
        normal=[{k:r[k] for k in ['selector','natural_go','final_score','drops','seconds']} for r in normal]),indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();analyze(a.study,a.output)
