"""Development-only paired return dataset and root-level ranking metrics.

No fitting, model selection, or reservation of an already inspected root as Test.
"""
import argparse
import json
import statistics
from pathlib import Path

from watermelon_lab import write,sha
from branch_teacher_batch import fingerprint
from export_branch_teacher import example


def mean(xs):return statistics.mean(xs) if xs else None


def prepare_protocol(batch,prior_seeds=None):
    batch=Path(batch);plan=json.loads((batch/'plan.json').read_text())
    if any((batch/'tasks').glob('*_f[0-9]*')):
        raise ValueError('Freeze development split before main branch trials start')
    roots=plan['roots'];cut=len(roots)//2
    prior=Path(__file__).resolve().parent/'outputs/branch_teacher_jobs18_29_01/plan.json'
    if prior_seeds is None:prior_seeds=[r['source_seed'] for r in json.loads(prior.read_text())['roots']]
    protocol=dict(version='branch-ranking-development-v1',fixed_before_main_outcomes=True,
        new_development_train=[r['source_seed'] for r in roots[:cut]],
        new_development_validation=[r['source_seed'] for r in roots[cut:]],
        prior_development_train=prior_seeds,
        independent_test=[],assignment_rule='Frozen root order: first half development Train, remaining development Validation',
        note='No independent Test; union seed OR initial8 before assignment; no label-dependent split changes')
    write(batch/'dataset_protocol.json',protocol)
    return protocol


def grouped_splits(rows,protocol):
    parent=list(range(len(rows)));seen={}
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,r in enumerate(rows):
        for key in r['provenance']['split_keys']:
            if key in seen:parent[find(i)]=find(seen[key])
            else:seen[key]=i
    train=set(protocol['new_development_train']+protocol['prior_development_train'])
    val=set(protocol['new_development_validation']);components={}
    for i,r in enumerate(rows):components.setdefault(find(i),[]).append(r)
    for group in components.values():
        seeds={r['provenance']['source_seed'] for r in group}
        choices=set()
        if seeds&train:choices.add('development_train')
        if seeds&val:choices.add('development_validation')
        if len(choices)!=1:raise ValueError('Unknown group or planned Train/Validation leakage through seed/initial8')
        keys=sorted({k for r in group for k in r['provenance']['split_keys']});gid=fingerprint(keys)
        for r in group:r['split']=next(iter(choices));r['source_group']=gid
    return rows


def evaluate(rows,predictions,return_difference_prediction=True):
    """Each row is one root (not one future, frame, or candidate). B-A convention."""
    results=[]
    for row in rows:
        uid=row['root_uid'];score=predictions[uid]
        a=row['target']['mean_return_A'];b=row['target']['mean_return_B'];delta=b-a
        choose_b=score>0;selected=b if choose_b else a
        results.append(dict(source_group=row['source_group'],correct=(choose_b==(delta>0)) if delta!=0 else None,
                            selected=selected,gain=selected-a,regret=max(a,b)-selected,
                            absolute_error=abs(score-delta)))
    by_group={}
    for r in results:by_group.setdefault(r['source_group'],[]).append(r)
    def macro(field):
        values=[mean([r[field] for r in rs if r[field] is not None]) for rs in by_group.values()]
        return mean([v for v in values if v is not None])
    return dict(roots=len(rows),independent_source_groups=len(by_group),
                ranking_accuracy=macro('correct'),
                root_macro_ranking_accuracy=mean([r['correct'] for r in results if r['correct'] is not None]),
                tied_target_roots=sum(r['correct'] is None for r in results),
                mean_selected_return=macro('selected'),
                mean_gain_vs_MCTS_A=macro('gain'),
                mean_regret_to_observed_best_of_two=macro('regret'),
                delta_MAE=macro('absolute_error') if return_difference_prediction else None,
                note='Finite future-sample returns under recorded continuation; not true best action. Metrics are development diagnostics, not held-out Test.')


def evaluate_learning_seeds(rows,predictions_by_seed):
    metrics={str(seed):evaluate(rows,pred) for seed,pred in predictions_by_seed.items()}
    accuracies=[m['ranking_accuracy'] for m in metrics.values() if m['ranking_accuracy'] is not None]
    return dict(per_learning_seed=metrics,learning_seeds=len(metrics),
                mean_ranking_accuracy=mean(accuracies),
                sd_ranking_accuracy=statistics.stdev(accuracies) if len(accuracies)>1 else None,
                fraction_roots_with_changed_choice=mean([len({pred[r['root_uid']]>0 for pred in predictions_by_seed.values()})>1 for r in rows]) if predictions_by_seed else None,
                note='Accepts frozen predictions; does not train or tune a model.')


def load_dataset(path,split=None):
    rows=[json.loads(l) for l in Path(path).open(encoding='utf8') if l.strip()]
    if any(r['split']=='test' for r in rows):raise ValueError('These inspected roots cannot be independent Test')
    groups={}
    for row in rows:
        groups.setdefault(row['source_group'],set()).add(row['split'])
        if set(row['input'])!={'state','coordinates_A_B','mcts_statistics_A_B'}:raise ValueError('Unexpected model input fields')
        allowed={'fruits','current_fruit','next_fruit_type','score','game_over','drop_cooldown_remaining','ai_move_speed','fixed_delta_time','geometry'}
        if set(row['input']['state'])!=allowed:raise ValueError('Unexpected/future state features')
    if any(len(v)!=1 for v in groups.values()):raise ValueError('Source group crosses splits')
    return [r for r in rows if split is None or r['split']==split]


def build(batch,out,include_prior=True):
    batch=Path(batch);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    protocol=json.loads((batch/'dataset_protocol.json').read_text())
    frozen_roots=json.loads((batch/'plan.json').read_text())['roots'];cut=len(frozen_roots)//2
    if protocol['new_development_train']!=[r['source_seed'] for r in frozen_roots[:cut]] or protocol['new_development_validation']!=[r['source_seed'] for r in frozen_roots[cut:]]:
        raise ValueError('Development split differs from the frozen root-order rule')
    reports=[batch/'teacher.json']
    if include_prior:reports.append(Path(__file__).resolve().parent/'outputs/branch_teacher_jobs18_29_01/teacher.json')
    units={};observations=[];excluded=[];duplicate_keys=set();policies=set();action_examples=[];report_identities=[]
    for rp in reports:
        raw=rp.read_bytes();report=json.loads(raw);report_identities.append(dict(path=str(rp.resolve()),sha256=__import__('hashlib').sha256(raw).hexdigest()))
        games={(g['root_id'],g['future_seed'],g['role']):g for g in report['games']}
        for pair in report['pairs']:
            if not pair['valid_conditional_return_pair']:
                excluded.append(dict(report=str(rp),root=pair['root_id'],future=pair['future_seed'],reason='censored or noncomparable pair'));continue
            gg=[games[(pair['root_id'],pair['future_seed'],role)] for role in ['recommended','alternative']]
            rr=[]
            for g in gg:
                root=None;decision=None
                with Path(g['trajectory']).open() as f:
                    for line in f:
                        r=json.loads(line)
                        if r['evt']=='root':root=r
                        if r['evt']=='decision':decision=r;break
                rr.append(root)
                launch=json.loads((Path(g['trajectory']).parent/'launch.json').read_text())
                g['player_identity']={k:launch[k] for k in ['exe_sha256','assembly_sha256']}
                g['actual_planner_settings']=decision['planning']['settings']
            if rr[0]['state']!=rr[1]['state'] or rr[0]['rng']!=rr[1]['rng'] or rr[0]['tick']!=rr[1]['tick']:
                excluded.append(dict(root=pair['root_id'],future=pair['future_seed'],reason='full initial state/RNG/tick mismatch'));continue
            aa=[example(g,r['state'],True) for g,r in zip(gg,rr)]
            if not all(e['eligible_observed_return'] for e in aa):raise ValueError('Invalid committed pair marked eligible')
            state=aa[0]['input']['state'];observed_uid=fingerprint(state)
            policy_id=fingerprint(dict(continuation=pair['continuation'],player=gg[0]['player_identity']))
            policies.add(policy_id)
            uid=fingerprint(dict(source_seed=gg[0]['source_seed'],state=state,policy=policy_id,
                                 candidates=[g['first_x'] for g in gg]))
            key=(uid,pair['future_seed'])
            if key in duplicate_keys:raise ValueError('Repeated root/future is not an independent sample')
            duplicate_keys.add(key)
            for e in aa:e['provenance']['source_report']=str(rp.resolve())
            action_examples+=aa
            # If a declared root changes visible state across futures, do not blend it.
            declared=(str(rp),pair['root_id']);old=units.setdefault(declared,observed_uid)
            if old!=observed_uid:raise ValueError('Declared root changed visible initial state across future seeds')
            selection_path=rp.parent/(pair['root_id']+'_selection.json')
            selection=json.loads(selection_path.read_text())
            stats=[]
            for g in gg:
                e=next(e for e in selection['candidates'] if e['x']==g['first_x'])
                stats.append({k:e[k] for k in ['x','visits','mean_points','sd_points','terminal_returns','immediate_go']})
            observations.append(dict(root_uid=uid,input=dict(state=state,coordinates_A_B=[g['first_x'] for g in gg],mcts_statistics_A_B=stats),
                future=dict(seed=pair['future_seed'],return_A=gg[0]['actual_return'],return_B=gg[1]['actual_return'],delta_B_minus_A=pair['alternative_minus_recommended'],
                    outcome_A={k:gg[0][k] for k in ['natural_go','accepted_drops','new_watermelons','second_watermelon','two_present','doubles','wall_seconds']},
                    outcome_B={k:gg[1][k] for k in ['natural_go','accepted_drops','new_watermelons','second_watermelon','two_present','doubles','wall_seconds']}),
                provenance=dict(root_id=pair['root_id'],source_seed=gg[0]['source_seed'],source_initial_sequence=gg[0]['source_initial_sequence'],
                    phase=gg[0].get('phase','after'),initial_watermelons=gg[0]['initial_watermelons'],
                    split_keys=gg[0]['split_keys'],continuation=pair['continuation'],policy_id=policy_id,
                    source='actual_experimental_continuation',restoration='approximate_cold',
                    report=str(rp.resolve()),trajectories=[g['trajectory'] for g in gg],reproducibility=gg[0]['reproducibility'])))
    if len(policies)>1:raise ValueError('Continuation/Player policies differ; separate datasets before fitting')
    by_root={}
    for r in observations:by_root.setdefault(r['root_uid'],[]).append(r)
    dataset=[]
    for uid,samples in by_root.items():
        delta=[r['future']['delta_B_minus_A'] for r in samples];a=[r['future']['return_A'] for r in samples];b=[r['future']['return_B'] for r in samples]
        dataset.append(dict(schema='root-paired-return-v1',root_uid=uid,input=samples[0]['input'],
             target=dict(mean_return_A=mean(a),mean_return_B=mean(b),mean_delta_B_minus_A=mean(delta),
                         empirical_probability_A_better=sum(d<0 for d in delta)/len(delta),
                         empirical_probability_B_better=sum(d>0 for d in delta)/len(delta),tie_fraction=sum(d==0 for d in delta)/len(delta)),
             uncertainty=dict(future_samples=len(delta),sd_delta=statistics.stdev(delta) if len(delta)>1 else None,
                              min_delta=min(delta),max_delta=max(delta),rank_flip=any(d>0 for d in delta) and any(d<0 for d in delta),
                              calibrated_probability=False,true_optimal_label=False),
             future_outcomes=[r['future'] for r in samples],provenance=samples[0]['provenance']))
    grouped_splits(dataset,protocol)
    with (out/'ranking.jsonl').open('x',encoding='utf8') as f:
        for r in dataset:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    with (out/'action_examples.jsonl').open('x',encoding='utf8') as f:
        for r in action_examples:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    # The loader itself audits the saved file, including group boundaries.
    restored=load_dataset(out/'ranking.jsonl');metrics={}
    for split in ['development_train','development_validation']:
        rows=[r for r in restored if r['split']==split]
        selected={r['root_uid']:-1 for r in rows}
        mcts_mean={r['root_uid']:r['input']['mcts_statistics_A_B'][1]['mean_points']-r['input']['mcts_statistics_A_B'][0]['mean_points'] for r in rows}
        metrics[split]=dict(MCTS_selected_A=evaluate(rows,selected,False),MCTS_mean_ranking=evaluate(rows,mcts_mean,False))
    write(out/'baseline_metrics.json',metrics)
    manifest=dict(root_rows=len(dataset),action_examples=len(action_examples),future_pairs=len(observations),
                  independent_source_groups=len({r['source_group'] for r in dataset}),
                  new_batch_source_groups=len({r['source_group'] for r in dataset if r['provenance']['report']==str(reports[0].resolve())}),
                  prior_development_source_groups=len({r['source_group'] for r in dataset if r['provenance']['report']!=str(reports[0].resolve())}),
                  new_batch_action_examples=sum(e['provenance']['source_report']==str(reports[0].resolve()) for e in action_examples),
                  splits={s:dict(roots=sum(r['split']==s for r in dataset),source_groups=len({r['source_group'] for r in dataset if r['split']==s})) for s in ['development_train','development_validation']},
                  independent_test_roots=0,rank_flip_roots=sum(r['uncertainty']['rank_flip'] for r in dataset),
                  reports=report_identities,excluded=excluded,
                  policy_ids=sorted(policies),protocol=protocol,model_training_performed=False,
                  warning='Only development data. Per-future win fractions at n=2 are not calibrated probabilities. Future outcomes/provenance are labels/metadata, never model inputs.')
    write(out/'manifest.json',manifest);print(json.dumps(manifest,ensure_ascii=False))
    return dataset


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path,required=True);p.add_argument('--output',type=Path)
    p.add_argument('--prepare-protocol',action='store_true');p.add_argument('--without-prior',action='store_true');a=p.parse_args()
    if a.prepare_protocol:print(json.dumps(prepare_protocol(a.batch)))
    elif a.output is None:p.error('--output required to build dataset')
    else:build(a.batch,a.output,not a.without_prior)


if __name__=='__main__':main()
