"""STEP8-E paired heuristic/MCTS experiment. Existing logs/models are never overwritten."""
import argparse,concurrent.futures,csv,hashlib,json,math,random,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.parallel_play import run_parallel,validate_run,worker_specs
from suika_ai.collection_metadata import canonical
from compare_value_ai import validate_selected_action,metrics

RULES_VERSION='step8e-all-fruit-go-v2'
MODES=('heuristic','mcts')

def settings(mode):
    return dict(ai_mode=mode,candidate_count=5,post_drop_steps=25,mcts_iterations=32,mcts_max_depth=3,mcts_seed=8191,score_scale=55.,weight_height=0.,weight_danger=0.,weight_roughness=.2)

def paired_ci(differences):
    # Resample paired games/seeds, never states or individual actions.
    if len(differences)<2:return None
    rng=random.Random(20261022)
    means=sorted(statistics.mean(rng.choices(differences,k=len(differences))) for _ in range(10000))
    return [means[249],means[9749]]

def public_series(rows):
    start=next(r for r in rows if r['event']=='episode_start')['state']
    series=[start['current_fruit']['type'],start['next_fruit_type']]
    for row in rows:
        if row.get('event')!='transition':continue
        p=row['info']['planning']
        if p['held_fruit_type']!=series[-2] or p['next_fruit_type']!=series[-1]:
            raise ValueError('Held/NEXT sequence changed without a successful drop')
        if row['info']['drop_success']:
            if row['state']['current_fruit']['type']!=series[-1]:raise ValueError('Visible NEXT did not become held fruit')
            series.append(row['state']['next_fruit_type'])
    return series

def episode(run_path,manifest,w,expected_settings=None,flexible_mcts=False):
    mode=manifest['settings']['ai_mode'];errors=[]
    def fail(message):errors.append(message)
    path=run_path/(w['game_id']+'.jsonl')
    rows=[]
    try:
        for line in path.read_text(encoding='utf-8').splitlines():rows.append(json.loads(line))
    except (OSError,json.JSONDecodeError) as e:fail('incomplete_or_invalid_log:'+str(e))
    transitions=[r for r in rows if r.get('event')=='transition']
    ends=[r for r in rows if r.get('event')=='episode_end'];starts=[r for r in rows if r.get('event')=='episode_start']
    end=ends[-1] if ends else {};final=end.get('state',{})
    if len(starts)!=1 or len(ends)!=1:fail('expected_one_complete_episode')
    if starts and (starts[0].get('seed')!=w['seed'] or starts[0]['state'].get('worker_seed')!=w['seed'] or starts[0]['state'].get('has_worker_seed') is not True):fail('requested_vs_actual_seed_mismatch')
    if not (end.get('game_over') is True and end.get('truncated') is False and end.get('reason')=='game_over'):fail('not_natural_go:'+str(end.get('reason','missing_end')))
    if not end.get('conserved'):fail('reward_not_conserved')
    for r in rows:
        if r.get('event')=='worker_error':fail('worker_error:'+r.get('error','unknown'))
    environment={};environment_id=None
    try:
        metadata=json.loads((run_path/'metadata'/(w['game_id']+'.json')).read_text(encoding='utf-8'))
        environment=metadata['environment'];environment_id=metadata['environment_id']
        if hashlib.sha256(canonical(environment)).hexdigest()!=environment_id:fail('environment_hash_mismatch')
        if environment.get('rules_version')!=RULES_VERSION:fail('wrong_or_missing_rules_version')
        if abs(environment.get('game_over_screen_ratio',-1)-.83)>1e-5:fail('wrong_GO_ratio')
        assets=environment.get('fruit_assets',[])
        if len(assets)!=11 or any(f.get('game_object_tag')!='Fruit' for f in assets):fail('prefab_GO_tags_not_verified')
        if any(r.get('environment_id',environment_id)!=environment_id for r in rows if r.get('event') in ('transition','episode_start')):fail('mixed_environment_ids')
    except (OSError,KeyError,ValueError) as e:fail('missing_environment:'+str(e))
    expected_settings=settings(mode) if expected_settings is None else expected_settings
    for key,value in expected_settings.items():
        if manifest['settings'].get(key)!=value:fail('wrong_setting:'+key)
    if not manifest.get('headless'):fail('comparison_requires_headless_both_modes')
    if not final.get('episode_statistics_known'):fail('missing_actual_merge_statistics')
    planning=[];confusion=dict(tp=0,tn=0,false_negative=0,false_positive=0);pre_drop_go=0;selected_errors=[];sequence=[]
    for row in transitions:
        try:
            info=row['info'];d=info['planning'];c=d['candidates'][d['selected_index']]
            validate_selected_action(c,row) # Existing no-drop/default-zero fix retained.
            if (not flexible_mcts and (len(d['candidates'])!=expected_settings['candidate_count'] or d['evaluated_count']!=expected_settings['candidate_count'])):raise ValueError('Expected candidates not covered')
            if not d['same_source_verified']:raise ValueError('Planner mutated source or prefix mismatch')
            if d['ai_mode']!=mode:raise ValueError('Wrong AI mode')
            if mode=='mcts':
                m=d['mcts']
                if (not flexible_mcts and m['completed_iterations']!=expected_settings['mcts_iterations']) or m['max_depth']!=expected_settings['mcts_max_depth'] or not m['prefixes_match'] or not m['source_unchanged']:raise ValueError('MCTS budget/depth/source mismatch')
                if sum(x['visits'] for x in m['nodes'][0]['actions'])!=(m['completed_iterations'] if flexible_mcts else expected_settings['mcts_iterations']):raise ValueError('MCTS visit conservation failed')
            planning.append(d['elapsed_ms'])
            pred=c['predicted_game_over'];actual=row['state']['game_over']
            confusion['tp' if pred and actual else 'false_positive' if pred else 'false_negative' if actual else 'tn']+=1
            pre_drop_go+=int(actual and not info['drop_success'])
        except (KeyError,ValueError,IndexError,TypeError) as e:
            selected_errors.append(dict(turn=row.get('turn'),error=str(e)));fail('invalid_selected_action:'+str(row.get('turn')))
    try:sequence=public_series(rows)
    except (KeyError,ValueError,StopIteration) as e:fail('fruit_series:'+str(e))
    stats=[r['state'] for r in transitions]+([final] if final else [])
    previous=0
    for state in stats:
        count=state.get('episode_merge_count')
        if state.get('episode_statistics_known') is not True or type(count) is not int or count<previous:fail('invalid_or_nonmonotonic_actual_merge_count');break
        previous=count
    natural=bool(end.get('game_over') and not end.get('truncated') and end.get('reason')=='game_over')
    return dict(mode=mode,seed=w['seed'],game_id=w['game_id'],log=str(path),natural_go=natural,
        termination=end.get('reason','incomplete_or_error'),worker_errors=[r.get('error') for r in rows if r.get('event')=='worker_error'],
        final_score=end.get('final_score') if natural else None,last_observed_score=end.get('last_observed_score'),operations=len(transitions),
        successful_drops=sum(bool(r['info'].get('drop_success')) for r in transitions),merges=final.get('episode_merge_count') if final.get('episode_statistics_known') else None,
        maximum_fruit_type=final.get('episode_max_fruit_type') if final.get('episode_statistics_known') else None,
        game_wall_seconds=end.get('wall_seconds'),planning_ms=metrics(planning),planning_ms_per_action=planning,
        go_confusion=confusion,pre_drop_actual_go=pre_drop_go,between_action_actual_go=sum(r.get('event')=='terminal_observation' for r in rows),
        public_series=sequence,environment_id=environment_id,rules_version=environment.get('rules_version'),exe_sha256=manifest.get('exe_sha256'),
        errors=errors,selected_action_errors=selected_errors)

def summarize(root,report_dir=None):
    root=Path(root).resolve();episodes={};audit=[]
    for path in sorted(root.rglob('run.json')):
        manifest=json.loads(path.read_text(encoding='utf-8'));mode=manifest['settings']['ai_mode']
        if mode not in MODES:raise ValueError('Unexpected AI mode in comparison')
        integrity_error=None
        try:audit.append(dict(run=str(path.parent),checks=validate_run(path.parent)))
        except (ValueError,KeyError,OSError,json.JSONDecodeError) as e:integrity_error=str(e);audit.append(dict(run=str(path.parent),error=integrity_error))
        for worker in manifest['workers']:
            ep=episode(path.parent,manifest,worker)
            if integrity_error:ep['errors'].append('run_integrity:'+integrity_error)
            modes=episodes.setdefault(worker['seed'],{})
            if mode in modes:raise ValueError('Duplicate seed/mode: episodes are not independent')
            modes[mode]=ep
    # Scheduled missing games are retained as excluded pairs, never silently dropped.
    schedule_path=root/'comparison_plan.json'
    schedule=json.loads(schedule_path.read_text()) if schedule_path.exists() else {}
    for seed in schedule.get('seeds',[]):episodes.setdefault(seed,{})
    pairs=[]
    for seed,modes in sorted(episodes.items()):
        reasons=[]
        for mode in MODES:
            if mode not in modes:reasons.append(mode+':missing_game')
            else:reasons.extend(mode+':'+e for e in modes[mode]['errors'])
        if all(m in modes for m in MODES):
            h,m=modes['heuristic'],modes['mcts'];n=min(len(h['public_series']),len(m['public_series']))
            equal=n>=2 and h['public_series'][:n]==m['public_series'][:n]
            if not equal:reasons.append('public_fruit_sequence_mismatch')
            if not h['environment_id'] or h['environment_id']!=m['environment_id']:reasons.append('environment_mismatch')
            if not h['exe_sha256'] or h['exe_sha256']!=m['exe_sha256']:reasons.append('binary_mismatch')
        else:n=0;equal=False
        eligible=not reasons
        pairs.append(dict(seed=seed,eligible=eligible,exclusion_reasons=reasons,series_match=equal,common_visible_prefix_length=n,
            difference=modes['mcts']['final_score']-modes['heuristic']['final_score'] if eligible else None,**modes))
    valid=[p for p in pairs if p['eligible']];differences=[p['difference'] for p in valid]
    modes={}
    for mode in MODES:
        values=[p[mode] for p in valid]
        modes[mode]=dict(scores=metrics([v['final_score'] for v in values]),operations=metrics([v['operations'] for v in values]),
            merges=metrics([v['merges'] for v in values]),maximum_fruit_type=metrics([v['maximum_fruit_type'] for v in values]),
            game_wall_seconds=metrics([v['game_wall_seconds'] for v in values if v['game_wall_seconds'] is not None]),
            game_mean_planning_ms=metrics([v['planning_ms']['mean'] for v in values if v['planning_ms']['n']]),
            pooled_action_planning_ms_descriptive=metrics([t for v in values for t in v['planning_ms_per_action']]),
            go_confusion={k:sum(v['go_confusion'][k] for v in values) for k in ('tp','tn','false_negative','false_positive')},
            between_action_go=sum(v['between_action_actual_go'] for v in values))
    result=dict(status="completed" if pairs and len(valid)==len(pairs) else "incomplete_or_invalid",rules_version=RULES_VERSION,eligible_pairs=len(valid),excluded_pairs=len(pairs)-len(valid),pairs=pairs,audit=audit,modes=modes,
        wins=dict(heuristic=sum(d<0 for d in differences),mcts=sum(d>0 for d in differences),tie=sum(d==0 for d in differences)),
        mcts_minus_heuristic=metrics(differences),paired_mean_difference_95ci=paired_ci(differences),
        statistics='Paired-seed bootstrap percentile 95% (10000 resamples). Paired games are the independent units; actions/states are not resampled. CI unavailable for n<2; n=10 exploratory.',
        go_scope='Selected immediate 25-post-drop-tick prediction vs actual returned state. Between-action GO is separate; deeper sampled rollout GO is not an actual counterfactual.',
        experiment_purpose=schedule.get('purpose','comparison'))
    destination=Path(report_dir) if report_dir else root
    if report_dir:destination.mkdir(parents=True,exist_ok=False)
    if any((destination/f).exists() for f in ('comparison.json','paired_scores.csv')):raise FileExistsError('Refuse to replace prior analysis; use --report-dir NEW')
    with (destination/'comparison.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
    with (destination/'paired_scores.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['seed','heuristic_score','mcts_score','mcts_minus_heuristic','eligible','exclusion_reasons'])
        for p in pairs:writer.writerow([p['seed'],p.get('heuristic',{}).get('final_score'),p.get('mcts',{}).get('final_score'),p['difference'],p['eligible'],';'.join(p['exclusion_reasons'])])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'));p.add_argument('--pairs',type=int,default=10);p.add_argument('--games',type=int,default=4);p.add_argument('--seed',type=int,default=748000);p.add_argument('--base-port',type=int,default=33000);p.add_argument('--max-steps',type=int,default=3000);p.add_argument('--analyze-only',action='store_true');p.add_argument('--report-dir',type=Path);p.add_argument('--smoke-seconds',type=float,help='One paired bounded smoke only; modes run concurrently, never interpreted as strength evidence');a=p.parse_args()
    if a.analyze_only:
        result=summarize(a.output,a.report_dir)
    else:
        if a.pairs<1 or a.max_steps<1:p.error('Positive pairs and max-steps required')
        worker_specs(a.games,a.base_port,a.seed);worker_specs(1,a.base_port,a.seed+a.pairs-1)
        if a.smoke_seconds is not None and (a.pairs!=1 or a.games!=1 or not 0<a.smoke_seconds<=180):p.error('Smoke must be one pair, one game per mode, 0..180 seconds')
        a.output.mkdir(parents=True,exist_ok=False)
        schedule=dict(rules_version=RULES_VERSION,seeds=list(range(a.seed,a.seed+a.pairs)),settings={m:settings(m) for m in MODES},
            purpose='pipeline_smoke_not_strength' if a.smoke_seconds else 'paired_strength_comparison',mode_order='concurrent only for smoke; alternate batch order otherwise',
            timing='Same live movement/cooldown/post25 API; game physics not accelerated. Wall-clock planning cost may differ.',smoke_seconds=a.smoke_seconds)
        with (a.output/'comparison_plan.json').open('x') as f:json.dump(schedule,f,indent=2)
        def run(mode,start,count,port):
            return run_parallel(a.exe,a.output/f'batch_{start:04d}_{mode}',count,1,a.max_steps,port,a.seed+start,True,settings(mode),require_metadata=True,expected_go_ratio=.83,max_episode_seconds=a.smoke_seconds,expected_rules_version=RULES_VERSION)
        if a.smoke_seconds:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(run,m,0,1,a.base_port+2*i) for i,m in enumerate(MODES)]
                for f in futures:f.result()
        else:
            halted=False
            for start in range(0,a.pairs,a.games):
                order=MODES if (start//a.games)%2==0 else MODES[::-1]
                for mode in order:
                    run_result=run(mode,start,min(a.games,a.pairs-start),a.base_port)
                    if any(w['status'] in ('error','stopped') for w in run_result['workers']):halted=True;break
                if halted:break
        result=summarize(a.output,a.report_dir)
    print(json.dumps({k:result[k] for k in ('status','eligible_pairs','excluded_pairs','modes','wins','mcts_minus_heuristic','paired_mean_difference_95ci')},ensure_ascii=False),flush=True)
    if result['excluded_pairs'] or not result['eligible_pairs']:raise SystemExit(2)
if __name__=='__main__':main()
