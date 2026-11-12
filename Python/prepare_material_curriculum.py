"""Freeze a material-progress curriculum from approved Train games, without copying replay."""
from pathlib import Path
from double_watermelon_learning import load, sha, write, digest, ROOT, read_rows
from material_progress import GOALS, conditions
from prepare_candidate_fixtures import fixture


def prepare_progress(dataset, output, max_roots=24, source_limit=64):
    dataset,output=Path(dataset).resolve(),Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    if not 1<=max_roots<=100 or not max_roots<=source_limit<=256:raise ValueError('invalid root/source limits')
    base=load(dataset/'manifest.json');replay=Path(base.get('replay_file',dataset/'replay.jsonl'))
    if sha(replay)!=base['replay_sha256']:raise ValueError('Changed replay')
    candidates={};scanned=[]
    sources=[s for s in base['sources'] if s['split']=='train' and load(Path(s['path'])/'result.json').get('new_watermelons',0)>0]
    for src in sorted(sources,key=lambda s:s['seed'])[:source_limit]:
        source=Path(src['path'])/'trace.jsonl'
        if sha(source)!=src['trace_sha256']:raise ValueError('Changed approved source trace')
        rows,partial=read_rows(source)
        if partial:raise ValueError('Partial approved trace')
        ds=[r for r in rows if r['evt']=='decision' and not r['state']['game_over']]
        selected={};first=None
        for i,r in enumerate(ds):
            present=conditions(r['state'])
            if present['watermelon_one'] and first is None:first=i
            for k,v in present.items():
                if v:selected.setdefault(k,r)
        if first is not None and first>0:selected['pre_watermelon']=ds[first-1]
        if selected:candidates[src['seed']]=(src,selected)
        scanned.append(src['seed'])
    # Fixed coverage priority from material goals, not final score or continuation return.
    priority=list(reversed(GOALS[:-1]))+['pre_watermelon']
    buckets={k:[s for s in sorted(candidates) if k in candidates[s][1]] for k in priority}
    selected_roots=[];selected_prefixes=set()
    while len(selected_roots)<max_roots:
        before=len(selected_roots)
        for k in priority:
            seed=next((s for s in buckets[k] if s not in selected_roots and candidates[s][0]['initial8'] not in selected_prefixes),None)
            if seed is not None:
                selected_roots.append(seed);selected_prefixes.add(candidates[seed][0]['initial8'])
            if len(selected_roots)==max_roots:break
        if len(selected_roots)==before:break
    if not selected_roots:raise ValueError('No approved progress states')
    output.mkdir(parents=True);(output/'fixtures').mkdir();inventory=[]
    for seed in selected_roots:
        src,stages=candidates[seed];unique={}
        for stage,r in stages.items():
            key=digest(r['state'])
            if key in unique:unique[key]['stages'].append(stage);continue
            s=r['state'];geo=s['geometry']
            row=dict(state=s,action_id=r['command']['start_tick'],info=dict(planning=dict(
                drop_range=dict(left_wall_inner=geo[0],right_wall_inner=geo[1]),floor_y=geo[2],game_over_y=geo[3])))
            f=fixture(row,'post_state',allow_cold=True)
            f.update(source_seed=seed,source_initial8=src['initial8'],source_split='train',source_tick=r['tick'],
                     source_trace=src['path'],source_trace_sha256=src['trace_sha256'],native_checkpoint_exact=False)
            path=output/'fixtures'/f'seed_{seed}_{key[:12]}.json';write(path,f)
            item=dict(path=str(path),sha256=sha(path),snapshot_id=key,source_seed=seed,initial8=src['initial8'],
                      split='train',stage=stage,stages=[stage],initial_conditions=conditions(s),
                      initial_watermelons=sum(x['type']==10 for x in s['fruits']))
            unique[key]=item;inventory.append(item)
    manifest=dict(base,version='watermelon-material-curriculum-v2',replay_file=str(replay),fixtures=inventory,
        base_manifest=str(dataset/'manifest.json'),base_manifest_sha256=sha(dataset/'manifest.json'),
        recommended_exe=str(ROOT/'Unity/Builds/MaterialCurriculum_01/SuikaGameAI.exe'),
        material_progress=True,curriculum_policy='progress-balanced',
        selection=dict(scanned_source_seeds=scanned,selected_source_seeds=selected_roots,max_roots=max_roots,
                       rule='Train only; fixed material coverage priority; first observed matching state, no score/position ranking'),
        phase_groups={k:len({f['source_seed'] for f in inventory if k in f['stages']}) for k in ('pre_watermelon',)+GOALS[:-1]},
        progress_bonus_points_default=0,
        missing_phases=[k for k in GOALS[:-1] if not any(k in f['stages'] for f in inventory)])
    write(output/'manifest.json',manifest)
    return dict(output=str(output),independent_source_groups=len(selected_roots),unique_fixtures=len(inventory),
                phase_groups=manifest['phase_groups'],missing_phases=manifest['missing_phases'],
                replay_shared_read_only=True,independent_test=False)
