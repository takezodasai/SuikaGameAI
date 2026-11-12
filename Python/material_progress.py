"""Actual-game material milestones. Missing observations are unknown, never failures."""
from collections import Counter
import statistics

VERSION = 'watermelon-materials-v1'
BONUS_RECIPE = 'first-attainment-learning-only-v1'
GOALS = ('watermelon_one', 'watermelon_pineapple', 'watermelon_melon',
         'watermelon_melon_pineapple', 'watermelon_two_melons', 'two_watermelons', 'double_watermelon')
BONUS_UNITS = dict(zip(GOALS, (0, 1, 2, 3, 4, 6, 20)))
LEGACY = {'watermelon_one': 'watermelon_one', 'watermelon_melon_one': 'watermelon_melon',
          'watermelon_melon_two': 'watermelon_two_melons', 'watermelon_two': 'two_watermelons',
          'double_watermelon': 'double_watermelon'}


def inventory(state):
    fs = state.get('fruits')
    if not isinstance(fs, list) or any(type(f.get('type')) is not int or not 0 <= f['type'] <= 10 for f in fs):
        raise ValueError('unknown inventory')
    return Counter(f['type'] for f in fs)


def conditions(state):
    c = inventory(state);w, m, p = c[10], c[9], c[8]
    return dict(watermelon_one=w >= 1, watermelon_pineapple=w >= 1 and p >= 1,
                watermelon_melon=w >= 1 and m >= 1,
                watermelon_melon_pineapple=w >= 1 and m >= 1 and p >= 1,
                watermelon_two_melons=w >= 1 and m >= 2, two_watermelons=w >= 2)


def analyze(rows):
    """First attainment, imported attainment, and post-attainment outcomes separately.

    Only the native atomic recorder proves negative coexistence labels. Legacy
    sampled board states prove observed positives but cannot exclude short events.
    """
    if not rows:
        return dict(version=VERSION, natural_go=False, atomic_complete=False, goals={k:dict(initial=None,new=None) for k in GOALS})
    end = rows[-1] if rows[-1].get('evt') == 'end' else None
    terminal = bool(end and end.get('natural_go') and not end.get('truncated') and end.get('reason') == 'natural_go')
    root = next((r for r in rows if r.get('evt') == 'root'), None)
    root_index = rows.index(root) if root else 0
    first = {};supported = set();initial = {}
    actual_root=bool(root and (root.get('raw_events') or {}).get('source')=='actual_game' and (root.get('raw_events') or {}).get('known'))
    try:
        if actual_root:initial.update(conditions(root['state']))
    except (KeyError, TypeError, ValueError):
        pass
    initial['double_watermelon'] = False if actual_root else None
    final_native = ((end or rows[-1]).get('raw_events') or {}).get('materials') or {}
    root_native = ((root or {}).get('raw_events') or {}).get('materials') or {}
    root_legacy=((root or {}).get('raw_events') or {}).get('learning') or {}
    root_counts=inventory(root['state']) if actual_root else Counter()
    legacy_trusted=bool(actual_root and root_legacy.get('known') and
                        root_legacy.get('watermelons_present')==root_counts[10] and
                        root_legacy.get('melons_present')==root_counts[9])
    atomic = bool(root_native.get('version') == VERSION and root_native.get('known') and
                  final_native.get('version') == VERSION and final_native.get('known'))
    for i, r in enumerate(rows):
        raw = r.get('raw_events') or {}
        # Prediction branches are not accepted as actual observations.
        if raw.get('source') != 'actual_game' or not raw.get('known'):
            continue
        native = raw.get('materials') or {}
        if native.get('version') == VERSION and native.get('known'):
            if terminal and atomic:
                supported.update(GOALS)
            for e in native.get('events') or []:
                k = e.get('kind')
                if k in GOALS:
                    first.setdefault(k, dict(e, observation_index=i, evidence='atomic_actual_callback'))
        legacy = raw.get('learning') or {}
        if legacy.get('known') and legacy_trusted:
            if terminal and ((end.get('raw_events') or {}).get('learning') or {}).get('known'):
                supported.update(LEGACY.values())
            for e in legacy.get('events') or []:
                k = LEGACY.get(e.get('kind'))
                if k:
                    first.setdefault(k, dict(e, kind=k, initial=bool(initial.get(k) and i==root_index),
                                             observation_index=i, evidence='legacy_actual_callback'))
        # Coexistence between logged snapshots may be missed in old logs.
        if r.get('evt') in ('root','decision','action','end'):
            try:
                for k, yes in conditions(r['state']).items():
                    if yes:
                        first.setdefault(k, dict(kind=k,initial=bool(initial.get(k)),tick=r.get('tick'),
                            score=r['score'],drop_count=r.get('accepted_drops'),observation_index=i,
                            evidence='sampled_actual_board'))
            except (KeyError, TypeError, ValueError):
                pass
        for e in raw.get('events') or []:
            if e.get('kind')=='double_watermelon':
                first.setdefault('double_watermelon',dict(e,initial=False,observation_index=i,evidence='actual_double_callback'))
    goals = {}
    for k in GOALS:
        e=first.get(k);init=initial.get(k)
        if e and e.get('evidence')=='atomic_actual_callback':
            init=bool(e['initial'])
        new = bool(e and not init) if e else False if k in supported else None
        if init is True:
            new=False
        after_drops=after_score=None
        if e and terminal:
            if e.get('drop_count') is not None:
                after_drops=end['accepted_drops']-e['drop_count']
            if e.get('score') is not None:
                after_score=end['score']-e['score']
        goals[k]=dict(initial=init,new=new,ever=True if e or init else False if k in supported else None,
                      first=e,post_attainment_survival_drops=after_drops,post_attainment_points=after_score)
    return dict(version=VERSION,natural_go=terminal,atomic_complete=atomic and terminal,
                goals=goals,initial_counts={str(k):v for k,v in inventory(root['state']).items()} if actual_root else None,
                note='Inventory milestones are progress measures, not guarantees of eventual success. Initial inventory is not newly earned.')


def future_labels(rows, decision, analysis=None):
    result = analysis or analyze(rows)
    i = next(j for j,r in enumerate(rows) if r is decision)
    labels = {}
    for k in GOALS:
        g=result['goals'][k];first=g.get('first')
        if g['initial'] or (first and first['observation_index']<=i):
            labels[k]=None  # not at risk of a first attainment; no repeated bonus
        elif first and first['observation_index']>i:
            labels[k]=True
        else:
            labels[k]=False if g['ever'] is False else None
    return labels


def bonus_points(labels, unit_points=0.):
    if not 0 <= unit_points <= 100:
        raise ValueError('progress bonus unit must be 0..100 points')
    return sum(BONUS_UNITS[k]*unit_points for k in GOALS if labels.get(k) is True)


def rates(progresses):
    out={}
    for k in GOALS:
        gs=[p['goals'][k] for p in progresses]
        at_risk=[g for g in gs if g['initial'] is False]
        known=[g for g in at_risk if g['new'] is not None]
        def followup(items):
            survival=[g['post_attainment_survival_drops'] for g in items if g.get('post_attainment_survival_drops') is not None]
            points=[g['post_attainment_points'] for g in items if g.get('post_attainment_points') is not None]
            return dict(games=len(survival),mean_survival_drops=statistics.mean(survival) if survival else None,
                        mean_additional_points=statistics.mean(points) if points else None)
        out[k]=dict(initial=sum(g['initial'] is True for g in gs),at_risk=len(at_risk),
                    evaluable=len(known),unknown=sum(g['new'] is None for g in at_risk),
                    newly_achieved=sum(g['new'] is True for g in known),
                    observed_rate=sum(g['new'] is True for g in known)/len(known) if known else None,
                    new_attainment_followup=followup([g for g in known if g['new'] is True]),
                    initial_attainment_followup=followup([g for g in gs if g['initial'] is True]))
    return out


def select_fixture(fixtures, index, policy='legacy'):
    if policy=='legacy':
        return fixtures[index % len(fixtures)]
    if policy!='progress-balanced':
        raise ValueError('unknown curriculum policy')
    buckets={k:[] for k in ('pre_watermelon',)+GOALS[:-1]}
    for f in fixtures:
        for stage in f.get('stages',[f['stage']]):
            if stage in buckets:buckets[stage].append(f)
    available=[v for v in buckets.values() if v]
    if not available:raise ValueError('no material-progress fixtures')
    bucket=available[index % len(available)]
    return bucket[(index//len(available)) % len(bucket)]
