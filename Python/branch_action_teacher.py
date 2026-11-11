"""First-action counterfactuals in declared cold Watermelon Lab fixtures.

No learning, historical replay claim, planner changes, or implicit seed replacement.
Each fresh process uses the existing Player's baseline MCTS mode.
"""
import argparse
import csv
import json
import math
import statistics
import subprocess
import time
from pathlib import Path

from watermelon_lab import ROOT, public_difference, sha, summarize, write
from prepare_candidate_fixtures import fixture
from staged_action_experiment import choose_alternative
from compare_watermelon_dynamic import active_players


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def records(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def policy(config):
    if config.get('kind') != 'legacy_mcts':
        raise ValueError('Only an explicitly recorded legacy_mcts continuation is supported by this Player')
    if type(config['iterations']) is not int or not 32 <= config['iterations'] <= 256:
        raise ValueError('Existing Lab supports bounded 32..256 iteration continuation')
    if type(config['depth']) is not int or not 2 <= config['depth'] <= 16:
        raise ValueError('Lab depth must be 2..16')
    if type(config['search_seed']) is not int or not 0 <= config['search_seed'] <= 2147483647:
        raise ValueError('Invalid search seed')
    return dict(config, candidates=[0, .25, .5, .75, 1], rollout='random',
                chance='legacy', execution='sync', post_drop_ticks=25)


def validate_plan(plan):
    policy(plan['continuation'])
    if not 0 < plan['total_seconds'] <= 3600 or not 0 < plan['game_seconds'] <= 600:
        raise ValueError('Study cap <=3600s and per-game cap <=600s required')
    if not plan['roots'] or len({r['id'] for r in plan['roots']}) != len(plan['roots']):
        raise ValueError('Unique nonempty roots required')
    for r in plan['roots']:
        if not r['id'].replace('_', '').isalnum():
            raise ValueError('Root ID must be a simple directory name')
        if sha(r['fixture']) != r['fixture_sha256']:
            raise ValueError('Frozen fixture changed')
        if r.get('positions') is not None:
            xs = r['positions']
            if len(xs) != 2 or len(set(xs)) != 2 or any(not math.isfinite(x) or not 0 <= x <= 1 for x in xs):
                raise ValueError('Exactly two distinct normalized first positions required')
    if len(plan['future_seeds']) != len(set(plan['future_seeds'])) or not plan['future_seeds']:
        raise ValueError('Distinct future seeds required')
    if any(type(x) is not int or not 0 <= x <= 2147483647 for x in plan['future_seeds']):
        raise ValueError('Invalid future seed')


def prepare(source, jobs, out, futures, total_seconds, game_seconds):
    from suika_ai.collection_audit import initial_sequence
    out.mkdir(parents=True, exist_ok=False)
    reserved_path = ROOT / 'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json'
    reserved = load(reserved_path)['episodes']
    roots = []
    for job in jobs:
        jobdir = source / 'jobs' / f'job_{job:06d}'
        attempts = sorted(p for p in jobdir.glob('attempt_*') if p.is_dir())
        if not attempts:
            raise ValueError('Missing source attempt')
        a = attempts[-1]
        result = load(jobdir / (a.name + '_result.json'))
        rows = records(a / 'game_00.jsonl')
        end = rows[-1]
        if not (result.get('valid_for_return_learning') and end.get('event') == 'episode_end'
                and end.get('reason') == 'game_over' and end.get('game_over') is True
                and end.get('truncated') is False and end.get('conserved')):
            raise ValueError('Only independently audited natural-GO sources accepted')
        prefix = initial_sequence(rows)
        seed = result['game_seed']
        if seed in {e['seed'] for e in reserved} or prefix in {e['initial_sequence'] for e in reserved}:
            raise ValueError('Reserved Test19 group quarantined')
        chosen = next(r for r in rows if r.get('event') == 'transition'
                      and r.get('info', {}).get('drop_success') and not r['state'].get('game_over')
                      and any(f['type'] == 10 for f in r['state']['fruits']))
        f = fixture(chosen, 'post_state', allow_cold=True)
        f.update(source_file=str((a / 'game_00.jsonl').resolve()), source_sha256=sha(a / 'game_00.jsonl'),
                 source_seed=seed, source_initial_sequence=prefix, source_game_tick=chosen['state'].get('game_tick'),
                 source_split='development_not_reserved_test', native_checkpoint_exact=False,
                 future_rng='new experimental future; original source RNG unknown')
        target = out / f'job_{job}_after.json'
        write(target, f)
        roots.append(dict(id=f'job_{job}', fixture=str(target.resolve()), fixture_sha256=sha(target),
                          source_seed=seed, source_initial_sequence=prefix,
                          split_keys=[f'game_seed:{seed}', f'initial8:{prefix}'],
                          source_action_id=chosen['action_id'], source_tick=f['source_game_tick'],
                          source_sha256=f['source_sha256'], initial_score=f['score'],
                          initial_watermelons=sum(x['type'] == 10 for x in f['fruits']),
                          positions=None))
    exe = ROOT / 'Unity/Builds/StagedAction_02/SuikaGameAI.exe'
    protected = {}
    for pattern in ['Unity/Assets/**/*.cs', 'Python/*.py', 'Python/src/**/*.py']:
        for f in ROOT.glob(pattern):
            protected[str(f.resolve())] = sha(f)
    plan = dict(version='first-action-teacher-v1', roots=roots, future_seeds=futures,
                exe=str(exe), assembly_sha256=sha(exe.parent / 'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'),
                continuation=dict(kind='legacy_mcts', iterations=128, depth=4, search_seed=8191),
                total_seconds=total_seconds, game_seconds=game_seconds, port=43400,
                repeat_drops=3, repeat_seconds=45, candidate_rule='A legacy recommendation; B highest-mean other sampled, drop-success, immediate-nonGO candidate',
                split_rule='All futures/actions/repeats of a root stay together. Union source seeds OR initial8 keys across existing datasets before assigning splits.',
                claim='Actual experimental continuation from an approximate cold board; not a historical native counterfactual or optimal-action label.',
                reserved_manifest=str(reserved_path), reserved_sha256=sha(reserved_path), protected=protected)
    validate_plan(plan)
    write(out / 'plan.json', plan)
    return plan


def run_trial(folder, plan, root, future, mode, seconds, first_x=-1, drops=1000):
    from suika_ai.parallel_play import check_ports, worker_specs
    if active_players():
        raise RuntimeError('An existing Player is active; do not interfere with collection')
    check_ports(worker_specs(1, plan['port']))
    folder.mkdir(parents=True, exist_ok=False)
    c = policy(plan['continuation'])
    cfg = dict(fixture=root['fixture'], output=str((folder / 'trace.jsonl').resolve()), mode=mode,
               normal_start=False, future_seed=future, search_seed=c['search_seed'], iterations=c['iterations'],
               depth=c['depth'], max_drops=drops, max_seconds=seconds, first_x=first_x)
    write(folder / 'config.json', cfg)
    write(folder / 'provenance.json', dict(root_id=root['id'], split_keys=root['split_keys'],
          source_seed=root['source_seed'], source_initial_sequence=root['source_initial_sequence'],
          fixture_sha256=root['fixture_sha256'], continuation=c, source='actual_experimental_continuation',
          exact_historical_restore=False, hidden_native_state_complete=False))
    exe = Path(plan['exe'])
    args = [str(exe), '-batchmode', '-nographics', '--suika-audio', '0', '--suika-events', '1',
            '--suika-seed', str(future), '--suika-listen-port', str(plan['port']), '--suika-python-port', str(plan['port'] + 1),
            '-suikaRuntimeProbe', str((folder / 'runtime.jsonl').resolve()),
            '-suikaStagedActionLab', str((folder / 'config.json').resolve()),
            '-logFile', str((folder / 'player.log').resolve())]
    write(folder / 'launch.json', dict(args=args, exe_sha256=sha(exe), assembly_sha256=plan['assembly_sha256']))
    started = time.monotonic()
    proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    error = None
    try:
        while proc.poll() is None:
            if time.monotonic() - started > seconds + 20:
                error = 'process_timeout'
                break
            time.sleep(.25)
    except KeyboardInterrupt:
        error = 'interrupted'
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(10)
    rows = records(folder / 'trace.jsonl') if (folder / 'trace.jsonl').exists() else []
    result = summarize(rows)
    result.update(exit_code=proc.returncode, process_error=error, wall_seconds=time.monotonic() - started)
    if not result['end']:
        result['process_error'] = error or 'missing_end'
    result['natural_go'] = bool(result['natural_go'] and not result['errors'] and not result['process_error'] and proc.returncode == 0)
    write(folder / 'result.json', result)
    print(json.dumps(dict(event='trial_end', folder=str(folder), natural_go=result['natural_go'],
          reason=result['end']['reason'] if result['end'] else result['process_error'],
          extra=result['end']['additional_score'] if result['end'] else None,
          drops=result['end']['accepted_drops'] if result['end'] else None, seconds=result['wall_seconds'])), flush=True)
    if result['errors'] or result['process_error'] or proc.returncode:
        raise RuntimeError('Technical failure saved; do not replace seed or trust this return')
    return result, rows


def compare_trials(a, b):
    """Compare observed root, public chance draws, action/tick trajectory, and planner statistics separately."""
    ar = next(r for r in a if r['evt'] == 'root')
    br = next(r for r in b if r['evt'] == 'root')
    diff = public_difference(ar['state'], br['state'])
    extra = ['drop_cooldown_remaining', 'geometry', 'ai_move_speed', 'fixed_delta_time']
    same_context = all(ar['state'].get(k) == br['state'].get(k) for k in extra)
    def angular(rows):
        return sorted((f['type'], f['x'], f['y'], f.get('angular_velocity'), f.get('sleeping'), f.get('touching'), f.get('is_merging')) for f in rows['state']['fruits'])
    same_initial = diff['all_compared_fields_equal'] and same_context and angular(ar) == angular(br) and ar['tick'] == br['tick']
    def seq(rs):
        return [rs[0]['state']['current_fruit']['type'], rs[0]['state']['next_fruit_type']] + [r['state']['next_fruit_type'] for r in rs if r['evt'] == 'release']
    sa, sb = seq(a), seq(b)
    n = min(len(sa), len(sb))
    aa, bb = ([r for r in rs if r['evt'] == 'action'] for rs in [a, b])
    checks = []
    for x, y in zip(aa, bb):
        checks.append(dict(action=x['completed_actions'], public=public_difference(x['state'], y['state']),
                           command_equal=x['command'] == y['command'], rng_equal=x['rng'] == y['rng']))
    da, db = ([r for r in rs if r['evt'] == 'decision'] for rs in [a, b])
    search_checks = []
    for x, y in zip(da, db):
        search_checks.append(dict(action=x['completed_actions'] + 1,
               selected_equal=x['planning']['selected_x'] == y['planning']['selected_x'],
               root_statistics_equal=x['search']['root'] == y['search']['root'],
               source_unchanged=x['search']['source_unchanged'] and y['search']['source_unchanged']))
    return dict(initial_public=diff, same_initial_observed=same_initial,
                same_initial_context=same_context, initial_rng_equal=ar['rng'] == br['rng'],
                common_public_fruit_count=n, common_public_fruits_equal=sa[:n] == sb[:n],
                actions_compared=len(checks), action_checks=checks, search_checks=search_checks,
                fully_equal_observed_prefix=bool(checks) and len(aa) == len(bb) and all(c['public']['all_compared_fields_equal'] and c['command_equal'] and c['rng_equal'] for c in checks)
                    and len(da) == len(db) and all(c['selected_equal'] and c['root_statistics_equal'] and c['source_unchanged'] for c in search_checks),
                exact_native_state_guaranteed=False)


def run_study(out):
    plan = load(out / 'plan.json')
    validate_plan(plan)
    exe = Path(plan['exe'])
    if sha(exe.parent / 'SuikaGameAI_Data/Managed/Assembly-CSharp.dll') != plan['assembly_sha256']:
        raise ValueError('Protected Player changed')
    if sha(plan['reserved_manifest']) != plan['reserved_sha256']:
        raise ValueError('Test reservation changed')
    if active_players():
        raise RuntimeError('Do not compete with running collection')
    start = time.monotonic()
    write(out / 'execution_start.json', dict(start_unix=time.time(), total_seconds=plan['total_seconds'], plan_sha256=sha(out / 'plan.json')))
    selections, audits, durations, stops = {}, {}, [], []
    deadline = start + plan['total_seconds']
    try:
        for root in plan['roots']:
            rid = root['id']
            _, rows = run_trial(out / 'surveys' / rid, plan, root, plan['future_seeds'][0], 'survey', 30, drops=1)
            d = next(r for r in rows if r['evt'] == 'decision')
            selected = choose_alternative(d) if root.get('positions') is None else dict(
                recommended_x=root['positions'][0], alternative_x=root['positions'][1], candidates=d['search']['root'], explicit_positions=True)
            selections[rid] = selected
            # Freeze each pair before repeats or any natural-GO return can be observed.
            write(out / f'{rid}_selection.json', selected)
            _, future_rows = run_trial(out / 'future_surveys' / rid, plan, root, plan['future_seeds'][-1], 'survey', 30, drops=1)
            fd = next(r for r in future_rows if r['evt'] == 'decision')
            future_same = d['search']['root'] == fd['search']['root'] and d['planning']['selected_x'] == fd['planning']['selected_x']
            repeated = []
            for repeat in range(2):
                _, rr = run_trial(out / 'repeats' / rid / str(repeat), plan, root, plan['future_seeds'][0], 'baseline',
                                  plan['repeat_seconds'], selected['recommended_x'], plan['repeat_drops'])
                repeated.append(rr)
            audit = compare_trials(*repeated)
            audit['future_seed_changes_survey_statistics'] = not future_same
            audit['first_selection'] = selected
            audits[rid] = audit
            write(out / f'{rid}_reproducibility.json', audit)
            if not audit['same_initial_observed'] or not audit['initial_rng_equal']:
                stops.append(dict(root=rid, reason='initial_observed_state_not_comparable'))
        write(out / 'selections.json', selections)
        write(out / 'reproducibility.json', audits)
        for fi, future in enumerate(plan['future_seeds']):
            for ri, root in enumerate(plan['roots']):
                rid = root['id']
                if not audits[rid]['same_initial_observed'] or not audits[rid]['initial_rng_equal']:
                    continue
                remaining = deadline - time.monotonic()
                estimate = 2 * max(durations or [150]) * 1.15 + 25
                if remaining < estimate:
                    stops.append(dict(root=rid, future=future, reason='insufficient_remaining_pair_budget', remaining=remaining, estimate=estimate))
                    continue
                roles = ['recommended', 'alternative'] if (fi + ri) % 2 == 0 else ['alternative', 'recommended']
                for role in roles:
                    seconds = min(plan['game_seconds'], max(1, deadline - time.monotonic() - 25))
                    result, _ = run_trial(out / 'branches' / f'{rid}_f{future}' / role, plan, root, future,
                                          'baseline', seconds, selections[rid][role + '_x'])
                    durations.append(result['wall_seconds'])
                if len(durations) == 2:
                    write(out / 'pilot_timing.json', dict(pair_seconds=sum(durations), remaining_seconds=deadline-time.monotonic(),
                          rule='Keep candidates/seeds fixed. Use completed trial durations only to determine if another pair fits; never extend total budget.'))
    finally:
        write(out / 'execution_end.json', dict(elapsed_seconds=time.monotonic()-start, stops=stops,
              protected_changes=[p for p, h in plan['protected'].items() if sha(p) != h]))
    analyze(out)


def analyze(out, name='teacher'):
    plan = load(out / 'plan.json')
    audits = load(out / 'reproducibility.json') if (out / 'reproducibility.json').exists() else {}
    games, pairs, missing = [], [], []
    for root in plan['roots']:
        rid = root['id']
        for future in plan['future_seeds']:
            pair_rows, pair_games = {}, {}
            for role in ['recommended', 'alternative']:
                folder = out / 'branches' / f'{rid}_f{future}' / role
                if not (folder / 'result.json').exists():
                    missing.append(dict(root=rid, future=future, role=role))
                    continue
                result = load(folder / 'result.json')
                rs = records(folder / 'trace.jsonl')
                pair_rows[role] = rs
                start, end = result['root'], result['end']
                ds = [r for r in rs if r['evt'] == 'decision']
                cfg = load(folder / 'config.json')
                g = dict(root_id=rid, source_seed=root['source_seed'], source_initial_sequence=root['source_initial_sequence'],
                         split_keys=root['split_keys'], first_x=cfg['first_x'], role=role, future_seed=future,
                         continuation=policy(plan['continuation']), natural_go=result['natural_go'],
                         initial_score=start['score'], initial_watermelons=start['initial_watermelons'],
                         final_score=end['score'] if end else None,
                         actual_return=end['additional_score'] if result['natural_go'] else None,
                         observed_extra=end['additional_score'] if end else None,
                         accepted_drops=end['accepted_drops'] if end else None,
                         new_watermelons=end['new_watermelons'] if end else None,
                         second_watermelon=end['second_watermelon_generated'] if end else None,
                         two_present=end['two_watermelons_present'] if end else None,
                         doubles=end['double_watermelons'] if end else None,
                         reason=end['reason'] if end else result['process_error'], wall_seconds=result['wall_seconds'],
                         mean_planning_ms=statistics.mean(r['planning_ms'] for r in ds) if ds else None,
                         all_iterations_correct=all(r['search']['completed_iterations']==plan['continuation']['iterations'] for r in ds),
                         source_unchanged=all(r['search']['source_unchanged'] for r in ds),
                         first_root_statistics=ds[0]['search']['root'] if ds else [],
                         reproducibility=audits.get(rid), approximation='cold_visible_state_not_native_checkpoint',
                         source='actual_experimental_continuation', trajectory=str((folder / 'trace.jsonl').resolve()))
                pair_games[role] = g
                games.append(g)
            if len(pair_rows) == 2:
                c = compare_trials(pair_rows['recommended'], pair_rows['alternative'])
                a, b = pair_games['recommended'], pair_games['alternative']
                valid = a['natural_go'] and b['natural_go'] and c['same_initial_observed'] and c['initial_rng_equal'] and c['common_public_fruits_equal']
                pairs.append(dict(root_id=rid, source_seed=root['source_seed'], split_keys=root['split_keys'], future_seed=future,
                    valid_conditional_return_pair=valid, recommended_return=a['actual_return'], alternative_return=b['actual_return'],
                    alternative_minus_recommended=b['actual_return']-a['actual_return'] if valid else None,
                    comparison=c, continuation=policy(plan['continuation']),
                    label_scope='Return under this recorded continuation and future sample, not optimal Q or historical-game truth',
                    teacher_use='development_diagnostic_root_group_only; no training in this experiment'))
    report = dict(games=games, pairs=pairs, missing=missing, roots=len(plan['roots']),
                  source_group_rule=plan['split_rule'], model_training_performed=False)
    write(out / (name+'.json'), report)
    fields = ['root_id', 'source_seed', 'role', 'first_x', 'future_seed', 'natural_go', 'actual_return',
              'observed_extra', 'accepted_drops', 'new_watermelons', 'second_watermelon', 'two_present', 'doubles',
              'wall_seconds', 'mean_planning_ms', 'reason', 'all_iterations_correct', 'source_unchanged']
    with (out / (name+'.csv')).open('x', encoding='utf8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(games)
    print(json.dumps(dict(games=len(games), natural_go=sum(g['natural_go'] for g in games),
          pairs=[{k:p[k] for k in ['root_id','future_seed','valid_conditional_return_pair','alternative_minus_recommended']} for p in pairs], missing=len(missing))), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'run', 'analyze'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--jobs', type=int, nargs='+', default=[18, 29])
    p.add_argument('--future-seeds', type=int, nargs='+', default=[2026110101, 2026110102])
    p.add_argument('--total-seconds', type=float, default=3600)
    p.add_argument('--game-seconds', type=float, default=600)
    p.add_argument('--name', default='teacher')
    a = p.parse_args()
    if a.command == 'prepare':
        if a.source is None:raise ValueError('--source required')
        prepare(a.source, a.jobs, a.output, a.future_seeds, a.total_seconds, a.game_seconds)
    elif a.command == 'run':run_study(a.output)
    else:analyze(a.output, a.name)


if __name__ == '__main__':
    main()
