"""STEP8-S: sequential MCTS iteration-budget experiments, immutable per-game results and resume."""
import argparse,contextlib,csv,hashlib,itertools,json,math,os,statistics,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from compare_mcts_ai import episode,paired_ci,metrics,RULES_VERSION
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel,validate_run,worker_specs
from analyze_two_step_probe import trace_search

BUDGETS=(32,64,128,256)
def settings(count,search_seed=8191):
    if count not in BUDGETS:raise ValueError('Supported budgets: 32,64,128,256')
    return validate_planning_settings(dict(ai_mode='mcts',candidate_policy='grid',candidate_count=5,mcts_iterations=count,mcts_max_depth=4,mcts_seed=search_seed,execution_mode='sync',post_drop_steps=25,rollout_policy='random',tree_policy='chance',expansion_policy='legacy',action_order_policy='index',pair_coverage_iterations=0,mcts_common_chance=False))

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,obj):
    import uuid
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    if path.exists():raise FileExistsError(path)
    os.rename(temporary,path) # Same-volume atomic publication; Windows refuses an existing target.
def assembly_sha(exe):
    p=Path(exe).with_name(Path(exe).stem+'_Data')/'Managed/Assembly-CSharp.dll'
    return sha(p) if p.exists() else None
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def percentile(xs,q=.95):
    if not xs:return None
    xs=sorted(xs);p=(len(xs)-1)*q;i=int(p);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(p-i)
@contextlib.contextmanager
def experiment_lock(root):
    f=(Path(root)/'experiment.lock').open('a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:f.close();raise RuntimeError('Experiment is already running')
    try:yield
    finally:f.close() # OS releases the lock, also after a process crash.

def audit_game(run,count,search_seed):
    manifest=read(run/'run.json');expected=settings(count,search_seed)
    if len(manifest['workers'])!=1:raise ValueError('Expected exactly one independent Player')
    ep=episode(run,manifest,manifest['workers'][0],expected_settings=expected)
    audit=validate_run(run)
    rows=[json.loads(l) for l in (run/'game_00.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    physical=0;planning=[];maxima=[];go_search=0
    for r in rows:
        if r.get('event')!='transition':continue
        d=r['info']['planning'];m=d['mcts']
        for k,v in expected.items():
            actual=d['settings'].get(k)
            ok=math.isclose(v,actual,rel_tol=1e-6,abs_tol=1e-7) if type(v) in (int,float) and type(actual) in (int,float) else actual==v
            if not ok:raise ValueError('Executed setting mismatch: '+k)
        if m['completed_iterations']!=count or m['requested_iterations']!=count or len(m['iterations'])!=count:raise ValueError('Actual search budget mismatch')
        if m['max_depth']!=4 or sum(a['visits'] for a in m['nodes'][0]['actions'])!=count:raise ValueError('Depth or visit conservation mismatch')
        if sum(i['simulated_ticks'] for i in m['iterations'])!=m['total_physics_ticks']:raise ValueError('Physical work mismatch')
        if any(i['depth']>4 or i.get('coverage_requested',False) for i in m['iterations']):raise ValueError('Unexpected allocation/depth')
        if m['common_chance'] or m['tree_policy']!='chance' or m['rollout_policy']!='random' or m['expansion_policy']!='legacy':raise ValueError('Baseline changed')
        trace_search(dict(decision=d,report=m))
        physical+=m['total_physics_ticks'];planning.append(d['elapsed_ms']);go_search+=sum(i['game_over'] for i in m['iterations'])
    ep.update(iterations=count,depth=4,search_seed=search_seed,planning_p95_ms=percentile(planning),planning_total_seconds=sum(planning)/1000,physical_ticks=physical,search_go_samples=go_search,audit=audit)
    return ep

def completed(root,job):
    p=root/job['key']/'result.json'
    if not p.exists():return None
    r=read(p)
    if r['job']!=job:raise ValueError('Saved job differs from immutable plan')
    for name,digest in r['hashes'].items():
        if sha(root/name)!=digest:raise ValueError('Saved completed data changed: '+name)
    return r['episode']

def pair_result(a,b):
    reasons=[]
    for label,r in [('a',a),('b',b)]:
        if r is None:reasons.append(label+':missing')
        else:
            reasons.extend(label+':'+e for e in r['errors'])
            if not r['natural_go']:reasons.append(label+':not_natural_go')
    if a and b:
        n=min(len(a['public_series']),len(b['public_series']))
        if n<2 or a['public_series'][:n]!=b['public_series'][:n]:reasons.append('fruit_sequence_mismatch')
        if not a['environment_id'] or a['environment_id']!=b['environment_id']:reasons.append('environment_mismatch')
        if not a['exe_sha256'] or a['exe_sha256']!=b['exe_sha256']:reasons.append('binary_mismatch')
    return dict(eligible=not reasons,reasons=reasons,difference=b['final_score']-a['final_score'] if not reasons else None)

def summarize(root,plan):
    episodes=[];by={};pending=[]
    for j in plan['jobs']:
        r=completed(root,j)
        if r is None:
            attempts=sorted((root/j['key']).glob('attempt_*'))
            pending.append(dict(**j,status='interrupted_or_failed' if attempts else 'not_started',attempts=[str(p.relative_to(root)) for p in attempts]));continue
        episodes.append(r);by[j['seed'],j['iterations']]=r
    modes={}
    for n in plan['budgets']:
        rs=[r for r in episodes if r['iterations']==n];valid=[r for r in rs if r['natural_go'] and not r['errors']]
        modes[str(n)]=dict(completed=len(rs),natural_go=sum(r['natural_go'] for r in rs),valid_natural_go=len(valid),truncated=sum(not r['natural_go'] for r in rs),scores=metrics([r['final_score'] for r in valid]),game_mean_planning_ms=metrics([r['planning_ms']['mean'] for r in valid if r['planning_ms']['n']]),game_total_planning_seconds=metrics([r['planning_total_seconds'] for r in valid]),game_wall_seconds=metrics([r['game_wall_seconds'] for r in valid if r['game_wall_seconds'] is not None]))
    comparisons=[]
    for n,m in itertools.combinations(plan['budgets'],2):
        pairs=[]
        for seed in plan['seeds']:
            a,b=by.get((seed,n)),by.get((seed,m));p=pair_result(a,b);p.update(seed=seed,a_score=a['final_score'] if a else None,b_score=b['final_score'] if b else None)
            if p['eligible']:
                p['planning_time_ratio']=b['planning_total_seconds']/a['planning_total_seconds'] if a['planning_total_seconds'] else None
                p['mean_decision_time_ratio']=b['planning_ms']['mean']/a['planning_ms']['mean'] if a['planning_ms']['mean'] else None
                p['wall_time_ratio']=b['game_wall_seconds']/a['game_wall_seconds'] if a['game_wall_seconds'] else None
            pairs.append(p)
        valid=[p for p in pairs if p['eligible']];diff=[p['difference'] for p in valid]
        comparisons.append(dict(a=n,b=m,valid_pairs=len(valid),excluded_pairs=len(pairs)-len(valid),pairs=pairs,wins_a=sum(d<0 for d in diff),wins_b=sum(d>0 for d in diff),ties=sum(d==0 for d in diff),difference=metrics(diff),mean_difference_95ci=paired_ci(diff),mean_decision_time_ratio=metrics([p['mean_decision_time_ratio'] for p in valid if p['mean_decision_time_ratio'] is not None]),total_planning_time_ratio=metrics([p['planning_time_ratio'] for p in valid if p['planning_time_ratio'] is not None])))
    result=dict(purpose=plan['purpose'],episodes=episodes,pending=pending,modes=modes,comparisons=comparisons,statistics='Paired game/seed bootstrap 10000 resamples; no action resampling. n<2 CI unavailable; 3 seeds exploratory; multiple comparisons descriptive.',timing='Wall game time and planning CPU wall time are separate. Real-time idle/catch-up can differ across budgets; same fruit prefix is audited, not identical physics histories.')
    reports=root/'reports';reports.mkdir(exist_ok=True);index=0
    while (reports/f'{index:04d}').exists():index+=1
    dest=reports/f'{index:04d}';dest.mkdir();save(dest/'comparison.json',result)
    fields=['iterations','depth','seed','search_seed','natural_go','termination','final_score','last_observed_score','operations','successful_drops','merges','maximum_fruit_type','planning_p95_ms','planning_total_seconds','game_wall_seconds','physical_ticks','search_go_samples','errors']
    with (dest/'games.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields+['planning_mean_ms','go_false_negative','go_false_positive']);w.writeheader()
        for r in episodes:
            row={k:r[k] for k in fields};row.update(planning_mean_ms=r['planning_ms'].get('mean'),go_false_negative=r['go_confusion']['false_negative'],go_false_positive=r['go_confusion']['false_positive']);row['errors']=json.dumps(row['errors']);w.writerow(row)
    with (dest/'pairs.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['a','b','seed','eligible','a_score','b_score','b_minus_a','reasons','mean_decision_time_ratio'])
        for c in comparisons:
            for r in c['pairs']:w.writerow([c['a'],c['b'],r['seed'],r['eligible'],r['a_score'],r['b_score'],r['difference'],';'.join(r['reasons']),r.get('mean_decision_time_ratio')])
    with (dest/'comparisons.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['a','b','valid_pairs','excluded_pairs','wins_a','wins_b','ties','mean_b_minus_a','ci95_low','ci95_high','mean_decision_time_ratio','total_planning_time_ratio'])
        for c in comparisons:w.writerow([c['a'],c['b'],c['valid_pairs'],c['excluded_pairs'],c['wins_a'],c['wins_b'],c['ties'],c['difference'].get('mean'),*(c['mean_difference_95ci'] or [None,None]),c['mean_decision_time_ratio'].get('mean'),c['total_planning_time_ratio'].get('mean')])
    # Explicit summary CSV, including valid counts and score extrema.
    with (dest/'summary.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['iterations','completed','valid_natural_go','truncated','mean','median','min','max'])
        for n,r in modes.items():w.writerow([n,r['completed'],r['valid_natural_go'],r['truncated'],*[r['scores'].get(k) for k in ['mean','median','minimum','maximum']]])
    print(json.dumps(dict(report=str(dest),completed=len(episodes),pending=len(pending)),ensure_ascii=False),flush=True)
    return result

def run(root,plan):
    if sha(plan['exe'])!=plan['exe_sha256'] or assembly_sha(plan['exe'])!=plan['assembly_sha256']:raise ValueError('Player changed since experiment creation; start a new experiment')
    if any(plan['settings'][str(n)]!=settings(n,plan['search_seed']) for n in plan['budgets']):raise ValueError('Tool settings changed since experiment creation')
    for index,j in enumerate(plan['jobs']):
        if completed(root,j) is not None:continue
        base=root/j['key'];base.mkdir(parents=True,exist_ok=True);attempt=0
        while (base/f'attempt_{attempt:03d}').exists():attempt+=1
        folder=base/f'attempt_{attempt:03d}'
        print(json.dumps(dict(progress=index+1,total=len(plan['jobs']),seed=j['seed'],iterations=j['iterations'],attempt=attempt)),flush=True)
        summary=run_parallel(Path(plan['exe']),folder,games=1,episodes=1,max_steps=plan['max_steps'],base_port=plan['base_port'],seed=j['seed'],headless=True,settings=settings(j['iterations'],plan['search_seed']),main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION,step_timeout=plan['step_timeout'])
        ep=audit_game(folder,j['iterations'],plan['search_seed'])
        if ep['termination'] in ('stopped','incomplete_or_error') or ep['worker_errors']:
            save(folder/'interrupted_audit.json',ep);summarize(root,plan);raise RuntimeError('Game interrupted/failed; logs retained. Resume will retry only this unfinished job.')
        files=[folder/'run.json',folder/'game_00.jsonl',folder/'metadata/game_00.json']
        save(base/'result.json',dict(job=j,episode=ep,hashes={str(p.relative_to(root)):sha(p) for p in files}))
        report=summarize(root,plan)
        errors=[e for e in ep['errors'] if not e.startswith('not_natural_go:')]
        if errors:raise ValueError('Completed game failed integrity audit: '+str(errors))
    return summarize(root,plan)

def make_plan(budgets,seeds,search_seed,exe,max_steps,port,smoke,step_timeout=120):
    if not math.isfinite(step_timeout) or step_timeout<=0:raise ValueError("Invalid step timeout")
    if len(budgets)<2 or len(set(budgets))!=len(budgets):raise ValueError('Choose at least two distinct budgets')
    if len(set(seeds))!=len(seeds) or not seeds:raise ValueError('Unique nonempty seed group required')
    for n in budgets:settings(n,search_seed)
    for seed in seeds:worker_specs(1,port,seed)
    if max_steps<1 or (smoke and (len(seeds)!=1 or max_steps>8)):raise ValueError('Smoke is one seed, at most eight hands per condition')
    jobs=[]
    for i,seed in enumerate(seeds):
        order=budgets[i%len(budgets):]+budgets[:i%len(budgets)]
        for n in order:jobs.append(dict(key=f'seed_{seed}/iterations_{n}',seed=seed,iterations=n))
    return dict(schema_version=1,purpose='smoke_not_strength' if smoke else 'natural_go_comparison',budgets=budgets,seeds=seeds,search_seed=search_seed,exe=str(exe.resolve()),exe_sha256=sha(exe),assembly_sha256=assembly_sha(exe),step_timeout=step_timeout,max_steps=max_steps,base_port=port,jobs=jobs,rules_version=RULES_VERSION,settings={str(n):settings(n,search_seed) for n in budgets},order='rotate condition order across seeds; single Player; one seed initialization per game')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--budgets',nargs='+',type=int);p.add_argument('--games',type=int);p.add_argument('--seed',type=int);p.add_argument('--search-seed',type=int);p.add_argument('--max-steps',type=int);p.add_argument('--base-port',type=int);p.add_argument('--exe',type=Path);p.add_argument('--step-timeout',type=float);p.add_argument('--smoke',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--analyze-only',action='store_true');a=p.parse_args();root=a.output.resolve()
    if a.resume or a.analyze_only:
        plan=read(root/'experiment_plan.json')
        for key in ['budgets','search_seed','max_steps','base_port','step_timeout']:
            if getattr(a,key) is not None and getattr(a,key)!=plan[key]:p.error('Resume settings must match stored plan: '+key)
        if a.seed is not None and a.seed!=plan['seeds'][0]:p.error('Resume seed mismatch')
        if a.games is not None and a.games!=len(plan['seeds']):p.error('Resume game count mismatch')
        if a.exe is not None and str(a.exe.resolve())!=plan['exe']:p.error('Resume executable mismatch')
    else:
        exe=a.exe or Path('../Unity/Builds/Step6/SuikaGameAI.exe');games=a.games if a.games is not None else 3;seed=a.seed if a.seed is not None else 758300
        if games<1:p.error('Positive games required')
        plan=make_plan(a.budgets or list(BUDGETS),list(range(seed,seed+games)),a.search_seed if a.search_seed is not None else 8191,exe,a.max_steps if a.max_steps is not None else 3000,a.base_port if a.base_port is not None else 39200,a.smoke,a.step_timeout if a.step_timeout is not None else 120)
        root.mkdir(parents=True,exist_ok=False);save(root/'experiment_plan.json',plan)
    with experiment_lock(root):
        if a.analyze_only:summarize(root,plan)
        else:run(root,plan)
if __name__=='__main__':main()
