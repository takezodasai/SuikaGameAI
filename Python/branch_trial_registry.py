"""Read-only recursive branch registry and explicit replication identities.

Source groups are independent only across original seed AND initial8. A trial
condition excludes repeat labels, file paths and output directory names.
"""
import hashlib
import json
import os
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def branch_plans(outputs, exclude=None):
    """Visit nested session containers, never traverse bulky per-trial artifacts."""
    excluded = Path(exclude).resolve() if exclude is not None else None
    for folder, dirs, files in os.walk(outputs):
        dirs[:] = sorted(d for d in dirs if d not in {'jobs', 'tasks', '.git', '__pycache__'}
                         and not d.startswith(('attempt_', 'dataset')))
        path = Path(folder) / 'plan.json'
        if 'plan.json' not in files or path.parent.resolve() == excluded:
            continue
        names = [p.name for p in path.relative_to(outputs).parents]
        legacy_name=any(n.startswith(('branch_', 'staged_action_', 'watermelon_lab_', 'watermelon_dynamic_')) for n in names)
        # Fail closed on unreadable registered plans; do not silently forget work.
        try:data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError,OSError):
            if legacy_name:raise
            continue
        is_batch=str(data.get('version','')).startswith('branch-batch-')
        if (legacy_name or is_batch) and ('roots' in data or 'inventory' in data):
            yield path, data


def snapshot_identity(root):
    """All saved physical restore inputs, excluding provenance and file names."""
    f = root.get('fixture')
    if f and Path(f).is_file():
        x = json.loads(Path(f).read_text(encoding='utf-8-sig'))
        fields = ['fruits', 'current_fruit_type', 'next_fruit_type', 'score', 'held_x',
                  'game_over_y', 'geometry', 'drop_cooldown_remaining', 'ai_move_speed', 'fixed_delta_time']
        state = {k: x[k] for k in fields if k in x}
        # Snapshot also contains process IDs, clocks, previous planner reports and
        # telemetry. These must not make a copied physical condition look new.
        s = x.get('snapshot', {})
        state['snapshot'] = {k:s[k] for k in ['current_fruit', 'next_fruit_type', 'geometry',
                            'ai_move_speed', 'fixed_delta_time', 'drop_cooldown_remaining'] if k in s}
        def without_observation_ids(value):
            if isinstance(value,dict):return {k:without_observation_ids(v) for k,v in value.items() if k!='id'}
            if isinstance(value,list):return [without_observation_ids(v) for v in value]
            return value
        # Keep fruit initialization order, but observation-only IDs are not a
        # distinct experiment. Physics profile IDs remain part of the identity.
        return digest(without_observation_ids(state))
    return root.get('fixture_sha256', root.get('board_uid'))


def source_keys(root):
    keys = set(root.get('split_keys', []))
    if root.get('source_seed') is not None:
        keys.add('game_seed:' + str(root['source_seed']))
    if root.get('source_initial_sequence'):
        keys.add('initial8:' + root['source_initial_sequence'])
    return keys


def trial_identity(plan, root, future, x):
    if not snapshot_identity(root):
        raise ValueError('Unknown snapshot identity; cannot guarantee duplicate prevention')
    return dict(board_uid=root.get('board_uid'), snapshot=snapshot_identity(root),
                source_keys=sorted(source_keys(root)), coordinate=float(x),
                future_seed=int(future), continuation=plan['continuation'],
                player={k: plan.get(k) for k in ['exe_sha256', 'assembly_sha256']})


def relationship(left, right):
    """Distinguish source dependence from identical/new-future conditions."""
    same_board = left['snapshot'] == right['snapshot']
    same_policy = left['continuation'] == right['continuation'] and left['player'] == right['player']
    if same_board and same_policy and left['coordinate'] == right['coordinate']:
        return 'same_condition' if left['future_seed'] == right['future_seed'] else 'new_future'
    if same_board:
        return 'same_board_different_action_or_policy'
    if set(left['source_keys']) & set(right['source_keys']):
        return 'same_source_different_board'
    return 'independent_source'


def declared_trials(path, plan):
    for root in plan.get('roots', []):
        if not isinstance(root, dict) or 'id' not in root:
            continue
        selection = path.parent / (root['id'] + '_selection.json')
        if not selection.exists():
            continue
        selected = json.loads(selection.read_text(encoding='utf-8-sig'))
        for future in plan.get('future_seeds', []):
            for role in ['recommended', 'alternative']:
                yield trial_identity(plan, root, future, selected[role + '_x'])


def check_new_trial(outputs, out, plan, root, future, x):
    target = trial_identity(plan, root, future, x)
    allowed = False
    if plan.get('collection_intent') == 'intentional_repeat':
        source = Path(plan.get('source_plan', ''))
        if source.is_file() and plan.get('repeat_reason'):
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() == plan.get('repeat_of_plan_sha256'):
                reference = json.loads(raw)
                allowed = any(relationship(target, t) == 'same_condition' for t in declared_trials(source, reference))
        if not allowed:
            raise ValueError('Repeat authorization does not match a frozen source trial')
    for path, old in branch_plans(outputs, exclude=out):
        if plan.get('collection_intent')=='new_independent_sources':
            for previous in old.get('roots',[]):
                if isinstance(previous,dict) and (source_keys(root)&source_keys(previous) or snapshot_identity(root)==snapshot_identity(previous)):
                    raise ValueError('Previously used source/board cannot be collected as independent: '+str(path))
        for trial in declared_trials(path, old):
            if relationship(target, trial) != 'same_condition':
                continue
            if not allowed:
                raise ValueError('Unintentional duplicate trial blocked: ' + str(path))


def preview_plan(out, outputs=None):
    out=Path(out)
    outputs=Path(outputs) if outputs is not None else Path(__file__).resolve().parent/'outputs'
    plan=json.loads((out/'plan.json').read_text())
    previous=list(branch_plans(outputs,exclude=out))
    keys=set();snapshots=set();trials=[]
    for path,p in previous:
        for r in p.get('roots',[]):
            if isinstance(r,dict):keys.update(source_keys(r));snapshots.add(snapshot_identity(r))
        trials.extend(declared_trials(path,p))
    roots=plan['roots'];declared=list(declared_trials(out/'plan.json',plan))
    matches=[any(relationship(t,old)=='same_condition' for old in trials) for t in declared]
    return dict(new_independent_boards=sum(not bool(source_keys(r)&keys) and snapshot_identity(r) not in snapshots for r in roots),
        existing_source_overlaps=sum(bool(source_keys(r)&keys) for r in roots),
        existing_board_overlaps=sum(snapshot_identity(r) in snapshots for r in roots),
        planned_main_trials=len(roots)*len(plan['future_seeds'])*2,
        candidate_fixed_trials=len(declared),same_condition_trials=sum(matches),
        collection_intent=plan.get('collection_intent','legacy_unspecified'),
        note='Read-only. Repeats/new futures never increase independent source count.')


def clone_plan(source, out, futures, intent, reason=None, dry_run=False):
    """Explicit repeated/new-future runs use a NEW immutable plan, never edit old."""
    from watermelon_lab import sha, write
    source, out = Path(source), Path(out)
    if out.exists():
        raise FileExistsError(out)
    old = json.loads((source / 'plan.json').read_text())
    futures = list(futures)
    if len(futures) != 2 or len(set(futures)) != 2:
        raise ValueError('Current runner requires two distinct future seeds')
    if intent == 'intentional_repeat':
        if not reason or futures != old['future_seeds']:
            raise ValueError('Repeat requires a reason and the original future seeds')
    elif intent == 'new_future_series':
        if set(futures) & set(old['future_seeds']):
            raise ValueError('New-future request includes an original future seed')
        # Also reject a future already reserved by a different batch.
        for _, other in branch_plans(Path(__file__).resolve().parent / 'outputs'):
            for r in other.get('roots', []):
                if isinstance(r, dict) and any(snapshot_identity(r) == snapshot_identity(a) for a in old['roots']):
                    if set(futures) & set(other.get('future_seeds', [])):
                        raise ValueError('New-future request overlaps an existing plan')
    else:
        raise ValueError('Explicit repeat or new_future_series required')
    summary = dict(intent=intent, new_independent_boards=0, existing_board_overlaps=len(old['roots']),
                   planned_main_trials=len(old['roots'])*len(futures)*2, future_seeds=futures)
    if dry_run:
        return summary
    for r in old['roots']:
        if not (source / (r['id'] + '_selection.json')).exists():
            raise ValueError('Freeze candidates in the original plan before cloning')
    out.mkdir(parents=True)
    plan = dict(old, future_seeds=futures, collection_intent=intent, repeat_reason=reason,
                repeat_of_plan_sha256=sha(source / 'plan.json'), source_plan=str((source/'plan.json').resolve()))
    write(out / 'plan.json', plan)
    for r in old['roots']:
        write(out / (r['id']+'_selection.json'), json.loads((source/(r['id']+'_selection.json')).read_text()))
    return summary
