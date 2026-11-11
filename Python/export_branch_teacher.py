"""Export observation/action/outcome examples; never fits a model or edits raw logs."""
import argparse
import hashlib
import json
from pathlib import Path
from watermelon_lab import write


def example(game, root_state, comparable):
    # Experimental future seed/RNG, final score, and events are NEVER input features.
    observation = {k: root_state[k] for k in ['fruits', 'current_fruit', 'next_fruit_type', 'score',
                   'game_over', 'drop_cooldown_remaining', 'ai_move_speed', 'fixed_delta_time', 'geometry']}
    root_uid=hashlib.sha256(json.dumps(observation,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    known = bool(game['natural_go'])
    return dict(schema='conditional-action-return-v1',
                input=dict(state=observation, normalized_x=game['first_x']),
                labels=dict(additional_score=game['actual_return'], outcome_known=known,
                            new_watermelons=game['new_watermelons'] if known else None,
                            second_watermelon=game['second_watermelon'] if known else None,
                            two_present=game['two_present'] if known else None,
                            double_count=game['doubles'] if known else None),
                eligible_observed_return=known and comparable and game['source_unchanged'] and game['all_iterations_correct'],
                provenance=dict(root_id=game['root_id'], observed_root_uid=root_uid, source_seed=game['source_seed'],
                     source_initial_sequence=game['source_initial_sequence'], split_keys=game['split_keys'],
                     future_seed=game['future_seed'], continuation=game['continuation'],
                     player_identity=game.get('player_identity'),
                     actual_planner_settings=game.get('actual_planner_settings'),
                     source=game['source'], restoration=game['approximation'], trajectory=game['trajectory'],
                     strict_historical_counterfactual=False, observed_return_under_recorded_policy=True,
                     reserved_split='development_diagnostic_do_not_promote_to_independent_test'))


def export(folder):
    report = json.loads((folder / 'teacher.json').read_text())
    comparisons = {(p['root_id'],p['future_seed']):p for p in report['pairs']}
    examples, roots, strict = [], {}, {}
    for game in report['games']:
        with Path(game['trajectory']).open() as f:
            root, decision = None, None
            for line in f:
                row=json.loads(line)
                if row['evt']=='root':root=row
                if row['evt']=='decision':decision=row;break
        if root is None or decision is None:raise ValueError('Missing initial root/actual planner settings')
        launch=json.loads((Path(game['trajectory']).parent/'launch.json').read_text())
        game['player_identity']={k:launch[k] for k in ['exe_sha256','assembly_sha256']}
        game['actual_planner_settings']=decision['planning']['settings']
        roots[(game['root_id'],game['future_seed'],game['role'])] = root
    for key,pair in comparisons.items():
        a,b=(roots[(*key,role)] for role in ['recommended','alternative'])
        # Include held x/y, cooldown, angular velocities and all recorded metadata,
        # beyond the compact position/velocity summary in the study report.
        strict[key]=dict(all_logged_initial_state_fields_equal=a['state']==b['state'],
                         initial_relative_tick_equal=a['tick']==b['tick'],
                         initial_game_rng_equal=a['rng']==b['rng'])
    for game in report['games']:
        root=roots[(game['root_id'],game['future_seed'],game['role'])]
        pair = comparisons.get((game['root_id'],game['future_seed']))
        checked=strict.get((game['root_id'],game['future_seed']),{})
        comparable = bool(pair and pair['valid_conditional_return_pair'] and checked and all(checked.values()))
        examples.append(example(game,root['state'],comparable))
    with (folder/'examples.jsonl').open('x',encoding='utf8') as f:
        for row in examples:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    groups = {}
    for pair in report['pairs']:
        if pair['valid_conditional_return_pair'] and all(strict[(pair['root_id'],pair['future_seed'])].values()):
            groups.setdefault(pair['root_id'],[]).append(pair)
    write(folder/'strict_initial_checks.json',[dict(root_id=r,future_seed=f,**v) for (r,f),v in strict.items()])
    write(folder/'pair_targets.json',dict(schema='paired-action-difference-v1',groups=[
        dict(root_id=root,split_keys=ps[0]['split_keys'],continuation=ps[0]['continuation'],
             future_samples=len(ps),per_future=[dict(future_seed=p['future_seed'],difference=p['alternative_minus_recommended']) for p in ps],
             mean_alternative_minus_recommended=sum(p['alternative_minus_recommended'] for p in ps)/len(ps),
             true_optimal_action_label=False) for root,ps in groups.items()],
        split_rule=report['source_group_rule'],model_training_performed=False))
    print(json.dumps(dict(examples=len(examples),eligible=sum(e['eligible_observed_return'] for e in examples),independent_roots=len(groups))))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    export(p.parse_args().output)


if __name__=='__main__':main()
