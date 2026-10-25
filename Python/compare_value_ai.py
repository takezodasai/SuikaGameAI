"""Paired fresh-seed comparison; no training, no policy retuning, no log overwrite."""
import argparse,collections,json,statistics,sys,random,time,math,csv
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.parallel_play import run_parallel,validate_run

def metrics(values):
    if not values:return dict(n=0)
    return dict(n=len(values),mean=statistics.mean(values),median=statistics.median(values),minimum=min(values),maximum=max(values))

# World-space tolerance already used by live movement-range checks. Do not widen it
# to accommodate an unavailable prediction coordinate (default 0 before a drop).
DROP_X_TOLERANCE=1e-5

def validate_selected_action(c,row):
    info=row['info'];d=info['planning'];errors=[]
    def close(a,b,label):
        if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a) or not math.isfinite(b) or abs(a-b)>DROP_X_TOLERANCE:
            errors.append(label)
    if not c['success']:errors.append('Invalid selected candidate')
    if c.get('index')!=d['selected_index']:errors.append('Selected candidate index mismatch')
    if c['predicted_game_over'] and not d['all_predicted_terminal']:errors.append('Excluded GO candidate selected')
    if d['all_predicted_terminal'] and not all(x['success'] and x['predicted_game_over'] for x in d['candidates']):errors.append('Invalid all-GO fallback')
    close(c['x'],d['selected_x'],'Candidate/selected X mismatch')
    close(d['selected_x'],row['selected_x'],'Logged selected X mismatch')
    close(d['selected_x'],info['requested_x'],'Selected/requested X mismatch')
    if not 0<=d['selected_x']<=1:errors.append('Normalized X outside range')
    close(c['target_x'],info['target_x'],'Movement target X mismatch')
    predicted_available=c['drop_success'] is True
    actual_available=info.get('drop_success') is True
    result=dict(predicted_drop_success=predicted_available,actual_drop_success=actual_available,
        predicted_applied_x=c['applied_x'] if predicted_available else None,
        actual_applied_x=info['applied_x'] if actual_available else None,
        raw_prediction_applied_x=c['applied_x'],selected_x=d['selected_x'],target_x=info['target_x'],
        raw_delta=info['applied_x']-c['applied_x'] if actual_available else None,
        classification='both_dropped' if predicted_available and actual_available else 'prediction_no_drop' if actual_available else 'actual_no_drop')
    if not predicted_available and not c['predicted_game_over']:errors.append('Prediction has no drop without GO')
    if not actual_available and not row['state']['game_over']:errors.append('Actual action has no drop without GO')
    if actual_available:
        applied=info['applied_x'];lo=info['min_x'];hi=info['max_x']
        close(applied,info['target_x'],'Actual drop/target X mismatch')
        close(applied,lo+(hi-lo)*info['requested_x'],'Actual drop/final range X mismatch')
        if not lo-DROP_X_TOLERANCE<=applied<=hi+DROP_X_TOLERANCE:errors.append('Actual drop outside range')
        if predicted_available:close(c['applied_x'],applied,'Selected drop X mismatch')
    if errors:raise ValueError('; '.join(errors))
    return result

def summarize(root,report_dir=None):
    root=Path(root);episodes={};diagnostics=[];action_errors=[]
    for manifest in root.rglob('run.json'):
        run=json.loads(manifest.read_text());mode=run['settings']['ai_mode']
        checks=validate_run(manifest.parent)
        for w in run['workers']:
            path=manifest.parent/(w['game_id']+'.jsonl')
            rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            transitions=[r for r in rows if r.get('event')=='transition']
            end=next((r for r in reversed(rows) if r.get('event')=='episode_end'),None)
            seq=[r['info']['planning']['held_fruit_type'] for r in transitions]
            planned=[r['info']['planning'] for r in transitions]
            selected=[d['candidates'][d['selected_index']] for d in planned]
            selection_errors=[];coordinate_counts=collections.Counter();max_target_error=0.;max_prediction_error=0.
            for c,r in zip(selected,transitions):
                identity=dict(mode=mode,seed=w['seed'],game_id=w['game_id'],turn=r['turn'],action_id=r['action_id'],episode_id=r['episode_id'],log=str(path))
                try:
                    check=validate_selected_action(c,r);coordinate_counts[check['classification']]+=1
                    if check['actual_drop_success']:max_target_error=max(max_target_error,abs(r['info']['applied_x']-r['info']['target_x']))
                    if check['actual_drop_success'] and check['predicted_drop_success']:max_prediction_error=max(max_prediction_error,abs(r['info']['applied_x']-c['applied_x']))
                    if check['actual_drop_success'] and abs(check['raw_delta'])>DROP_X_TOLERANCE:
                        diagnostics.append(dict(**identity,**check,predicted_go=c['predicted_game_over'],actual_go=r['state']['game_over'],all_go=r['info']['planning']['all_predicted_terminal'],pred_drop_tick=c['drop_tick'],pred_go_tick=c['game_over_tick']))
                except ValueError as error:
                    failure=dict(**identity,error=str(error));selection_errors.append(failure);action_errors.append(failure)
            episode=dict(seed=w['seed'],mode=mode,natural_go=bool(end and end['game_over'] and not end['truncated']),
                score=end['final_score'] if end and end['game_over'] else None,steps=len(transitions),
                full_candidates=all(len(d['candidates'])==5 and d['evaluated_count']==5 for d in planned),
                selection_errors=selection_errors,coordinate_checks=dict(coordinate_counts),max_target_x_error=max_target_error,max_prediction_x_error=max_prediction_error,
                model_sha256=planned[0].get('model_sha256') if planned else None,
                inference_ms=[c.get('inference_ms',0) for d in planned for c in d['candidates'] if c.get('value_evaluated')],
                dropped_types=seq,planning_ms=[d['elapsed_ms'] for d in planned],
                prediction_go_mismatches=sum(c['predicted_game_over']!=r['state']['game_over'] for c,r in zip(selected,transitions)),
                missed_go=sum(not c['predicted_game_over'] and r['state']['game_over'] for c,r in zip(selected,transitions)),
                between_action_go=sum(r.get('event')=='terminal_observation' for r in rows),
                all_go_fallbacks=sum(d['all_predicted_terminal'] for d in planned),
                source_verified=all(d['same_source_verified'] for d in planned),conserved=bool(end and end['conserved']),
                worker_errors=[r['error'] for r in rows if r.get('event')=='worker_error'],
                log=str(path),audit=checks)
            if mode=='value' and episode['natural_go']:
                late=[]
                for c,r in list(zip(selected,transitions))[-5:]:
                    # Diagnostic only: predicted board and actual board differ due to physics error.
                    actual_remaining=end['final_score']-r['state']['score']
                    late.append(dict(turn=r['turn'],future_value=c['future_value'],actual_remaining=actual_remaining,
                        overestimate=c['future_value']-actual_remaining,predicted_go=c['predicted_game_over'],actual_go=r['state']['game_over']))
                episode['last5_value_diagnostic']=late
            if mode in episodes.setdefault(w['seed'],{}):raise ValueError('Duplicate seed/mode episode')
            episodes[w['seed']][mode]=episode
    pairs=[]
    for seed,modes in sorted(episodes.items()):
        if set(modes)!={'heuristic','value'}:continue
        h,v=modes['heuristic'],modes['value'];n=min(len(h['dropped_types']),len(v['dropped_types']))
        equal=h['dropped_types'][:n]==v['dropped_types'][:n]
        complete=h['natural_go'] and v['natural_go'] and equal and h['conserved'] and v['conserved'] and h['source_verified'] and v['source_verified'] and not h['worker_errors'] and not v['worker_errors'] and not h['selection_errors'] and not v['selection_errors']
        reasons=[]
        for mode,ep in modes.items():
            for field in ('natural_go','conserved','source_verified'):
                if not ep[field]:reasons.append(mode+':'+field)
            if ep['worker_errors']:reasons.append(mode+':worker_error')
            if ep['selection_errors']:reasons.append(mode+':selection_mismatch')
        if not equal:reasons.append('fruit_series_mismatch')
        pairs.append(dict(seed=seed,exclusion_reasons=reasons,series_match=equal,common_prefix_length=n,eligible=complete,
            difference=v['score']-h['score'] if complete else None,heuristic=h,value=v))
    differences=[p['difference'] for p in pairs if p['eligible']]
    ci=None
    if len(differences)>=2:
        rng=random.Random(2026);boot=sorted(statistics.mean(rng.choices(differences,k=len(differences))) for _ in range(3000));ci=[boot[75],boot[2924]]
    result=dict(pairs=pairs,coordinate_diagnostics=diagnostics,action_errors=action_errors,
        wins=dict(heuristic=sum(x<0 for x in differences),value=sum(x>0 for x in differences),tie=sum(x==0 for x in differences)),
        eligible_pairs=len(differences),excluded_pairs=sum(not p['eligible'] for p in pairs),
        paired_difference=metrics(differences),paired_mean_difference_95ci=ci,
        independent_unit='one paired seed; incomplete/mismatching series excluded, not zero-filled',
        modes={m:dict(scores=metrics([p[m]['score'] for p in pairs if p['eligible']]),
            steps=metrics([p[m]['steps'] for p in pairs if p['eligible']]),
            planning_ms=metrics([t for p in pairs if p['eligible'] for t in p[m]['planning_ms']])) for m in ('heuristic','value')})
    destination=root if report_dir is None else Path(report_dir)
    if report_dir is not None:destination.mkdir(parents=True,exist_ok=False)
    # Exclusive creation protects previous experiments and previous analysis reports.
    with (destination/'comparison.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    with (destination/'paired_scores.csv').open('x',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['seed','heuristic_score','value_score','value_minus_heuristic','eligible','exclusion_reasons'])
        for p in pairs:writer.writerow([p['seed'],p['heuristic']['score'],p['value']['score'],p['difference'],p['eligible'],';'.join(p['exclusion_reasons'])])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'))
    p.add_argument('--pairs',type=int,default=30);p.add_argument('--games',type=int,default=4);p.add_argument('--seed',type=int,default=742500)
    p.add_argument('--max-steps',type=int,default=1000);p.add_argument('--base-port',type=int,default=22000)
    p.add_argument('--value-model',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report-dir',type=Path,help='New separate directory for analysis; existing reports are never overwritten')
    p.add_argument('--analyze-only',action='store_true');p.add_argument('--exclude-dataset',type=Path,action='append',default=[Path(__file__).resolve().parent/'outputs/value_data_100_01',Path(__file__).resolve().parent/'outputs/value_data_smoke_01'])
    a=p.parse_args()
    if a.analyze_only:
        result=summarize(a.output,a.report_dir);print(json.dumps(dict(modes=result['modes'],wins=result['wins'],eligible_pairs=result['eligible_pairs'],paired_difference=result['paired_difference'],paired_mean_difference_95ci=result['paired_mean_difference_95ci'])));return
    if a.pairs<1 or not 1<=a.games<=4:p.error('positive pairs, games1..4 required')
    # Refuse an unverifiable comparison rather than silently skipping the current dataset.
    if not (a.exclude_dataset[0]/'samples.jsonl').is_file():p.error('Current training dataset missing; cannot verify unseen seeds')
    used={12345,12346,12347,12348}
    for dataset in a.exclude_dataset:
        samples=dataset/'samples.jsonl'
        if not samples.exists():continue
        for line in samples.read_text(encoding='utf-8').splitlines():used.add(json.loads(line)['seed'])
    if set(range(a.seed,a.seed+a.pairs))&used:p.error('Comparison seeds overlap training/validation/test seeds')
    a.output.mkdir(parents=True,exist_ok=False)
    schedule=dict(pairs=a.pairs,games=a.games,seeds=list(range(a.seed,a.seed+a.pairs)),excluded_seeds=sorted(used),post_drop_steps=25,candidates=5,mode_order='alternate each batch',timing='normal game clock; headless both; no speed changes')
    (a.output/'comparison_plan.json').write_text(json.dumps(schedule,indent=2),encoding='utf-8')
    for start in range(0,a.pairs,a.games):
        modes=('heuristic','value') if (start//a.games)%2==0 else ('value','heuristic')
        for mode in modes:
            settings=dict(candidate_count=5,post_drop_steps=25,ai_mode=mode,value_model_path=str(a.value_model.resolve()) if a.value_model else '')
            result=run_parallel(a.exe,a.output/f'batch_{start:04d}_{mode}',min(a.games,a.pairs-start),1,a.max_steps,a.base_port,a.seed+start,True,settings,require_metadata=True,expected_go_ratio=.83)
            if any(w['status']=='error' for w in result['workers']):
                summarize(a.output);raise RuntimeError('Worker failed; logs preserved; comparison stopped')
    result=summarize(a.output);print(json.dumps(dict(modes=result['modes'],paired_difference=result['paired_difference'],paired_mean_difference_95ci=result['paired_mean_difference_95ci'])))
if __name__=='__main__':main()
