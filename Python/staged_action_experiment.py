"""Fixed-budget root allocation and first-action-only experiments; no training."""
import argparse,json,subprocess,time
from pathlib import Path
from watermelon_lab import ROOT,sha,write,summarize
from compare_watermelon_dynamic import active_players


def choose_alternative(decision):
    recommended=decision['planning']['selected_index'];candidates=decision['search']['root']
    valid=[e for e in candidates if e['index']!=recommended and e['visits']>0 and e['drop_success'] and not e['immediate_go']]
    if not valid:raise ValueError('No distinct eligible alternative; do not replace based on scores')
    alt=max(valid,key=lambda e:(e['mean_points'],e['visits'],-e['index']))
    return dict(recommended_x=decision['planning']['selected_x'],recommended_index=recommended,alternative_x=alt['x'],alternative_index=alt['index'],candidates=candidates)


def trial(folder,exe,fixture,mode,future,seconds,first_x=-1,drops=1000,normal_seed=None):
    from suika_ai.parallel_play import check_ports,worker_specs
    if active_players():raise RuntimeError('External Player active; collection remains untouched')
    check_ports(worker_specs(1,42960));folder.mkdir(parents=True,exist_ok=False)
    cfg=dict(fixture=str(fixture.resolve()) if fixture else '',output=str((folder/'trace.jsonl').resolve()),mode=mode,normal_start=normal_seed is not None,
             game_seed=normal_seed or 20261031,future_seed=future,search_seed=8191,iterations=128,depth=4,max_drops=drops,max_seconds=seconds,first_x=first_x)
    write(folder/'config.json',cfg)
    args=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(normal_seed or future),'--suika-listen-port','42960','--suika-python-port','42961',
          '-suikaRuntimeProbe',str((folder/'runtime.jsonl').resolve()),'-suikaStagedActionLab',str((folder/'config.json').resolve()),'-logFile',str((folder/'player.log').resolve())]
    write(folder/'launch.json',dict(command=args,assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'),fixture_sha256=sha(fixture) if fixture else None))
    proc=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS);start=time.monotonic();error=None
    reserved=json.loads((ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    try:
        while proc.poll() is None:
            if time.monotonic()-start>seconds+35:error='process_timeout';break
            log=folder/'player.log'
            if log.exists() and any(s in log.read_text(encoding='utf8',errors='replace') for s in ['NullReferenceException:','ArgumentException:','InvalidOperationException:']):error='player_exception';break
            path=folder/'trace.jsonl'
            if normal_seed is not None and path.exists():
                rows=[]
                for l in path.read_text(encoding='utf8').splitlines():
                    try:rows.append(json.loads(l))
                    except json.JSONDecodeError:pass
                starts=[r for r in rows if r['evt']=='root'];releases=[r for r in rows if r['evt']=='release']
                if starts:
                    state=starts[0]['state'];seq=[state['current_fruit']['type'],state['next_fruit_type']]+[r['state']['next_fruit_type'] for r in releases]
                    if len(seq)>=8 and ','.join(map(str,seq[:8])) in {e['initial_sequence'] for e in reserved}:error='reserved_initial8_quarantine';break
            time.sleep(.5)
    except KeyboardInterrupt:error='interrupted'
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
    rows=[]
    if (folder/'trace.jsonl').exists():
        for l in (folder/'trace.jsonl').read_text(encoding='utf8').splitlines():
            try:rows.append(json.loads(l))
            except json.JSONDecodeError:error=error or 'incomplete_trace'
    result=summarize(rows);result.update(exit_code=proc.returncode,process_error=error,wall_seconds=time.monotonic()-start)
    if not result['end']:result['process_error']=error or 'missing_end'
    if proc.returncode or result['process_error'] or result['errors']:result['natural_go']=False
    write(folder/'result.json',result)
    write(folder/'done.json',dict(complete=True,natural_go=result['natural_go'],mode=mode))
    print(json.dumps(dict(event='trial_end',folder=str(folder),natural_go=result['natural_go'],score=result['end']['additional_score'] if result['end'] else None,drops=result['end']['accepted_drops'] if result['end'] else None,reason=result['end']['reason'] if result['end'] else error,wall_seconds=result['wall_seconds'])),flush=True)
    if proc.returncode or result['process_error'] or result['errors']:raise RuntimeError('Technical failure; keep data and stop without seed replacement')
    return result,rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=ROOT/'Unity/Builds/StagedAction_02/SuikaGameAI.exe');a=p.parse_args();out=a.output;exe=a.exe.resolve();plan=json.loads((out/'plan.json').read_text())
    if (out/'execution_start.json').exists():raise FileExistsError('Do not repeat an existing experiment')
    for f,h in plan['fixture_hashes'].items():
        if sha(f)!=h:raise RuntimeError('Frozen fixture changed')
    normal_seed=904731001;reserved=json.loads((ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    if normal_seed in {e['seed'] for e in reserved}:raise RuntimeError('Reserved seed')
    write(out/'execution_protocol.json',dict(normal_seed=normal_seed,normal_pair_total_limit=1200,normal_game_limit=600,normal_condition='only if >=1200 seconds remain; otherwise three-step normal smoke only',
          branch_pairs=[(r['id'],f) for f in plan['future_seeds'] for r in plan['roots']],reuse='recommended first forced to the same native recommendation, then legacy is identical to legacy policy; verify before reusing as staged baseline'))
    start=time.monotonic();deadline=start+plan['budget']['total_seconds'];branch_deadline=min(start+plan['budget']['branch_stage_seconds'],deadline-plan['budget']['reserved_for_staged_comparison_seconds'])
    write(out/'execution_start.json',dict(start_unix=time.time(),total_seconds=plan['budget']['total_seconds'],plan_sha256=sha(out/'plan.json'),assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')))
    selections={};references=[];branch_times={};stops=[]
    for r in plan['roots']:
        _,rows=trial(out/'surveys'/r['id'],exe,Path(r['fixture']),'survey',plan['future_seeds'][0],30,drops=1)
        decision=next(x for x in rows if x['evt']=='decision');selections[r['id']]=choose_alternative(decision)
    write(out/'selections.json',selections)
    trial(out/'staged_smoke',exe,Path(plan['roots'][0]['fixture']),'staged',plan['future_seeds'][0],45,drops=3)
    for fi,future in enumerate(plan['future_seeds']):
        for ri,r in enumerate(plan['roots']):
            key=r['id'];left=branch_deadline-time.monotonic();expected=2*max(branch_times.get(key,[120 if ri==0 else 300]))*1.1+10
            if left<expected:stops.append(dict(stage='branch',root=key,future=future,reason='reserve_new_method_budget',remaining=left,expected_pair=expected));continue
            roles=['recommended','alternative'] if (fi+ri)%2==0 else ['alternative','recommended']
            for role in roles:
                seconds=min(plan['budget']['per_game_seconds'],max(1,branch_deadline-time.monotonic()-35))
                x=selections[key][role+'_x'];folder=out/'branches'/f'{key}_f{future}'/role
                result,rows=trial(folder,exe,Path(r['fixture']),'baseline',future,seconds,first_x=x);branch_times.setdefault(key,[]).append(result['wall_seconds'])
                if role=='recommended' and result['natural_go']:
                    ds=[x for x in rows if x['evt']=='decision'];native=ds[0]['planning']['selected_x']
                    if native!=selections[key]['recommended_x']:raise RuntimeError('Reference differs from native legacy recommendation')
                    references.append(dict(root=key,future=future,fixture=r['fixture'],folder=str(folder),seconds=result['wall_seconds']))
                with (out/'progress.jsonl').open('a') as f:f.write(json.dumps(dict(stage='branch',root=key,future=future,role=role,natural_go=result['natural_go']))+'\n')
    write(out/'branch_complete.json',dict(references=references,stops=stops,elapsed_seconds=time.monotonic()-start))
    for ref in references:
        left=deadline-time.monotonic()
        if left<ref['seconds']*1.15+35:stops.append(dict(stage='staged',root=ref['root'],future=ref['future'],reason='budget',remaining=left));continue
        result,_=trial(out/'staged'/f"{ref['root']}_f{ref['future']}",exe,Path(ref['fixture']),'staged',ref['future'],min(420,left-35))
        with (out/'progress.jsonl').open('a') as f:f.write(json.dumps(dict(stage='staged',root=ref['root'],future=ref['future'],natural_go=result['natural_go']))+'\n')
    left=deadline-time.monotonic()
    if left>=1200:
        for mode in ['baseline','staged']:trial(out/'normal'/mode,exe,None,mode,normal_seed,min(600,deadline-time.monotonic()-35),normal_seed=normal_seed)
    elif left>=45:
        for mode in ['baseline','staged']:trial(out/'normal_smoke'/mode,exe,None,mode,normal_seed,20,drops=3,normal_seed=normal_seed)
        stops.append(dict(stage='normal',reason='insufficient_for_natural_pair_only_smoke',remaining_before=left))
    write(out/'execution_end.json',dict(elapsed_seconds=time.monotonic()-start,remaining_seconds=deadline-time.monotonic(),stops=stops))


if __name__=='__main__':main()
