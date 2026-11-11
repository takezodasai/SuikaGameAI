"""Isolated approximate post-watermelon actual-play lab. Never edits source episodes."""
import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Python' / 'src'))


def write(path, value):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def choose_stages(transitions):
    """Only recorded actual board evidence, never synthesize a watermelon."""
    first = next(i for i, r in enumerate(transitions)
                 if not r['state'].get('game_over') and any(f['type'] == 10 for f in r['state']['fruits']))
    after = [r for r in transitions[first:] if not r['state'].get('game_over')
             and any(f['type'] == 10 for f in r['state']['fruits'])]
    def risk(r):
        armed = [f['y'] for f in r['state']['fruits'] if f.get('has_collided')]
        return max(armed, default=-math.inf)
    stages = [('after', transitions[first]), ('danger', max(after, key=risk))]
    if first:
        stages.insert(0, ('before', transitions[first - 1]))
    return stages


def prepare(output):
    from prepare_candidate_fixtures import fixture
    output.mkdir(parents=True, exist_ok=False)
    manifest = ROOT / 'Python/outputs/policy_success_01/dataset/manifest.json'
    reserved_file = ROOT / 'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json'
    reserved = json.loads(reserved_file.read_text())['episodes']
    reserved_seeds = {e['seed'] for e in reserved}
    reserved_prefixes = {e['initial_sequence'] for e in reserved}
    episodes = json.loads(manifest.read_text())['episodes']
    selected, groups = [], set()
    for e in episodes:
        if (e['split'] == 'train' and e['natural_go'] and e['events']['labels']['watermelon_one']['achieved']
                and e['group'] not in groups and e['seed'] not in reserved_seeds
                and e['initial_sequence'] not in reserved_prefixes):
            selected.append(e)
            groups.add(e['group'])
        if len(selected) == 3:
            break
    if len(selected) < 3:
        raise ValueError('Need three independent training success groups')
    inventory = []
    for index, e in enumerate(selected):
        source = Path(e['source'])
        rows = [json.loads(l) for l in source.open(encoding='utf-8-sig')]
        end = rows[-1]
        if end.get('event') != 'episode_end' or not end.get('game_over') or end.get('truncated') or not end.get('conserved'):
            raise ValueError('Completed conserved natural-GO source required')
        transitions = [r for r in rows if r.get('event') == 'transition' and r['info'].get('drop_success')]
        root = output / f'source_{index}'
        root.mkdir()
        for stage, row in choose_stages(transitions):
            f = fixture(row, 'post_state', allow_cold=True)
            f.update(source_file=str(source), source_sha256=sha(source), source_seed=e['seed'],
                     source_group=e['group'], source_split='train', category=stage,
                     source_game_tick=row['state'].get('game_tick'),
                     native_checkpoint_exact=False, future_rng='new experimental seed, not source RNG',
                     original_state=dict(unity_rng='unknown', solver_cache='unserializable',
                                         frame_schedule='not fully recorded'))
            target = root / f'{stage}.json'
            write(target, f)
            inventory.append(dict(index=index, seed=e['seed'], stage=stage, fixture=str(target.resolve()),
                                  source=str(source), source_action_id=row['action_id'], score=f['score'],
                                  original_final_score=end.get('score'), fruits=len(f['fruits']),
                                  watermelons=sum(x['type'] == 10 for x in f['fruits']),
                                  missing=f['unknown_fields'], source_sha256=f['source_sha256']))
    protected = {}
    for glob in ['Unity/Assets/**/*.cs', 'Python/*.py']:
        for p in ROOT.glob(glob):
            protected[str(p)] = sha(p)
    plan = dict(version='watermelon-lab-v1', exact_historical_restore=False, inventory=inventory,
                manifest_sha256=sha(manifest), reserved_manifest_sha256=sha(reserved_file),
                replay_budget='Up to 3 source prefixes, <=24 drops / 50 seconds each; abort audit at first failed source comparison. No historical exactness inferred from new-process self agreement.',
                play_budget='serial; <=3 headless MCTS continuations + one <=3-drop GUI smoke; each <=180s, <=600s total continuation budget',
                mcts=dict(iterations=128, depth=4, candidates=5, post_drop_ticks=25,
                          random_rollout=True, search_seed=8191),
                events='Imported initial watermelon is baseline, never a newly generated success. Record actual continuation callbacks with baseline offset.',
                comparison='Approximate fixtures only; no guaranteed identical hidden solver state; no strict action ranking labels',
                sources_protected=protected)
    write(output / 'plan.json', plan)
    print(json.dumps(dict(fixtures=len(inventory), sources=len(selected), output=str(output)), ensure_ascii=False))


def summarize(rows):
    ends = [r for r in rows if r.get('evt') == 'end']
    root = next((r for r in rows if r.get('evt') == 'root'), None)
    end = ends[-1] if ends else None
    return dict(root=root, end=end, natural_go=bool(end and end.get('natural_go')),
                valid_historical_return=False,
                errors=[r.get('error') for r in rows if r.get('evt') == 'error'],
                note='Actual continuation from approximate reconstructed root; not historical-game counterfactual truth.')


def public_difference(old, new):
    """Field audit; equality never proves equality of native solver caches."""
    result = dict(score_equal=old['score'] == new['score'],
                  held_equal=old['current_fruit']['type'] == new['current_fruit']['type'],
                  next_equal=old['next_fruit_type'] == new['next_fruit_type'],
                  fruit_count_equal=len(old['fruits']) == len(new['fruits']))
    key = lambda f: (f['type'], f['x'], f['y'])
    a, b = sorted(old['fruits'], key=key), sorted(new['fruits'], key=key)
    result['types_equal'] = [f['type'] for f in a] == [f['type'] for f in b]
    if result['types_equal']:
        result['max_position_delta'] = max((max(abs(x['x']-y['x']), abs(x['y']-y['y'])) for x,y in zip(a,b)), default=0)
        result['max_velocity_delta'] = max((max(abs(x['vx']-y['vx']), abs(x['vy']-y['vy'])) for x,y in zip(a,b)), default=0)
        result['max_rotation_delta'] = max((abs(x['angle']-y['angle']) for x,y in zip(a,b)), default=0)
        result['collision_flags_equal'] = all(x.get('has_collided') == y.get('has_collided') for x,y in zip(a,b))
    result['all_compared_fields_equal'] = all(result[k] for k in ['score_equal','held_equal','next_equal','fruit_count_equal','types_equal']) and all(result.get(k) == 0 for k in ['max_position_delta','max_velocity_delta','max_rotation_delta']) and result.get('collision_flags_equal',False)
    return result


def replay_audit(root, exe):
    from run_fresh_continuation import config, run as replay, source_positions
    plan = json.loads((root/'plan.json').read_text())
    audit = []
    for item in [x for x in plan['inventory'] if x['stage']=='after']:
        seed, positions, original = source_positions(item['source'])
        folder=root/f"source_{item['index']}"/'prefix24_audit'
        conf=config(folder,seed,positions[:24],seconds=45)
        result=replay(conf,exe,port=42890,timeout=65)
        old=[r for r in original if r.get('event')=='transition' and r['info'].get('drop_success')][:24]
        new=[json.loads(l) for l in (folder/'trace.jsonl').read_text().splitlines() if json.loads(l).get('evt')=='action']
        comparisons=[dict(action=i+1,**public_difference(a['state'],b['state'])) for i,(a,b) in enumerate(zip(old,new))]
        first=next((r for r in comparisons if not r['all_compared_fields_equal']),None)
        audit.append(dict(seed=seed,source=item['source'],first_difference=first,compared_actions=len(comparisons),
                          wall_seconds=result['wall_seconds'],exact_historical_replay=False,
                          conclusion='Historical prefix not certified: missing original RNG/frame schedule/native state. Stop at this short diagnostic; switch to declared approximate fixture.'))
    write(root/'replay_audit.json',audit)
    print(json.dumps(audit),flush=True)


def run(fixture, output, exe, drops, seconds, first_x, future_seed, gui, port, iterations):
    from suika_ai.parallel_play import check_ports, worker_specs
    if not 1 <= drops <= 1000 or not 0 < seconds <= 600 or not (-1 <= first_x <= 1):
        raise ValueError('Invalid lab budget or candidate')
    if not 5 <= iterations <= 256:
        raise ValueError('This lab preserves legacy-budget MCTS, 5..256 iterations')
    check_ports(worker_specs(1, port))
    output.mkdir(parents=True, exist_ok=False)
    cfg = dict(fixture=str(fixture.resolve()), output=str((output / 'trace.jsonl').resolve()),
               max_drops=drops, max_seconds=seconds, first_x=first_x, future_seed=future_seed,
               search_seed=8191, iterations=iterations, depth=4)
    write(output / 'config.json', cfg)
    args = [str(exe.resolve()), '--suika-audio', '0', '--suika-events', '1', '--suika-seed', str(future_seed),
            '--suika-listen-port', str(port), '--suika-python-port', str(port + 1),
            '-suikaRuntimeProbe', str((output / 'runtime.jsonl').resolve()),
            '-suikaWatermelonLab', str((output / 'config.json').resolve()),
            '-logFile', str((output / 'player.log').resolve())]
    if gui:
        args += ['-screen-width', '960', '-screen-height', '720', '-screen-fullscreen', '0']
    else:
        args += ['-batchmode', '-nographics']
    write(output / 'launch.json', dict(command=args, executable_sha256=sha(exe), fixture_sha256=sha(fixture)))
    child = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    start = time.monotonic()
    failure = None
    try:
        while child.poll() is None:
            if time.monotonic()-start > seconds+35:
                raise subprocess.TimeoutExpired(args,seconds+35)
            log_path=output/'player.log'
            if log_path.exists() and any(s in log_path.read_text(encoding='utf8',errors='replace') for s in ['NullReferenceException:', 'ArgumentException:', 'InvalidOperationException:']):
                failure='player_exception'
                break
            time.sleep(.25)
    except subprocess.TimeoutExpired:
        failure = 'process_timeout'
    except KeyboardInterrupt:
        failure = 'user_interrupt'
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
    trace = output / 'trace.jsonl'
    rows = []
    if trace.exists():
        for line in trace.read_text(encoding='utf-8-sig').splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                failure = failure or 'incomplete_trace'
    result = summarize(rows)
    if result['end'] is None and failure is None:
        failure = 'missing_end_record'
    result.update(process_error=failure, exit_code=child.returncode, wall_seconds=time.monotonic()-start)
    write(output / 'result.json', result)
    print(json.dumps(dict(output=str(output), exit_code=child.returncode, process_error=failure,
                         end={k: result['end'].get(k) for k in ['reason','score','additional_score','accepted_drops','new_watermelons','double_watermelons']} if result['end'] else None)), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('prepare'); a.add_argument('--output', type=Path, required=True)
    a = sub.add_parser('replay-audit'); a.add_argument('--output', type=Path, required=True)
    a.add_argument('--exe', type=Path, default=ROOT/'Unity/Builds/WatermelonLab_03/SuikaGameAI.exe')
    a = sub.add_parser('play'); a.add_argument('--fixture', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--exe', type=Path, default=ROOT/'Unity/Builds/WatermelonLab_03/SuikaGameAI.exe')
    a.add_argument('--drops', type=int, default=80); a.add_argument('--seconds', type=float, default=180)
    a.add_argument('--first-x', type=float, default=-1); a.add_argument('--future-seed', type=int, default=2026103103)
    a.add_argument('--iterations', type=int, default=128); a.add_argument('--port', type=int, default=42880)
    a.add_argument('--gui', action='store_true')
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a.output)
    elif a.command == 'replay-audit':
        replay_audit(a.output,a.exe)
    else:
        run(a.fixture,a.output,a.exe,a.drops,a.seconds,a.first_x,a.future_seed,a.gui,a.port,a.iterations)


if __name__ == '__main__':
    main()
