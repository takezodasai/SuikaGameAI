"""Resumable serial branch-label collection, isolated from production collectors.

Immutable plan/attempts, durable per-task commits, explicit censoring, no training.
Uses the existing Watermelon Lab baseline Player and unmodified legacy MCTS.
"""
import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

from watermelon_lab import ROOT, sha, write
from prepare_candidate_fixtures import fixture
from branch_action_teacher import load, records, run_trial, compare_trials, policy
from staged_action_experiment import choose_alternative
from compare_watermelon_dynamic import active_players
from suika_ai.collection_audit import initial_sequence
from suika_ai.collection_metadata import atomic_metadata as atomic_json
from suika_ai.overnight_collection import exclusive_lock
from branch_trial_registry import branch_plans, check_new_trial, clone_plan, preview_plan


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def known_branch_groups(outputs=None,exclude=None):
    outputs=Path(outputs) if outputs is not None else ROOT/'Python/outputs'
    seeds,prefixes,plans=set(),set(),[]
    for path,data in branch_plans(outputs,exclude):
        if exclude is not None and path.parent.resolve()==Path(exclude).resolve():continue
        data=load(path);plans.append(str(path.resolve()))
        for root in data.get('roots',[])+data.get('inventory',[]):
            root=dict(fixture=root) if isinstance(root,str) else root
            seed=root.get('source_seed',root.get('seed'));prefix=root.get('source_initial_sequence')
            f=root.get('fixture')
            if f and Path(f).exists():
                meta=load(f);seed=meta.get('source_seed',seed);prefix=meta.get('source_initial_sequence',prefix)
                source=meta.get('source_file')
                if not prefix and source and Path(source).exists():
                    early=[]
                    with Path(source).open(encoding='utf-8-sig') as stream:
                        for line in stream:
                            row=json.loads(line)
                            if row.get('event')=='transition':early.append(row)
                            if len(early)==8:break
                    prefix=initial_sequence(early)
            if type(seed) is int:seeds.add(seed)
            if prefix:prefixes.add(prefix)
    return seeds,prefixes,plans


def select_stage(transitions, phase):
    first = next(i for i, r in enumerate(transitions) if any(f['type'] == 10 for f in r['state']['fruits']))
    candidates = list(reversed(transitions[:first])) if phase == 'before' else transitions[first:]
    return next(r for r in candidates if not r['state']['game_over']
                and r['state']['current_fruit']['present']
                and not any(f.get('is_merging') for f in r['state']['fruits']))


def fixed_branch_selection(decision):
    try:
        selection=choose_alternative(decision)
        if selection['alternative_x']==selection['recommended_x']:raise ValueError('Same coordinate')
        return selection
    except ValueError as e:
        return dict(recommended_x=decision['planning']['selected_x'],recommended_index=decision['planning']['selected_index'],
            alternative_x=None,alternative_index=None,candidates=decision['search']['root'],unavailable=True,reason=str(e))


def prepare(source, out, count=4, budget=7200, game_seconds=600, dry_run=False, future_seeds=None):
    if not 4 <= count <= 8 or not 0 < budget <= 7200 or not 0 < game_seconds <= 600:
        raise ValueError('4..8 roots, <=7200 total seconds, <=600 per game')
    future_seeds=[2026110301,2026110302] if future_seeds is None else list(future_seeds)
    if len(future_seeds)!=2 or len(set(future_seeds))!=2:raise ValueError('Two distinct future seeds required')
    reserved_path = ROOT / 'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json'
    reserved = load(reserved_path)['episodes']
    prior_path = ROOT / 'Python/outputs/branch_teacher_jobs18_29_01/plan.json'
    prior = load(prior_path)['roots']
    known_seed,known_prefix,known_plans=known_branch_groups(exclude=out)
    forbidden_seed = {e['seed'] for e in reserved} | {r['source_seed'] for r in prior} | known_seed
    forbidden_prefix = {e['initial_sequence'] for e in reserved} | {r['source_initial_sequence'] for r in prior} | known_prefix
    catalog, eligible = [], []
    for jobdir in sorted((source / 'jobs').glob('job_*')):
        attempts = sorted(p for p in jobdir.glob('attempt_*') if p.is_dir())
        if not attempts:continue
        a = attempts[-1];resultfile = jobdir / (a.name + '_result.json')
        if not resultfile.exists():continue
        result = load(resultfile)
        if not result.get('valid_for_return_learning') or not result.get('watermelon_events'):continue
        item = dict(job=result['job'], seed=result['game_seed'], attempt=str(a.resolve()))
        if item['seed'] in forbidden_seed:
            reason='reserved Test seed' if item['seed'] in {e['seed'] for e in reserved} else 'previously used source seed'
            catalog.append(dict(item, excluded=reason));continue
        rs = records(a / 'game_00.jsonl');prefix = initial_sequence(rs)
        if not prefix:
            catalog.append(dict(item, excluded='unknown initial8 group'));continue
        if prefix in forbidden_prefix:
            reason='reserved Test initial8' if prefix in {e['initial_sequence'] for e in reserved} else 'previously used initial8 group'
            catalog.append(dict(item, excluded=reason));continue
        end = rs[-1]
        if not (end.get('event') == 'episode_end' and end.get('game_over') is True
                and end.get('truncated') is False and end.get('reason') == 'game_over' and end.get('conserved')):
            catalog.append(dict(item, excluded='source terminal not certified'));continue
        item.update(initial_sequence=prefix, source=str((a/'game_00.jsonl').resolve()))
        eligible.append(item);catalog.append(dict(item, excluded=None))
    # Predeclared coverage rule: ascending source seed, alternating before/after.
    # Source final score and all branch outcomes are excluded from this ordering.
    eligible.sort(key=lambda x:(x['seed'],x['source']))
    selected, used_seed, used_prefix = [], set(), set()
    for item in eligible:
        if item['seed'] in used_seed or item['initial_sequence'] in used_prefix:continue
        selected.append(item);used_seed.add(item['seed']);used_prefix.add(item['initial_sequence'])
        if len(selected) == count:break
    summary=dict(new_independent_boards=len(selected), existing_source_overlaps=sum('previously used' in (r.get('excluded') or '') for r in catalog),
                 reserved_source_exclusions=sum('reserved Test' in (r.get('excluded') or '') for r in catalog),
                 requested_roots=count,planned_main_trials=len(selected)*4,available_for_request=len(selected)>=count,
                 selected_source_seeds=[r['seed'] for r in selected],catalog=catalog,
                 note='Seed/initial8 groups, not repeated games. Candidates freeze in survey before main returns.')
    if dry_run:
        print(json.dumps(summary));return summary
    if len(selected) < count:raise ValueError('Insufficient new independent success source groups; use --dry-run for exclusions')
    out.mkdir(parents=True, exist_ok=False)
    roots, board_keys = [], set()
    for index,item in enumerate(selected):
        rs=records(Path(item['source']));ts=[r for r in rs if r.get('event')=='transition' and r.get('info',{}).get('drop_success')]
        phase='before' if index%2==0 else 'after';row=select_stage(ts,phase)
        f=fixture(row,'post_state',allow_cold=True)
        board = dict(fruits=sorted([{k:v for k,v in x.items() if k!='id'} for x in f['fruits']],key=lambda x:(x['type'],x['x'],x['y'])),
                     held=f['snapshot']['current_fruit'],next=f['next_fruit_type'],score=f['score'])
        key=fingerprint(board)
        if key in board_keys:raise ValueError('Duplicate physical board selected')
        board_keys.add(key);rid=f"job_{item['job']}_{phase}"
        f.update(source_file=item['source'],source_sha256=sha(item['source']),source_seed=item['seed'],
                 source_initial_sequence=item['initial_sequence'],source_game_tick=row['state'].get('game_tick'),
                 native_checkpoint_exact=False,source_split='development_diagnostic_not_test',
                 future_rng='new experimental Unity RNG, not historical source RNG')
        target=out/(rid+'.json');write(target,f)
        roots.append(dict(id=rid,phase=phase,fixture=str(target.resolve()),fixture_sha256=sha(target),
                          board_uid=key,source_seed=item['seed'],source_initial_sequence=item['initial_sequence'],
                          source_file=item['source'],source_sha256=f['source_sha256'],source_action_id=row['action_id'],
                          split_keys=[f"game_seed:{item['seed']}",f"initial8:{item['initial_sequence']}"],
                          initial_score=f['score'],initial_watermelons=sum(x['type']==10 for x in f['fruits'])))
    exe=ROOT/'Unity/Builds/StagedAction_02/SuikaGameAI.exe'
    protected={}
    for pattern in ['Unity/Assets/**/*.cs','Python/*.py','Python/src/**/*.py']:
        for f in ROOT.glob(pattern):protected[str(f.resolve())]=sha(f)
    plan=dict(version='branch-batch-v2',collection_intent='new_independent_sources',roots=roots,source_session=str(source.resolve()),selection_catalog=catalog,
              previous_branch_plans=known_plans,
              selection_rule='Ascending source seed, exclude prior/reserved/duplicate seed OR initial8; alternate last clean pre-watermelon / first clean post-watermelon observation',
              candidate_rule='A legacy recommendation; B highest mean other sampled successful immediate-nonGO action; freeze all before any main return',
              future_seeds=future_seeds,continuation=dict(kind='legacy_mcts',iterations=128,depth=4,search_seed=8191),
              exe=str(exe.resolve()),assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'),
              exe_sha256=sha(exe),port=43500,total_seconds=budget,game_seconds=game_seconds,repeat_seconds=45,
              reserved_manifest=str(reserved_path),reserved_sha256=sha(reserved_path),protected=protected,
              split_rule='Union original game seed OR original initial8 across ALL datasets; all actions/futures/retries of a root stay together; these roots are development only')
    write(out/'plan.json',plan);print(json.dumps(dict(roots=[r['id'] for r in roots],source_seed_groups=len(roots))))


def task_spec(plan,root,future,mode,first_x,drops,seconds):
    return dict(root_id=root['id'],fixture_sha256=root['fixture_sha256'],future_seed=future,mode=mode,
                first_x=first_x,drops=drops,seconds=seconds,continuation=policy(plan['continuation']),
                assembly_sha256=plan['assembly_sha256'],exe_sha256=plan['exe_sha256'])


class Batch:
    def __init__(self,out,resume=False,runner=run_trial):
        self.out=Path(out);self.plan=load(self.out/'plan.json');self.runner=runner
        path=self.out/'runtime.json'
        if path.exists() and not resume:raise FileExistsError('Use --resume for an existing batch')
        if resume and not path.exists():raise ValueError('No existing batch to resume')
        self.state=load(path) if path.exists() else dict(plan_sha256=sha(self.out/'plan.json'),used_seconds=0,pending=None)
        if self.state['plan_sha256']!=sha(self.out/'plan.json'):raise ValueError('Frozen plan changed')
        if self.state.get('pending'):
            # Hard-kill recovery: conservatively charge the reserved attempt cap,
            # rather than forgetting in-flight cost or charging paused wall time.
            self.state['used_seconds']+=self.state['pending']['reserved_seconds']
            self.state.setdefault('conservative_recoveries',[]).append(self.state['pending'])
            self.state['pending']=None
        self.base_used=self.state['used_seconds'];self.start=time.monotonic();self.started=False

    def remaining(self):
        remaining=self.plan['total_seconds']-self.base_used-(time.monotonic()-self.start)
        if getattr(self,'external_deadline',None) is not None:remaining=min(remaining,self.external_deadline-time.time()-20)
        return remaining

    def save(self,pending=None):
        self.state.update(used_seconds=self.base_used+time.monotonic()-self.start,pending=pending)
        atomic_json(self.out/'runtime.json',self.state)

    def event(self,kind,**value):
        row=dict(utc=time.time(),event=kind,**value)
        with (self.out/'batch_events.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        print(json.dumps(row),flush=True)

    def _commit(self,folder,attempt,spec,result,recovered=False,result_name='result.json'):
        if result.get('errors') or (result.get('exit_code') not in [None,0]):
            if not getattr(self,'quarantine_trial_errors',False):raise RuntimeError('Native trial failed; preserved, explicit quarantine required')
            if result.get('natural_go'):raise ValueError('Failed native trial cannot be natural GO')
        if result.get('process_error')=='interrupted' and not result.get('end'):
            raise KeyboardInterrupt()
        if result.get('process_error') and not result.get('end'):
            raise RuntimeError('Technical incomplete attempt retained; explicit resume required')
        entry=dict(spec_sha256=fingerprint(spec),attempt=str(attempt.resolve()),
                   result_name=result_name,result_sha256=sha(attempt/result_name),trace_sha256=sha(attempt/'trace.jsonl'),
                   recovered=recovered,natural_go=result['natural_go'])
        if (folder/'completion.json').exists():raise FileExistsError('Task already committed')
        atomic_json(folder/'completion.json',entry)
        self.event('task_commit',task=folder.name,attempt=attempt.name,recovered=recovered,natural_go=result['natural_go'])
        return result,records(attempt/'trace.jsonl')

    def task(self,unit,root,future,mode,seconds,first_x=-1,drops=1000):
        folder=self.out/'tasks'/unit;folder.mkdir(parents=True,exist_ok=True)
        spec=task_spec(self.plan,root,future,mode,first_x,drops,seconds)
        done=folder/'completion.json'
        if done.exists():
            c=load(done);a=Path(c['attempt'])
            result_path=a/c.get('result_name','result.json')
            if c['spec_sha256']!=fingerprint(spec) or sha(result_path)!=c['result_sha256'] or sha(a/'trace.jsonl')!=c['trace_sha256']:
                raise ValueError('Completed task provenance changed')
            self.event('task_reuse',task=unit);return load(result_path),records(a/'trace.jsonl')
        attempts=sorted(p for p in folder.glob('attempt_*') if p.is_dir())
        for a in reversed(attempts):
            if not (a/'spec.json').exists() or load(a/'spec.json')!=spec:
                raise ValueError('Attempt specification changed')
            raw=a/'trial'
            r=None
            if (raw/'result.json').exists():
                try:r=load(raw/'result.json')
                except (ValueError,OSError):pass
                if r and r.get('end'):
                    return self._commit(folder,raw,spec,r,recovered=True)
            if (raw/'trace.jsonl').exists() and (r is None or not r.get('end')):
                # A hard kill can leave a partial final JSONL line. Preserve all
                # bytes, never synthesize a terminal, and retry a NEW attempt.
                try:rs=records(raw/'trace.jsonl')
                except (ValueError,OSError):rs=[]
                if rs and rs[-1]['evt']=='end':
                    from watermelon_lab import summarize
                    r=summarize(rs);r.update(exit_code=None,process_error=None,wall_seconds=rs[-1]['elapsed_seconds'],
                                           recovered_native_end=True,process_exit_verified=False)
                    if not (raw/'result.json').exists():
                        write(raw/'result.json',r)
                    else:
                        # Keep corrupt summary bytes intact; create a separate
                        # recovery summary and let the commit point to it.
                        recovery=raw/'recovered_result.json';number=0
                        while recovery.exists():
                            try:
                                if load(recovery)==r:break
                            except (ValueError,OSError):pass
                            number+=1;recovery=raw/f'recovered_result_{number:03d}.json'
                        if not recovery.exists():write(recovery,r)
                        return self._commit(folder,raw,spec,r,recovered=True,result_name=recovery.name)
                    return self._commit(folder,raw,spec,r,recovered=True)
        if self.remaining()<=30:raise TimeoutError('Study budget exhausted before next task')
        if mode=='baseline' and drops==1000:
            check_new_trial(ROOT/'Python/outputs',self.out,self.plan,root,future,first_x)
        number=max([int(a.name.split('_')[1]) for a in attempts]+[-1])+1
        a=folder/f'attempt_{number:03d}';a.mkdir();write(a/'spec.json',spec)
        # run_trial owns creation of the trial directory. Use an immutable child.
        trial=a/'trial';cap=min(seconds,max(1,self.remaining()-25))
        self.save(dict(task=unit,attempt=str(a),reserved_seconds=cap+25))
        self.event('task_start',task=unit,attempt=a.name,cap_seconds=cap)
        try:
            self.runner(trial,self.plan,root,future,mode,cap,first_x,drops)
        except RuntimeError:
            path=trial/'result.json'
            if path.exists():
                try:
                    failed=load(path)
                    if failed.get('process_error')=='interrupted':raise KeyboardInterrupt()
                    if getattr(self,'quarantine_trial_errors',False) and failed.get('end') and failed.get('root') and not failed.get('natural_go'):
                        self.event('trial_error_quarantined',task=unit,note='Not a natural-GO teacher; do not retry or substitute source')
                        return self._commit(folder,trial,spec,failed)
                except ValueError:pass
            raise
        finally:
            self.save()
        # Normalize nested trial location; spec remains alongside immutable raw trial.
        result=load(trial/'result.json')
        return self._commit(folder,trial,spec,result)


def cached(batch,unit):
    d=batch/'tasks'/unit/'completion.json'
    if not d.exists():return None
    c=load(d);a=Path(c['attempt'])
    result_path=a/c.get('result_name','result.json')
    if sha(result_path)!=c['result_sha256'] or sha(a/'trace.jsonl')!=c['trace_sha256']:
        raise ValueError('Committed artifact changed')
    return a,load(result_path),records(a/'trace.jsonl')


def operator_pause_requested(out,started_unix):
    path=Path(out)/'operator_pause_request.json'
    return path.exists() and load(path).get('requested_unix',0)>=started_unix


def run_batch(out,resume=False,stop_after_pairs=None,deadline_unix=None,quarantine_trial_errors=False):
    out=Path(out)
    with exclusive_lock(out/'batch.lock'):
        if active_players():raise RuntimeError('Existing Player active; leave collection untouched')
        b=Batch(out,resume)
        session_started_unix=time.time()
        b.external_deadline=deadline_unix
        b.quarantine_trial_errors=quarantine_trial_errors
        p=b.plan
        if sha(p['exe'])!=p['exe_sha256'] or sha(Path(p['exe']).parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')!=p['assembly_sha256']:
            raise ValueError('Player changed')
        if sha(p['reserved_manifest'])!=p['reserved_sha256']:raise ValueError('Test reservation changed')
        for r in p['roots']:
            if sha(r['fixture'])!=r['fixture_sha256']:raise ValueError('Fixture changed')
            selection_path=out/(r['id']+'_selection.json')
            if selection_path.exists():
                selection=load(selection_path)
                if selection.get('unavailable'):continue
                for future in p['future_seeds']:
                    for role in ['recommended','alternative']:
                        done=out/'tasks'/f"{r['id']}_f{future}_{role}"/'completion.json'
                        if not done.exists():check_new_trial(ROOT/'Python/outputs',out,p,r,future,selection[role+'_x'])
        b.event('session_start',resume=resume,used_seconds=b.base_used);b.save()
        reason='all_tasks_complete';pairs_this_session=0;durations={}
        try:
            for r in p['roots']:
                if operator_pause_requested(out,session_started_unix):reason='operator_requested_pause';return reason
                rid=r['id'];f0=p['future_seeds'][0]
                _,rs=b.task(f'{rid}_survey',r,f0,'survey',30,drops=1)
                decision=next(x for x in rs if x['evt']=='decision')
                selection=fixed_branch_selection(decision)
                selpath=out/(rid+'_selection.json')
                if selpath.exists():
                    if load(selpath)!=selection:raise ValueError('Frozen candidate selection changed')
                else:write(selpath,selection)
                _,fr=b.task(f'{rid}_future_survey',r,p['future_seeds'][1],'survey',30,drops=1)
                d0=next(x for x in rs if x['evt']=='decision');d1=next(x for x in fr if x['evt']=='decision')
                repeats=[]
                for i in [0,1]:
                    _,rr=b.task(f'{rid}_repeat{i}',r,f0,'baseline',p['repeat_seconds'],selection['recommended_x'],3);repeats.append(rr)
                audit=compare_trials(*repeats)
                audit['all_logged_initial_fields_equal']=repeats[0][0]['state']==repeats[1][0]['state']
                aa,bb=([x for x in rr if x['evt']=='action'] for rr in repeats)
                audit['all_logged_action_fields_equal']=len(aa)==len(bb) and all(x['state']==y['state'] for x,y in zip(aa,bb))
                audit['future_changes_initial_statistics']=d0['search']['root']!=d1['search']['root'] or d0['planning']['selected_x']!=d1['planning']['selected_x']
                path=out/(rid+'_reproducibility.json')
                if not path.exists():write(path,audit)
                elif load(path)!=audit:raise ValueError('Saved reproducibility audit changed')
            # Complete first future across every root before a second future.
            for fi,future in enumerate(p['future_seeds']):
                for ri,r in enumerate(p['roots']):
                    if operator_pause_requested(out,session_started_unix):reason='operator_requested_pause';return reason
                    rid=r['id'];audit=load(out/(rid+'_reproducibility.json'))
                    if not audit['all_logged_initial_fields_equal'] or not audit['initial_rng_equal']:
                        b.event('root_quarantined',root=rid,reason='initial state mismatch');continue
                    selection=load(out/(rid+'_selection.json'))
                    if selection.get('unavailable'):
                        b.event('root_quarantined',root=rid,reason='No distinct eligible B; no replacement source');continue
                    roles=['recommended','alternative'] if (fi+ri)%2==0 else ['alternative','recommended']
                    units=[f'{rid}_f{future}_{role}' for role in roles]
                    pending=[u for u in units if not (out/'tasks'/u/'completion.json').exists()]
                    estimate=max(durations.get(rid,[180]))*len(pending)*1.15+25
                    if pending and b.remaining()<estimate:
                        b.event('pair_deferred',root=rid,future=future,remaining=b.remaining(),estimated_seconds=estimate)
                        reason='budget_insufficient_for_more_pairs';continue
                    for role in roles:
                        unit=f'{rid}_f{future}_{role}'
                        result,_=b.task(unit,r,future,'baseline',p['game_seconds'],selection[role+'_x'])
                        durations.setdefault(rid,[]).append(result['wall_seconds'])
                    if pending:
                        pairs_this_session+=1
                        b.event('pair_complete',root=rid,future=future)
                        if not (out/'pilot_timing.json').exists():
                            pair_seconds=sum(durations[rid][-2:]);write(out/'pilot_timing.json',dict(first_pair_seconds=pair_seconds,
                                 naive_main_total_seconds=pair_seconds*len(p['roots'])*len(p['future_seeds']),
                                 remaining_seconds=b.remaining(),note='Timing estimate only. No candidates, seeds or source boards change.'))
                        aggregate(out)
                        if stop_after_pairs and pairs_this_session>=stop_after_pairs:
                            reason='planned_checkpoint_pause';return reason
        except KeyboardInterrupt:
            reason='interrupted';b.event('interrupted',note='Completed tasks retained; incomplete task retries only into a new attempt')
        except TimeoutError:
            reason='budget_exhausted'
        except Exception as e:
            reason='technical_failure: '+str(e)
            raise
        finally:
            b.state['last_stop_reason']=reason;b.save();b.event('session_end',reason=reason,used_seconds=b.state['used_seconds']);aggregate(out)
        return reason


def aggregate(out):
    out=Path(out);p=load(out/'plan.json');games=[];pairs=[];missing=[]
    for root in p['roots']:
        rid=root['id']
        for future in p['future_seeds']:
            conditions={}
            for role in ['recommended','alternative']:
                unit=f'{rid}_f{future}_{role}';c=cached(out,unit)
                if c is None:missing.append(unit);continue
                path,result,rs=c;start,end=result['root'],result['end'];ds=[r for r in rs if r['evt']=='decision'];cfg=load(path/'config.json')
                natural=bool(result['natural_go'] and end and end['state']['game_over'] and not end['truncated'])
                g=dict(root_id=rid,phase=root['phase'],source_seed=root['source_seed'],source_initial_sequence=root['source_initial_sequence'],
                       split_keys=root['split_keys'],first_x=cfg['first_x'],role=role,future_seed=future,
                       continuation=policy(p['continuation']),natural_go=natural,initial_score=start['score'],
                       initial_watermelons=start['initial_watermelons'],final_score=end['score'] if end else None,
                       actual_return=end['additional_score'] if natural else None,observed_extra=end['additional_score'] if end else None,
                       accepted_drops=end['accepted_drops'] if end else None,new_watermelons=end['new_watermelons'] if end else None,
                       second_watermelon=end['second_watermelon_generated'] if end else None,two_present=end['two_watermelons_present'] if end else None,
                       doubles=end['double_watermelons'] if end else None,reason=end['reason'] if end else 'unknown',
                       wall_seconds=result['wall_seconds'],mean_planning_ms=statistics.mean(d['planning_ms'] for d in ds) if ds else None,
                       all_iterations_correct=bool(ds) and all(d['search']['completed_iterations']==128 and sum(e['visits'] for e in d['search']['root'])==128 for d in ds),
                       source_unchanged=bool(ds) and all(d['search']['source_unchanged'] for d in ds),first_root_statistics=ds[0]['search']['root'] if ds else [],
                       approximation='cold_visible_state_not_native_checkpoint',source='actual_experimental_continuation',
                       trajectory=str((path/'trace.jsonl').resolve()),reproducibility=load(out/(rid+'_reproducibility.json')))
                games.append(g);conditions[role]=(g,rs)
            if len(conditions)==2:
                a,ar=conditions['recommended'];b,br=conditions['alternative'];check=compare_trials(ar,br)
                full_initial=ar[0]['state']==br[0]['state'];repro=a['reproducibility']
                valid=a['natural_go'] and b['natural_go'] and full_initial and check['initial_rng_equal'] and check['common_public_fruits_equal'] and a['source_unchanged'] and b['source_unchanged'] and a['all_iterations_correct'] and b['all_iterations_correct'] and repro['all_logged_initial_fields_equal']
                pairs.append(dict(root_id=rid,phase=root['phase'],source_seed=root['source_seed'],split_keys=root['split_keys'],future_seed=future,
                        valid_conditional_return_pair=valid,recommended_return=a['actual_return'],alternative_return=b['actual_return'],
                        alternative_minus_recommended=b['actual_return']-a['actual_return'] if valid else None,
                        all_logged_initial_fields_equal=full_initial,comparison=check,continuation=policy(p['continuation']),
                        teacher_use='development diagnostics only; not independent Test or true optimal-action labels'))
    report=dict(games=games,pairs=pairs,missing=missing,roots=len(p['roots']),source_group_rule=p['split_rule'],model_training_performed=False)
    # Only owned aggregate files are replaced; raw attempts/commits/plans are immutable.
    atomic_json(out/'teacher.json',report)
    fields=['root_id','phase','source_seed','role','first_x','future_seed','natural_go','actual_return','accepted_drops','new_watermelons','second_watermelon','two_present','doubles','wall_seconds','mean_planning_ms','reason']
    with (out/'teacher.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(games)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['prepare','run','summary','clone','pause'])
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--source',type=Path);ap.add_argument('--roots',type=int,default=4)
    ap.add_argument('--budget-seconds',type=float,default=7200);ap.add_argument('--game-seconds',type=float,default=600)
    ap.add_argument('--resume',action='store_true');ap.add_argument('--stop-after-pairs',type=int)
    ap.add_argument('--dry-run',action='store_true',help='Read-only selection/overlap preview; never launches a Player')
    ap.add_argument('--from-batch',type=Path);ap.add_argument('--future-seeds',nargs=2,type=int)
    ap.add_argument('--intent',choices=['intentional_repeat','new_future_series']);ap.add_argument('--repeat-reason')
    ap.add_argument('--deadline-unix',type=float,help='Optional outer study deadline; can only reduce the frozen batch budget')
    ap.add_argument('--quarantine-trial-errors',action='store_true',help='Retain native ended failures as invalid trials, no retry; continue other frozen conditions')
    args=ap.parse_args()
    if args.dry_run and args.command not in ['prepare','clone']:
        print(json.dumps(preview_plan(args.output)));return
    if args.command=='pause':
        if not (args.output/'plan.json').exists():raise ValueError('No batch plan')
        atomic_json(args.output/'operator_pause_request.json',dict(requested_unix=time.time(),reason='Operator requested completed-pair pause'))
        print('Pause requested; current pair finishes, no new pair starts.');return
    if args.command=='prepare':prepare(args.source,args.output,args.roots,args.budget_seconds,args.game_seconds,args.dry_run,args.future_seeds)
    elif args.command=='clone':
        if not args.from_batch or not args.future_seeds or not args.intent:ap.error('clone requires --from-batch, --future-seeds and --intent')
        print(json.dumps(clone_plan(args.from_batch,args.output,args.future_seeds,args.intent,args.repeat_reason,args.dry_run)))
    elif args.command=='run':
        reason=run_batch(args.output,args.resume,args.stop_after_pairs,args.deadline_unix,args.quarantine_trial_errors)
        if reason=='interrupted':sys.exit(130)
    else:aggregate(args.output)


if __name__=='__main__':main()
