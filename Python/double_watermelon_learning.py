"""Versioned normal-play + approximate watermelon curriculum, using the existing Player.

No changes to MCTS/physics. Old data is read-only. No automatic model promotion.
"""
import argparse
import collections
import hashlib
import json
import math
import secrets
import statistics
import subprocess
import time
import uuid
from pathlib import Path

from watermelon_lab import ROOT, sha, write, public_difference
from rollout_selfplay import DEFAULT_EXE, read_rows, exclusive_lock, atomic
from learned_rollout import GRID, features, probabilities

OUTPUTS = ROOT / 'Python/outputs'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def bounded_records(records, limit=64):
    """Stream a deterministic per-episode subset; retain first and last observations."""
    episodes = collections.defaultdict(list)
    seen = set()
    for r in records:
        key = (r['episode'],r['action_id'])
        if key in seen:
            continue
        seen.add(key)
        bucket = episodes[r['episode']]
        bucket.append((digest(key),r))
        if len(bucket)>limit:
            # Never discard the first/latest record; order-independent hash priority
            # selects the remaining interior observations without return-based choice.
            del bucket[max(range(1,len(bucket)-1),key=lambda i:bucket[i][0])]
    return [r for ep in sorted(episodes) for _,r in episodes[ep]]


def completed_trace(folder, actor=None):
    """Fail closed on partial, capped, unaudited, or actor-mismatched episodes."""
    folder = Path(folder)
    cfg, result = load(folder/'config.json'), load(folder/'result.json')
    if not result.get('natural_go') or result.get('exit_code') != 0:
        raise ValueError('not natural GO with known successful exit')
    if result.get('errors') or result.get('process_error'):
        raise ValueError('technical error')
    if result.get('trace_sha256') and sha(folder/'trace.jsonl')!=result['trace_sha256']:
        raise ValueError('saved trace hash mismatch')
    rows, partial = read_rows(folder/'trace.jsonl')
    if partial or not rows or rows[-1].get('evt') != 'end':
        raise ValueError('partial trace or missing terminal')
    end = rows[-1]
    if not end.get('natural_go') or end.get('truncated') or end.get('reason') != 'natural_go':
        raise ValueError('censored terminal')
    decisions = [r for r in rows if r['evt'] == 'decision']
    releases = {r['command']['start_tick']: r for r in rows if r['evt'] == 'release'}
    if end['accepted_drops'] != len(releases):
        raise ValueError('drop conservation')
    for row in decisions:
        s, p = row['search'], row['rollout']
        if (s['completed_iterations'] != cfg['iterations'] or
                sum(c['visits'] for c in s['root']) != cfg['iterations'] or
                not s['source_unchanged'] or
                (actor and p['model_sha256'] != actor)):
            raise ValueError('MCTS/actor audit')
        if p.get('rollout_calls') is not None and p['rollout_calls'] != p['learned_calls']+p['random_calls']+p['fallback_calls']:
            raise ValueError('rollout count conservation')
        if row['command']['x'] != row['planning']['selected_x']:
            raise ValueError('not unchanged root selection')
    root = next(r for r in rows if r['evt'] == 'root')
    if not cfg.get('normal_start'):
        f = load(cfg['fixture'])
        diff = public_difference(f['snapshot'], root['state'])
        if (not all(diff[k] for k in ('score_equal','held_equal','next_equal','fruit_count_equal','types_equal','collision_flags_equal'))
                or any(diff.get(k, math.inf)>1e-5 for k in ('max_position_delta','max_velocity_delta','max_rotation_delta'))):
            raise ValueError('fixture public-state mismatch')
    return cfg, rows, root, end, releases


def samples(folder, group, split, initial8, actor=None):
    cfg, rows, root, end, releases = completed_trace(folder, actor)
    episode = str(Path(folder).resolve())
    kind = 'normal' if cfg['normal_start'] else 'approximate_curriculum'
    from material_progress import analyze, future_labels
    progress=analyze(rows)
    ans = []
    for r in rows:
        if r['evt'] != 'decision' or r['command']['start_tick'] not in releases:
            continue
        if [c['x'] for c in r['search']['root']] != GRID:
            raise ValueError('only fixed five candidates supported')
        if r['state']['score'] > end['score']:
            raise ValueError('score conservation')
        raw = r.get('raw_events') or {}
        final = end.get('raw_events') or {}
        known = bool(raw.get('known') and final.get('known'))
        # Native observer also accounts for imported watermelons and transient pairs.
        targets = dict(new_watermelon=(end['new_watermelons'] > r['new_watermelons']) if known else None,
                       two_present=(end['max_watermelons_present'] >= 2) if known and r['max_watermelons_present'] < 2 else None,
                       double=(end['double_watermelons'] > r['double_watermelons']) if known else None)
        ans.append(dict(sample=dict(state=r['state'], geometry=r['state']['geometry']),
                        selected_index=r['planning']['selected_index'], visits=[c['visits'] for c in r['search']['root']],
                        return_points=end['score']-r['state']['score'], seed=group,
                        initial8=initial8, split=split, episode=episode,
                        source_kind=kind, actual_iterations=r['search']['completed_iterations'],
                        depth=cfg['depth'], actor_sha256=r['rollout']['model_sha256'],
                        action_id=r['command']['start_tick'], events=targets,
                        progress_labels=future_labels(rows,r,progress),
                        progress_observation_complete=progress['atomic_complete']))
    return ans


def prepare(out, max_roots=24):
    """Freeze all approved surviving episodes and inherited split decisions before use."""
    out = Path(out).resolve()
    if not 1 <= max_roots <= 500:
        raise ValueError('max_roots must be 1..500')
    if out.exists():
        raise FileExistsError(out)
    # Saved experience contains the historical split, not a newly invented Test.
    membership, prefix_split, conflicts = {}, {}, set()
    historical = {}
    for p in sorted(OUTPUTS.glob('rollout_selfplay_*/generations/*/experience.jsonl')):
        with p.open(encoding='utf8') as f:
            for line in f:
                r = json.loads(line)
                seed, prefix, split = r['source_seed'], r['initial8'], r['split']
                if split not in ('train', 'validation'):
                    continue
                if seed in membership and membership[seed] != split:
                    conflicts.add(seed)
                if prefix in prefix_split and prefix_split[prefix] != split:
                    conflicts.add(seed)
                membership[seed] = split
                prefix_split[prefix] = split
                if r['source_kind'] == 'bootstrap':
                    key = (r['episode'], digest(r['input']), r['selected_index'])
                    historical.setdefault(key, dict(sample=r['input'], selected_index=r['selected_index'],
                        visits=r['root_visits'], return_points=r['teacher']['actual_remaining_points'],
                        seed=seed, initial8=prefix, split=split, episode=r['episode'],
                        source_kind='historical', actual_iterations=r['actual_iterations'], depth=r['depth'],
                        action_id=key[1], events=None))
    if not historical:
        raise ValueError('No surviving historical split evidence; do not invent old Test membership')
    data = list(historical.values())
    sources, rejected = [], []
    seen, seen_prefix = set(), {}
    # Inherit saved seed/prefix split registries, including interrupted sessions.
    for p in sorted(OUTPUTS.glob('rollout_selfplay_*/split_registry.json')):
        for key, split in load(p).items():
            if key.startswith('seed:'):
                seed = int(key[5:])
                if seed in membership and membership[seed] != split:
                    conflicts.add(seed)
                membership[seed] = split
            elif key.startswith('initial8:'):
                prefix = key[9:]
                if prefix in prefix_split and prefix_split[prefix] != split:
                    # Quarantine the entire linked prefix later.
                    prefix_split[prefix] = 'conflict'
                else:
                    prefix_split[prefix] = split
    for p in sorted(OUTPUTS.glob('rollout_selfplay_*/jobs/*/attempt_*/result.json')):
        try:
            r = load(p)
            if not r.get('valid_for_learning'):
                continue
            seed, prefix = r['game_seed'], r['initial8']
            if seed in conflicts or prefix_split.get(prefix) == 'conflict':
                raise ValueError('historical split conflict')
            split = membership.get(seed, prefix_split.get(prefix))
            if split is None:
                split = 'validation' if int(digest(prefix)[:8], 16) % 5 == 0 else 'train'
            if prefix in seen_prefix and seen_prefix[prefix] != split:
                raise ValueError('linked prefix split collision')
            seen_prefix[prefix] = split
            if seed in seen:
                continue  # sibling replays are not independent new episodes
            new = samples(p.parent, seed, split, prefix, r['actor_sha256'])
            data += new
            seen.add(seed)
            sources.append(dict(path=str(p.parent.resolve()), seed=seed, initial8=prefix, split=split,
                                trace_sha256=sha(p.parent/'trace.jsonl'), actor_sha256=r['actor_sha256']))
        except (OSError, ValueError, KeyError, StopIteration) as e:
            rejected.append(dict(path=str(p), reason=str(e)))
    # Quarantine cross-source collisions instead of silently moving Validation to Train.
    by_prefix = collections.defaultdict(set)
    for r in data:
        by_prefix[r['initial8']].add(r['split'])
    blocked = {p for p, ss in by_prefix.items() if len(ss) > 1}
    data = [r for r in data if r['seed'] not in conflicts and r['initial8'] not in blocked and prefix_split.get(r['initial8'])!='conflict']
    allowed = {r['seed'] for r in data}
    sources = [s for s in sources if s['seed'] in allowed and s['initial8'] not in blocked]
    out.mkdir(parents=True)
    with (out/'replay.jsonl').open('x', encoding='utf8') as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False)+'\n')
    fixtures = []
    # Fixed selection independent of future outcomes: first creation, preceding decision,
    # and last nonterminal decision containing watermelon; no positional preference.
    for src in sources:
        if src['split'] != 'train' or len({x['source_seed'] for x in fixtures}) >= max_roots:
            continue
        rows, _ = read_rows(Path(src['path'])/'trace.jsonl')
        ds = [r for r in rows if r['evt'] == 'decision' and not r['state']['game_over']]
        first = next((i for i, r in enumerate(ds) if any(f['type'] == 10 for f in r['state']['fruits'])), None)
        if first is None:
            continue
        stages = [('before', max(0, first-1)), ('after', first),
                  ('late', max(i for i, r in enumerate(ds) if any(f['type'] == 10 for f in r['state']['fruits'])))]
        used = set()
        for stage, i in stages:
            if i in used:
                continue
            used.add(i)
            r, s = ds[i], ds[i]['state']
            from prepare_candidate_fixtures import fixture
            row = dict(state=s, action_id=r['command']['start_tick'], info=dict(planning=dict(
                drop_range=dict(left_wall_inner=s['geometry'][0], right_wall_inner=s['geometry'][1]),
                floor_y=s['geometry'][2], game_over_y=s['geometry'][3])))
            f = fixture(row, 'post_state', allow_cold=True)
            f.update(source_seed=src['seed'], source_initial8=src['initial8'], source_split='train',
                     source_trace=src['path'], source_trace_sha256=src['trace_sha256'],
                     source_tick=r['tick'], native_checkpoint_exact=False, stage=stage)
            path = out/'fixtures'/f"seed_{src['seed']}_{stage}.json"
            path.parent.mkdir(exist_ok=True)
            write(path, f)
            fixtures.append(dict(path=str(path), sha256=sha(path), source_seed=src['seed'],
                initial8=src['initial8'], split='train', stage=stage, initial_watermelons=sum(x['type']==10 for x in s['fruits'])))
    # Deleted Test19 prefixes cannot be recovered. Do NOT declare a fresh independent Test.
    excluded = set(seen) | {r['seed'] for r in data}
    for p in OUTPUTS.glob('rollout_selfplay_*/collection.json'):
        excluded.update(load(p).get('excluded_seeds', []))
    for p in OUTPUTS.glob('rollout_selfplay_*/jobs/*/job.json'):
        excluded.add(load(p)['game_seed'])
    manifest = dict(version='watermelon-curriculum-v1', replay_sha256=sha(out/'replay.jsonl'),
        rows=len(data), sources=sources, fixtures=fixtures, excluded_seeds=sorted(excluded),
        splits={s:dict(states=sum(r['split']==s for r in data), groups=len({r['initial8'] for r in data if r['split']==s})) for s in ('train','validation')},
        rejected=rejected, conflicts=sorted(conflicts), independent_test=False,
        historical_test_prefixes_recoverable=False,
        test_protection='Only previously approved natural self-play / saved Train-Validation experience reused. All surviving historical excluded seeds blocked for new games. Missing Test19 prefix registry is NOT claimed restored.',
        approximation='Cold fixtures omit solver caches and original random/contact history; never exact historical states')
    write(out/'manifest.json', manifest)
    return manifest


def audit_trial(folder, exit_code, error=None):
    folder = Path(folder)
    cfg = load(folder/'config.json')
    rows, partial = read_rows(folder/'trace.jsonl')
    end = next((r for r in reversed(rows) if r['evt']=='end'), None)
    result = dict(natural_go=False, exit_code=exit_code, process_error=error,
                  approximate=not cfg['normal_start'], final_score=None, additional_score=None,
                  drops=sum(r['evt']=='release' for r in rows), new_watermelons=None,
                  double_watermelons=None, two_present=None)
    try:
        ds=[r for r in rows if r['evt']=='decision']
        if any(r['search']['completed_iterations']!=cfg['iterations'] or not r['search']['source_unchanged']
               or sum(c['visits'] for c in r['search']['root'])!=cfg['iterations']
               or r['rollout']['model_sha256']!=cfg['actor_sha256'] for r in ds):
            raise ValueError('search/actor audit failed')
        result['iterations']=[r['search']['completed_iterations'] for r in ds]
        result['retained_scenes_max']=max((r['retained_scenes'] for r in ds),default=None)
        if not cfg['normal_start']:
            root=next(r for r in rows if r['evt']=='root')
            diff=public_difference(load(cfg['fixture'])['snapshot'],root['state'])
            result['initial_public_audit']=diff
            if not diff['all_compared_fields_equal']:
                raise ValueError('initial public fixture fields mismatch; no valid teacher')
    except (ValueError,KeyError,StopIteration) as e:
        error=error or str(e);result['process_error']=error
    reason = error or ('invalid_trace' if partial else end['reason'] if end else 'missing_end')
    if end and not partial and not error and exit_code==0:
        result.update(natural_go=bool(end['natural_go'] and not end['truncated']),
            new_watermelons=end['new_watermelons'], double_watermelons=end['double_watermelons'],
            two_present=end['two_watermelons_present'], reason=reason,
            last_score=end['score'], initial_score=end['initial_score'])
        if result['natural_go']:
            result.update(final_score=end['score'], additional_score=end['additional_score'])
    result['reason'] = reason
    from material_progress import analyze
    result['material_progress']=analyze(rows)
    if cfg.get('material_progress') and rows:
        native=(rows[-1].get('raw_events') or {}).get('materials') or {}
        from material_progress import VERSION,inventory
        root=next((r for r in rows if r.get('evt')=='root'),None)
        initial=(root.get('raw_events') or {}).get('materials') or {} if root else {}
        counts=inventory(root['state']) if root else {}
        initial_matches=initial.get('counts')==[counts.get(i,0) for i in range(11)]
        if not native.get('known') or native.get('version')!=VERSION or not initial_matches:
            result.update(natural_go=False,final_score=None,additional_score=None,
                          process_error='required atomic material observation missing or inconsistent',reason='material_audit_failed')
    if (folder/'trace.jsonl').exists():result['trace_sha256']=sha(folder/'trace.jsonl')
    # Persist, then re-use strict training audit. Capped episodes retain observations only.
    atomic(folder/'result.json', result)
    if result['natural_go']:
        try:
            completed_trace(folder, cfg['actor_sha256'])
        except (ValueError, KeyError, StopIteration, OSError) as e:
            result.update(natural_go=False, final_score=None, additional_score=None, process_error=str(e), reason='audit_failed')
            atomic(folder/'result.json', result)
    return result


def collect(dataset, out, model, workers=2, hours=8, max_jobs=1000, max_drops=100000,
            seconds=14400, resume=False, base_port=44800, exe=None, curriculum_policy=None,
            material_observation=None, progress_bonus_points=0.):
    from compare_watermelon_dynamic import active_players
    from suika_ai.parallel_play import check_ports, worker_specs
    dataset, out, model = map(lambda p:Path(p).resolve(), (dataset,out,model))
    manifest = load(dataset/'manifest.json')
    import shutil
    if shutil.disk_usage(out.parent if out.parent.exists() else OUTPUTS).free < 4*1024**3:
        raise RuntimeError('Less than 4 GiB free; do not start collection')
    if not 1<=workers<=4 or not 0<hours<=168 or not 0<seconds<=14400 or not 1<=max_drops<=100000 or not 1<=max_jobs<=10000:
        raise ValueError('invalid collection limits')
    if active_players():
        raise RuntimeError('Existing Player active; left untouched')
    if not manifest['fixtures']:
        raise ValueError('No training curriculum fixtures')
    exe=Path(exe or manifest.get('recommended_exe',DEFAULT_EXE)).resolve()
    curriculum_policy=curriculum_policy or manifest.get('curriculum_policy','legacy')
    if curriculum_policy not in ('legacy','progress-balanced'):raise ValueError('unknown curriculum policy')
    material_observation=manifest.get('material_progress',False) if material_observation is None else material_observation
    if not 0<=progress_bonus_points<=100:raise ValueError('progress bonus unit must be 0..100')
    assembly = exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'
    if resume:
        plan = load(out/'plan.json')
        dataset, model = Path(plan['dataset']), Path(plan['model'])
        workers, hours, seconds, max_drops, max_jobs, base_port = [plan[k] for k in ('workers','hours','seconds','max_drops','max_jobs','base_port')]
        manifest = load(dataset/'manifest.json')
        exe=Path(plan.get('exe',DEFAULT_EXE));assembly=exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'
    else:
        if out.exists():
            raise FileExistsError(out)
        plan = dict(dataset=str(dataset), manifest_sha256=sha(dataset/'manifest.json'), model=str(model),
            actor_sha256=sha(model), exe=str(exe),exe_sha256=sha(exe), assembly_sha256=sha(assembly),
            workers=workers, hours=hours, seconds=seconds, max_drops=max_drops, max_jobs=max_jobs,
            base_port=base_port, session=uuid.uuid4().hex, seed_base=secrets.randbelow(1000000000)+1000000000,
            curriculum='alternating normal game and train-only approximate fixture; fixed per game',
            native_resume=False, automatic_promotion=False,curriculum_policy=curriculum_policy,
            material_progress=material_observation,progress_bonus_points=progress_bonus_points)
        excluded=set(manifest['excluded_seeds'])
        for p in OUTPUTS.glob('rollout_selfplay_*/jobs/*/job.json'):excluded.add(load(p)['game_seed'])
        for p in OUTPUTS.glob('watermelon_*/jobs/*/job.json'):
            spec=load(p)
            if 'game_seed' in spec:excluded.add(spec['game_seed'])
        plan['excluded_seeds']=sorted(excluded)
        plan['replay_sessions']=[str(p.parent.resolve()) for p in sorted(OUTPUTS.glob('watermelon_*/plan.json'))
            if load(p).get('manifest_sha256')==plan['manifest_sha256']
            and (p.parent/'runtime.json').exists() and not load(p.parent/'runtime.json').get('active_jobs')]
        out.mkdir(parents=True)
        write(out/'plan.json', plan)
    for path, expected in [(model,plan['actor_sha256']),(exe,plan['exe_sha256']),(assembly,plan['assembly_sha256']),(dataset/'manifest.json',plan['manifest_sha256'])]:
        if sha(path)!=expected:
            raise ValueError('Pinned asset changed: '+str(path))
    # Historical missing Test19 prefix identities remain unknown. Reuse no historical
    # seed, including incomplete attempts; no new independent-Test claim is made.
    check_ports(worker_specs(workers,base_port))
    fixtures=manifest['fixtures'];excluded=set(plan.get('excluded_seeds',manifest['excluded_seeds']));active={}
    previous=load(out/'runtime.json').get('used_seconds',0) if (out/'runtime.json').exists() else 0
    began=time.monotonic();drain=False;forced=False;last_save=0;consecutive_failures=0
    with exclusive_lock(OUTPUTS/'watermelon_curriculum_collector.lock'), exclusive_lock(out/'collector.lock'), (out/'events.jsonl').open('a',encoding='utf8') as events:
        def emit(event,**kw):
            events.write(json.dumps(dict(event=event,unix=time.time(),**kw))+'\n');events.flush()
            display={k:v for k,v in kw.items() if k not in ('material_progress','iterations','initial_public_audit','trace_sha256')}
            if kw.get('material_progress'):
                display['new_material_goals']=[k for k,v in kw['material_progress']['goals'].items() if v['new'] is True]
            print(json.dumps(dict(event=event,**display)),flush=True)
        def allocate():
            for i in range(max_jobs):
                job=out/'jobs'/f'job_{i:06d}'
                if any(a['job']==job for a in active.values()):
                    continue
                attempts=sorted(job.glob('attempt_*'))
                for attempt in attempts:
                    if not (attempt/'result.json').exists():
                        if (attempt/'config.json').exists():audit_trial(attempt,None,'abandoned')
                        else:atomic(attempt/'result.json',dict(natural_go=False,exit_code=None,reason='abandoned',
                            approximate=None,final_score=None,additional_score=None,process_error='launch interrupted before config save'))
                results=[load(p/'result.json') for p in attempts if (p/'result.json').exists()]
                if any(r['natural_go'] or r['reason'] in ('wall_limit','drop_limit') for r in results):
                    continue
                if sum(r['reason'] not in ('interrupted','abandoned') for r in results)>=2:
                    continue
                cfgpath=job/'job.json'
                if cfgpath.exists():
                    spec=load(cfgpath)
                else:
                    from material_progress import select_fixture
                    normal=i%2==0;f=select_fixture(fixtures,i//2,plan.get('curriculum_policy','legacy'))
                    seed=plan['seed_base']+i
                    while seed in excluded:seed+=max_jobs
                    spec=dict(index=i,normal_start=normal,game_seed=seed,future_seed=seed,
                        source_seed=seed if normal else f['source_seed'],initial8=None if normal else f['initial8'],
                        fixture=None if normal else f['path'],fixture_sha256=None if normal else f['sha256'],
                        material_stages=[] if normal else f.get('stages',[f['stage']]),
                        search_seed=int(digest([plan['session'],i])[:7],16))
                    job.mkdir(parents=True,exist_ok=True);write(cfgpath,spec)
                if spec['fixture'] and sha(spec['fixture'])!=spec['fixture_sha256']:
                    raise ValueError('Fixture changed')
                folder=job/f'attempt_{len(attempts):03d}';folder.mkdir()
                return job,folder,spec
            return None
        def launch(slot,item):
            job,folder,spec=item
            if sha(model)!=plan['actor_sha256']:
                raise ValueError('Actor changed during collection')
            cfg=dict(spec,output=str(folder/'trace.jsonl'),policy_model=str(model),actor_sha256=plan['actor_sha256'],
                mode='learned',mixture=.5,final_selection='legacy',iterations=256,depth=4,
                max_drops=max_drops,max_seconds=seconds,first_x=-1,material_progress=plan.get('material_progress',False))
            write(folder/'config.json',cfg);port=base_port+2*slot
            args=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-events','1',
                '--suika-seed',str(spec['game_seed']),'--suika-listen-port',str(port),'--suika-python-port',str(port+1),
                '-suikaRuntimeProbe',str(folder/'runtime.jsonl'),'-suikaPolicySelfPlayLab',str(folder/'config.json'),'-logFile',str(folder/'player.log')]
            proc=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            active[slot]=dict(proc=proc,job=job,folder=folder,began=time.monotonic(),progress=time.monotonic(),size=0)
            write(folder/'launch.json',dict(pid=proc.pid,command=args))
            emit('job_start',job=spec['index'],normal_start=spec['normal_start'],slot=slot)
        try:
            while True:
                try:
                    expired=previous+time.monotonic()-began>=hours*3600
                    launched=False
                    if not drain and not expired:
                        if shutil.disk_usage(out).free<2*1024**3:
                            drain=True;emit('disk_draining',reason='less than 2 GiB free; finish current games, no new jobs')
                        for slot in range(workers):
                            if drain:break
                            if slot not in active:
                                item=allocate()
                                if item:launch(slot,item);launched=True
                    finished=False
                    for slot,a in list(active.items()):
                        path=a['folder']/'trace.jsonl';size=path.stat().st_size if path.exists() else 0
                        if size!=a['size']:a.update(size=size,progress=time.monotonic())
                        error='interrupted' if forced else 'progress_timeout' if time.monotonic()-a['progress']>720 else 'process_timeout' if time.monotonic()-a['began']>seconds+720 else None
                        if error and a['proc'].poll() is None:a['proc'].terminate()
                        if a['proc'].poll() is not None:
                            a['proc'].wait();r=audit_trial(a['folder'],a['proc'].returncode,error)
                            emit('job_end',folder=str(a['folder']),**r);del active[slot];finished=True
                            technical=bool(r['process_error']) or r['reason'] not in ('natural_go','wall_limit','drop_limit','interrupted')
                            consecutive_failures=consecutive_failures+1 if technical else 0
                            if consecutive_failures>=3:
                                drain=True;emit('circuit_breaker',reason='three consecutive technical failures; no new jobs')
                    if time.monotonic()-last_save>5:
                        last_save=time.monotonic()
                        atomic(out/'runtime.json',dict(used_seconds=previous+time.monotonic()-began,active_jobs=[str(a['job']) for a in active.values()],draining=drain or expired,forced=forced))
                        from suika_ai.overnight_collection import process_memory
                        with (out/'resources.jsonl').open('a',encoding='utf8') as resources:
                            for a in active.values():resources.write(json.dumps(dict(unix=time.time(),pid=a['proc'].pid,memory=process_memory(a['proc'].pid)))+'\n')
                    if not active and not ((finished or launched) and not drain and not expired):break
                    time.sleep(.25)
                except KeyboardInterrupt:
                    if drain:forced=True;emit('interrupt_force')
                    else:drain=True;emit('interrupt_drain')
        finally:
            for a in active.values():
                if a['proc'].poll() is None:a['proc'].terminate();a['proc'].wait(10)
                if not (a['folder']/'result.json').exists():audit_trial(a['folder'],a['proc'].returncode,'interrupted')
            atomic(out/'runtime.json',dict(used_seconds=previous+time.monotonic()-began,active_jobs=[],draining=True,forced=forced))
    return summarize(out)


def summarize(out):
    results=[]
    for job in sorted((Path(out)/'jobs').glob('job_*')):
        rs=[load(p) for p in sorted(job.glob('attempt_*/result.json'))]
        if rs:results.append(next((r for r in rs if r['natural_go']),rs[-1]))
    value={}
    for approximate in (False,True):
        rs=[r for r in results if r['approximate']==approximate and r['natural_go']]
        scores=[r['additional_score'] for r in rs]
        value['approximate' if approximate else 'normal']=dict(natural_go=len(rs),
            mean_additional=statistics.mean(scores) if scores else None,
            new_watermelons=sum(r['new_watermelons'] for r in rs),two_present=sum(r['two_present'] for r in rs),
            doubles=sum(r['double_watermelons'] for r in rs))
        from material_progress import rates
        observed=[r['material_progress'] for r in rs if r.get('material_progress')]
        value['approximate' if approximate else 'normal']['material_progress']=dict(
            games_with_records=len(observed),unknown_games=len(rs)-len(observed),goals=rates(observed))
    value['censored_or_failed']=sum(not r['natural_go'] for r in results)
    value['termination_reasons']=dict(collections.Counter(r.get('reason','unknown') for r in results))
    observed_caps=[r['material_progress'] for r in results if not r['natural_go'] and r.get('reason') in ('drop_limit','wall_limit') and not r.get('process_error') and r.get('material_progress')]
    from material_progress import GOALS
    value['censored_observed_new_materials']={k:sum(p['goals'][k]['new'] is True for p in observed_caps) for k in GOALS}
    return value


def train(dataset, model, out, sessions=(), epochs=25, continuations=(), progress_bonus_points=0.):
    """Bounded outcome-weighted rollout imitation, grouped source-game Validation.

    This is NOT evidence of stronger play or a new online RL reward function.
    """
    import numpy as np
    import torch
    from rollout_experience_learning import advantage_weights
    started=time.monotonic();dataset,model,out=map(Path,(dataset,model,out))
    if out.exists():raise FileExistsError(out)
    if not 1<=epochs<=100:raise ValueError('epochs must be 1..100')
    m=load(dataset/'manifest.json')
    replay_path=Path(m.get('replay_file',dataset/'replay.jsonl'))
    if sha(replay_path)!=m['replay_sha256']:raise ValueError('Replay changed')
    with replay_path.open(encoding='utf8') as replay:
        rows=bounded_records(json.loads(line) for line in replay)
    folders=list(map(Path,continuations))
    # Explicit session list only: no live directories silently added during training.
    for session in sessions:
        for job in sorted((Path(session)/'jobs').glob('job_*')):
            for p in sorted(job.glob('attempt_*/result.json')):
                if not load(p)['natural_go']:continue
                folders.append(p.parent);break
    for folder in dict.fromkeys(p.resolve() for p in folders):
        cfg=load(folder/'config.json');trace,_=read_rows(folder/'trace.jsonl')
        root=next(r for r in trace if r['evt']=='root')
        actor=cfg.get('actor_sha256') or next(r['rollout']['model_sha256'] for r in trace if r['evt']=='decision')
        if sha(cfg['policy_model'])!=actor:raise ValueError('Continuation actor file/log mismatch')
        if cfg['normal_start']:
            release=[r for r in trace if r['evt']=='release']
            sequence=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in release]
            if len(sequence)<8:raise ValueError('Initial sequence incomplete')
            prefix=','.join(map(str,sequence[:8]));group=cfg['game_seed']
            inherited={r['split'] for r in rows if r['seed']==group or r['initial8']==prefix}
            if len(inherited)>1:raise ValueError('Inherited split conflict')
            split=next(iter(inherited)) if inherited else 'validation' if int(digest(prefix)[:8],16)%5==0 else 'train'
        else:
            f=load(cfg['fixture']);prefix=f['source_initial8'];group=f['source_seed']
            inherited={r['split'] for r in rows if r['seed']==group or r['initial8']==prefix}
            if len(inherited)!=1:raise ValueError('Approximate fixture requires known original source split')
            split=next(iter(inherited))
            if f.get('source_split',split)!=split:raise ValueError('Fixture ancestry split mismatch')
        rows+=samples(folder,group,split,prefix,actor)
    # Group by seed OR fruit prefix, including all fixture descendants.
    parent={}
    def find(x):
        parent.setdefault(x,x)
        if parent[x]!=x:parent[x]=find(parent[x])
        return parent[x]
    for r in rows:parent[find(('seed',r['seed']))]=find(('prefix',r['initial8']))
    splits=collections.defaultdict(set)
    for r in rows:splits[find(('seed',r['seed']))].add(r['split'])
    if any(len(v)>1 for v in splits.values()):raise ValueError('Linked source group crosses Train/Validation')
    keys={};unique=[]
    for r in rows:
        key=(r['episode'],r['action_id'])
        if key not in keys:unique.append(r);keys[key]=True
    # Deterministic bounded per-episode sampling retains early and last decisions.
    # Prevent long/repeated trajectories from consuming all RAM or teacher mass.
    rows=bounded_records(unique)
    groups=[find(('seed',r['seed'])) for r in rows];group_ids={g:i for i,g in enumerate(sorted(set(groups)))}
    gg=np.array([group_ids[g] for g in groups]);tm=np.array([r['split']=='train' for r in rows])
    if len(set(gg[tm]))<3 or not (~tm).any():raise ValueError('Need >=3 Train groups and held-out Validation')
    x=np.stack([features(r['sample']) for r in rows]).astype(np.float32);y=np.array([r['return_points'] for r in rows])
    counts=collections.Counter((gg[i],r['source_kind']) for i,r in enumerate(rows))
    base=np.array([min(2,max(.5,math.sqrt(r['actual_iterations']/256)))/counts[(gg[i],r['source_kind'])] for i,r in enumerate(rows)],dtype=np.float32)
    # Source groups have equal total mass; repeated futures cannot multiply their weight.
    for g in set(gg):base[gg==g]/=base[gg==g].sum()
    from material_progress import bonus_points,GOALS,BONUS_UNITS,BONUS_RECIPE
    bonuses=np.array([bonus_points(r.get('progress_labels') or {},progress_bonus_points)
                      if r.get('progress_observation_complete') else 0. for r in rows])
    aw,pred,baseline=advantage_weights(x,y,gg,tm,base)
    # Validation remains score-only across both modes, so bonus settings do not
    # manufacture an improvement merely by changing the reported metric.
    score_aw=aw.copy()
    if progress_bonus_points:
        shaped,_,learning_baseline=advantage_weights(x,y+bonuses,gg,tm,base)
        aw[tm]=shaped[tm]
    torch.set_num_threads(1);torch.manual_seed(20261111)
    actor=load(model);initial=torch.tensor(actor['weights'],dtype=torch.float32);theta=initial.clone().requires_grad_()
    tx=torch.tensor(x);tv=torch.tensor(np.stack([np.array(r['visits'])/sum(r['visits']) for r in rows]),dtype=torch.float32)
    sel=torch.tensor([r['selected_index'] for r in rows]);bw=torch.tensor(base);ow=torch.tensor(aw,dtype=torch.float32)
    tr=torch.tensor(np.flatnonzero(tm));va=torch.tensor(np.flatnonzero(~tm));opt=torch.optim.Adam([theta],lr=.01)
    def loss(ids):
        lp=(tx[ids]@theta).log_softmax(-1);soft=-(tv[ids]*lp).sum(-1);hard=-lp[torch.arange(len(ids)),sel[ids]]
        return (bw[ids]*(.75*soft+.25*ow[ids]*hard)).sum()/(bw[ids]*(.75+.25*ow[ids])).sum()
    def metrics(ids):
        with torch.no_grad():return dict(loss=float(loss(ids)),match=float((bw[ids]*((tx[ids]@theta).argmax(-1)==sel[ids])).sum()/bw[ids].sum()),states=len(ids),groups=len(set(gg[ids.tolist()])))
    before=metrics(va);best=before['loss'];weights=initial.clone();history=[]
    for epoch in range(epochs):
        opt.zero_grad();ll=loss(tr)+.01*((theta-initial)**2).mean();ll.backward();opt.step();v=metrics(va);history.append(v)
        if v['loss']<best:best=v['loss'];weights=theta.detach().clone()
    with torch.no_grad():theta.copy_(weights)
    out.mkdir(parents=True);write(out/'model.json',dict(actor,weights=weights.tolist(),parent_sha256=sha(model),
        generation=digest([sha(dataset/'manifest.json'),sha(model),list(map(str,sessions)),list(map(str,continuations)),epochs,progress_bonus_points,BONUS_UNITS]),
        learning='curriculum observed-return weighted imitation; optional first-attainment bonus; not promoted'))
    assert np.isfinite(probabilities(load(out/'model.json'),rows[0]['sample'])).all()
    write(out/'training_plan.json',dict(dataset=str(dataset.resolve()),dataset_sha256=sha(replay_path),
        parent_model=str(model.resolve()),parent_sha256=sha(model),sessions=list(map(str,sessions)),continuations=list(map(str,continuations)),
        continuation_trace_sha256={str(p):sha(p/'trace.jsonl') for p in folders},
        epochs=epochs,seed=20261111,optimizer='Adam',learning_rate=.01,anchor=.01,
        objective='75% root visits + 25% selected action, bounded outcome weight .5..2; equal source-group mass',
        max_states_per_episode=64,independent_test=False,progress_bonus_points=progress_bonus_points,
        progress_bonus_units=BONUS_UNITS,progress_bonus_recipe=BONUS_RECIPE,
        groups=[dict(group=str(g),split=next(r['split'] for i,r in enumerate(rows) if groups[i]==g)) for g in sorted(set(groups))]))
    report=dict(seconds=time.monotonic()-started,train=metrics(tr),validation=metrics(va),parent_validation=before,
        epochs=epochs,model=str(out/'model.json'),model_sha256=sha(out/'model.json'),parent_sha256=sha(model),
        independent_test=False,automatic_promotion=False,rows=len(rows),
        max_states_per_episode=64,
        source_kinds=dict(collections.Counter(r['source_kind'] for r in rows)),
        event_labels={k:dict(known=sum(r.get('events') is not None and r['events'].get(k) is not None for r in rows),
                            positive=sum(bool((r.get('events') or {}).get(k)) for r in rows)) for k in ('new_watermelon','two_present','double')},
        reward_note='Event bonus is learning-only and optional; actual game returns unchanged. Absent successes cannot teach double watermelon. Approximate and normal provenance preserved.',
        history=history)
    report['progress_labels']={k:dict(known=sum((r.get('progress_labels') or {}).get(k) is not None for r in rows),
                                    positive=sum((r.get('progress_labels') or {}).get(k) is True for r in rows)) for k in GOALS}
    report['learning_bonus']=dict(unit_points=progress_bonus_points,max_points=float(bonuses.max()),
        states_with_bonus=int((bonuses>0).sum()),validation_metric='score-only outcome weights',
        units=BONUS_UNITS,recipe=BONUS_RECIPE,
        warning='Optional shaping for learning only. May reduce actual score; not a proven improvement.')
    with (out/'learning_labels.jsonl').open('x',encoding='utf8') as f:
        for i,r in enumerate(rows):f.write(json.dumps(dict(episode=r['episode'],action_id=r['action_id'],split=r['split'],source_group=int(gg[i]),
            actual_game_return=float(y[i]),learning_bonus=float(bonuses[i]),learning_return=float(y[i]+bonuses[i]),
            progress_labels=r.get('progress_labels'),progress_observation_complete=r.get('progress_observation_complete',False),
            score_outcome_weight=float(score_aw[i]),learning_outcome_weight=float(aw[i])))+'\n')
    if progress_bonus_points:write(out/'learning_baseline.json',learning_baseline)
    write(out/'evaluation.json',report);write(out/'state_baseline.json',baseline);write(out/'complete.json',dict(model_sha256=report['model_sha256']))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('prepare');a.add_argument('--output',type=Path,required=True);a.add_argument('--max-roots',type=int,default=24)
    a=s.add_parser('prepare-progress');a.add_argument('--dataset',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--max-roots',type=int,default=24);a.add_argument('--source-limit',type=int,default=64)
    a=s.add_parser('collect');a.add_argument('--dataset',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--model',type=Path,required=True);a.add_argument('--workers',type=int,default=2);a.add_argument('--hours',type=float,default=8);a.add_argument('--max-jobs',type=int,default=1000);a.add_argument('--max-drops',type=int,default=100000);a.add_argument('--game-seconds',type=float,default=14400);a.add_argument('--resume',action='store_true');a.add_argument('--base-port',type=int,default=44800);a.add_argument('--no-train',action='store_true')
    a=s.add_parser('summary');a.add_argument('--output',type=Path,required=True)
    a=s.add_parser('train');a.add_argument('--dataset',type=Path,required=True);a.add_argument('--model',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--session',type=Path,action='append',default=[]);a.add_argument('--continuation',type=Path,action='append',default=[]);a.add_argument('--epochs',type=int,default=25)
    for name in ('collect','train'):s.choices[name].add_argument('--progress-bonus-points',type=float,default=0.)
    s.choices['collect'].add_argument('--exe',type=Path)
    s.choices['collect'].add_argument('--curriculum-policy',choices=['legacy','progress-balanced'])
    s.choices['collect'].add_argument('--material-progress',action=argparse.BooleanOptionalAction,default=None)
    a=p.parse_args()
    if a.cmd=='prepare':r=prepare(a.output,a.max_roots);r={k:v for k,v in r.items() if k not in ('sources','fixtures','excluded_seeds')};r['manifest']=str(a.output/'manifest.json')
    elif a.cmd=='prepare-progress':
        from prepare_material_curriculum import prepare_progress
        r=prepare_progress(a.dataset,a.output,a.max_roots,a.source_limit)
    elif a.cmd=='collect':
        r=collect(a.dataset,a.output,a.model,a.workers,a.hours,a.max_jobs,a.max_drops,a.game_seconds,a.resume,a.base_port,a.exe,a.curriculum_policy,a.material_progress,a.progress_bonus_points)
        forced=load(a.output/'runtime.json').get('forced',False)
        if forced:r['training_status']='skipped_after_forced_stop; completed experience preserved for later training'
        if not forced and not a.no_train and sum(r[k]['natural_go'] for k in ('normal','approximate')):
            cfg=load(a.output/'plan.json')
            sessions=[Path(x) for x in cfg.get('replay_sessions',[])]+[a.output]
            traces=[sha(p.parent/'trace.jsonl') for session in sessions for p in sorted(session.glob('jobs/*/attempt_*/result.json')) if load(p)['natural_go']]
            def fit(unit):
                from material_progress import BONUS_UNITS,BONUS_RECIPE
                generation=a.output/'generations'/('gen_'+digest([cfg['actor_sha256'],cfg['manifest_sha256'],traces,'curriculum-v2',unit,BONUS_UNITS,BONUS_RECIPE])[:12])
                if (generation/'complete.json').exists():
                    marker=load(generation/'complete.json')
                    if sha(generation/'model.json')!=marker['model_sha256']:raise ValueError('Completed generation model changed')
                    return dict(status='already_trained',model=str(generation/'model.json'))
                if generation.exists():generation=generation.with_name(generation.name+'_attempt_'+uuid.uuid4().hex[:8])
                return train(cfg['dataset'],cfg['model'],generation,sessions,progress_bonus_points=unit)
            r['training']=fit(0.)
            if cfg.get('progress_bonus_points',0.):r['progress_training']=fit(cfg['progress_bonus_points'])
    elif a.cmd=='summary':r=summarize(a.output)
    else:r=train(a.dataset,a.model,a.output,a.session,a.epochs,a.continuation,a.progress_bonus_points)
    print(json.dumps(r,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
