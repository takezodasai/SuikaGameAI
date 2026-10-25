"""Sequential single-feature STEP8-T comparisons. No long experiment is started without this CLI."""
import argparse,json,math,sys,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from adaptive_profiles import PROFILES,profile,audit_decision
from compare_mcts_ai import episode,RULES_VERSION
from compare_mcts_budget import save,read,sha,assembly_sha,completed,experiment_lock,summarize,percentile
from suika_ai.parallel_play import run_parallel,validate_run,worker_specs

def audit_game(folder,name,expected):
    manifest=read(folder/'run.json');ep=episode(folder,manifest,manifest['workers'][0],expected_settings=expected,flexible_mcts=True);ep['audit']=validate_run(folder)
    rows=[json.loads(l) for l in (folder/'game_00.jsonl').read_text(encoding='utf-8-sig').splitlines()];decisions=[]
    for r in rows:
        if r.get('event')!='transition':continue
        d=r['info']['planning']
        for k,v in expected.items():
            actual=d['settings'].get(k)
            if not (math.isclose(v,actual,rel_tol=1e-6,abs_tol=1e-7) if type(v) in (int,float) and type(actual) in (int,float) else v==actual):raise ValueError('Executed setting differs: '+k)
        decisions.append(audit_decision(d))
    times=ep['planning_ms_per_action'];counts=[d['completed'] for d in decisions]
    ep.update(condition=name,iterations=expected['mcts_iterations'],depth=expected['mcts_max_depth'],search_seed=expected['mcts_seed'],allocation=expected['mcts_budget_mode'],maximum_iterations=expected['mcts_max_iterations'],actual_iterations=counts,actual_iteration_mean=statistics.mean(counts) if counts else None,actual_iteration_min=min(counts) if counts else None,actual_iteration_max=max(counts) if counts else None,peak_unity_allocated_bytes=max([r['info']['planning']['mcts']['unity_allocated_sampled_peak_bytes'] for r in rows if r.get('event')=='transition'] or [0]),decision_audits=decisions,planning_p95_ms=percentile(times),planning_total_seconds=sum(times)/1000,physical_ticks=sum(d['physical_ticks'] for d in decisions),search_go_samples=sum(sum(i['game_over'] for i in r['info']['planning']['mcts']['iterations']) for r in rows if r.get('event')=='transition'),double_watermelon_known=False,double_watermelon_success=None)
    return ep

def run(root,plan):
    if sha(plan['exe'])!=plan['exe_sha256'] or assembly_sha(plan['exe'])!=plan['assembly_sha256']:raise ValueError('Player differs from saved experiment')
    if any(sha(Path(__file__).parent/p)!=digest for p,digest in plan['python_sources'].items()):raise ValueError('Python implementation changed since experiment creation')
    for index,j in enumerate(plan['jobs']):
        if completed(root,j) is not None:continue
        name=j['iterations'];base=root/j['key'];base.mkdir(parents=True,exist_ok=True);attempt=0
        while (base/f'attempt_{attempt:03d}').exists():attempt+=1
        folder=base/f'attempt_{attempt:03d}';s=plan['settings'][name]
        print(json.dumps(dict(progress=index+1,total=len(plan['jobs']),condition=name,seed=j['seed'],attempt=attempt)),flush=True)
        run_parallel(Path(plan['exe']),folder,games=1,episodes=1,max_steps=plan['max_steps'],base_port=plan['base_port'],seed=j['seed'],headless=True,settings=s,main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION,step_timeout=plan['step_timeout'])
        ep=audit_game(folder,name,s)
        if ep['termination'] in ('stopped','incomplete_or_error') or ep['worker_errors']:
            save(folder/'interrupted_audit.json',ep);summarize(root,plan);raise RuntimeError('Interrupted game retained; resume retries this unfinished job')
        files=[folder/'run.json',folder/'game_00.jsonl',folder/'metadata/game_00.json']
        save(base/'result.json',dict(job=j,episode=ep,hashes={str(p.relative_to(root)):sha(p) for p in files}));summarize(root,plan)
        errors=[e for e in ep['errors'] if not e.startswith('not_natural_go:')]
        if errors:raise ValueError('Integrity failure: '+str(errors))
    return summarize(root,plan)

def make_plan(names,seeds,exe,max_steps,port,smoke,options):
    if len(names)<2 or len(set(names))!=len(names) or not seeds or len(set(seeds))!=len(seeds):raise ValueError('Distinct conditions and game seeds required')
    if max_steps<1 or (smoke and (len(seeds)!=1 or max_steps>8)):raise ValueError('Smoke: one seed, at most eight hands per condition')
    settings={n:profile(n,**options) for n in names}
    for seed in seeds:worker_specs(1,port,seed)
    jobs=[]
    for i,seed in enumerate(seeds):
        for name in names[i%len(names):]+names[:i%len(names)]:jobs.append(dict(key=f'seed_{seed}/{name}',seed=seed,iterations=name))
    sources=['compare_adaptive_mcts.py','adaptive_profiles.py','compare_mcts_budget.py','compare_mcts_ai.py','compare_value_ai.py','analyze_two_step_probe.py','src/suika_ai/unity_env.py','src/suika_ai/parallel_play.py']
    return dict(python_sources={p:sha(Path(__file__).parent/p) for p in sources},purpose='smoke_not_strength' if smoke else 'single_feature_natural_go_comparison',budgets=names,seeds=seeds,settings=settings,jobs=jobs,exe=str(exe.resolve()),exe_sha256=sha(exe),assembly_sha256=assembly_sha(exe),max_steps=max_steps,base_port=port,step_timeout=max(120,options['time_limit']+60),rules_version=RULES_VERSION,options=options)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--profiles',nargs='+',choices=PROFILES);p.add_argument('--games',type=int);p.add_argument('--seed',type=int);p.add_argument('--search-seed',type=int);p.add_argument('--iterations',type=int);p.add_argument('--depth',type=int);p.add_argument('--candidates',type=int);p.add_argument('--time-limit',type=float);p.add_argument('--max-iterations',type=int);p.add_argument('--widen-after',type=int);p.add_argument('--widen-max',type=int);p.add_argument('--max-steps',type=int);p.add_argument('--base-port',type=int);p.add_argument('--exe',type=Path);p.add_argument('--smoke',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--analyze-only',action='store_true');a=p.parse_args();root=a.output.resolve()
    option_defaults=dict(iterations=32,depth=4,candidates=5,time_limit=5.,max_iterations=256,widen_after=10,widen_max=9,search_seed=8191)
    if a.resume or a.analyze_only:
        plan=read(root/'experiment_plan.json')
        for key in option_defaults:
            if getattr(a,key) is not None and getattr(a,key)!=plan['options'][key]:p.error('Resume option differs: '+key)
        for key,expected in [('profiles',plan['budgets']),('games',len(plan['seeds'])),('seed',plan['seeds'][0]),('max_steps',plan['max_steps']),('base_port',plan['base_port'])]:
            if getattr(a,key) is not None and getattr(a,key)!=expected:p.error('Resume option differs: '+key)
        if a.exe is not None and str(a.exe.resolve())!=plan['exe']:p.error('Resume Player differs')
    else:
        options={k:getattr(a,k) if getattr(a,k) is not None else v for k,v in option_defaults.items()};games=a.games if a.games is not None else 3;seed=a.seed if a.seed is not None else 760300
        if games<1:p.error('Positive game count required')
        plan=make_plan(a.profiles or ['legacy','adaptive'],list(range(seed,seed+games)),a.exe or Path('../Unity/Builds/Step8T/SuikaGameAI.exe'),a.max_steps if a.max_steps is not None else 3000,a.base_port if a.base_port is not None else 39500,a.smoke,options)
        root.mkdir(parents=True,exist_ok=False);save(root/'experiment_plan.json',plan)
    with experiment_lock(root):
        if a.analyze_only:summarize(root,plan)
        else:run(root,plan)
if __name__=='__main__':main()
