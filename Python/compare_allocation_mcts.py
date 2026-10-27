"""STEP8-X: four single-Player conditions; immutable resume plan, actual-game events."""
import argparse,csv,json,sys,math,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel,validate_run,worker_specs
from compare_mcts_ai import episode,RULES_VERSION
from compare_mcts_budget import read,save,sha,assembly_sha,completed,experiment_lock,summarize,percentile
from episode_events import audit_events

MODES=('fixed128','adaptive5','adaptive9','fixed256')
def settings(mode,search_seed=8191,time_limit=20):
    if mode not in MODES:raise ValueError('Unknown condition')
    return validate_planning_settings(dict(ai_mode='mcts',candidate_count=5,mcts_max_depth=4,
        mcts_extended_budget=True,mcts_auto_depth=False,mcts_seed=search_seed,
        mcts_iterations=256 if mode=='fixed256' else 128 if mode=='fixed128' else 32,
        mcts_max_iterations=512,mcts_time_limit_seconds=time_limit,
        mcts_budget_mode='adaptive' if mode.startswith('adaptive') else 'fixed',
        mcts_widening=mode=='adaptive9',widening_policy='budgeted' if mode=='adaptive9' else 'legacy',
        widening_max_candidates=9))

def audit_decision(d):
    s=d['settings'];m=d['mcts'];n=m['completed_iterations'];cap=s['mcts_iterations'] if s['mcts_budget_mode']=='fixed' else s['mcts_max_iterations']
    def check(ok,why):
        if not ok:raise ValueError(why)
    check(32<=n<=cap and m['iteration_cap']==cap,'Iteration bounds')
    check(m['source_unchanged'] and m['prefixes_match'] and d['same_source_verified'],'Source mutation')
    check(m['max_depth']==s['mcts_max_depth'] and not s['mcts_auto_depth'],'Depth changed')
    root=m['nodes'][0]['actions'];check(sum(a['visits'] for a in root)==n,'Root visit conservation')
    check(len(root)==len(d['candidates']),'Root candidate mismatch')
    xs=[a['x'] for a in root];check(len(set(xs))==len(xs) and all(0<=x<=1 for x in xs),'Illegal candidate')
    check(all(x in xs for x in [0,.25,.5,.75,1]),'Anchors missing')
    check(m['tree_policy']=='chance' and m['rollout_policy']=='random' and m['expansion_policy']=='legacy' and not m['common_chance'],'Algorithm differs')
    check(m['budget_stop_reason'] in ('iteration_limit','time_limit','adaptive_stable'),'Unknown stop')
    check(m['budget_stop_reason']!='iteration_limit' or n==cap,'False cap stop')
    check(m['budget_stop_reason']!='time_limit' or m['elapsed_ms']>=m['time_limit_ms'],'False time stop')
    check(abs(m['time_overrun_ms']-max(0,m['elapsed_ms']-s['mcts_time_limit_seconds']*1000))<.1,'Overrun accounting')
    checkpoints=m['budget_checkpoints'] or []
    if m['budget_stop_reason']=='adaptive_stable':
        check(s['mcts_budget_mode']=='adaptive' and checkpoints and checkpoints[-1]['stable'],'Unjustified early stop')
        check(not checkpoints[-1].get('candidate_guard_blocked'),'Pending candidate early stop')
    selected=d['selected_index'];check(0<=selected<len(root) and root[selected]['visits']>0,'Unvisited selection')
    check(not d['candidates'][selected]['predicted_game_over'] or d['all_predicted_terminal'],'GO selection')
    additions=m['candidate_additions'] or []
    for a in additions:
        check(a['final_revisits']==max(0,a['final_visits']-1),'Addition revisit count')
        check(0<a['x']<1 and a['iteration']<n,'Addition timing/location')
    if s['widening_policy']=='budgeted':
        check(len(root) in (5,7,9) and len(root)<=s['widening_max_candidates'],'Candidate cap')
        grouped={}
        for a in additions:grouped.setdefault((a['node_id'],a['iteration']),[]).append(a)
        check(all(len(v)==2 for v in grouped.values()),'Incomplete candidate stage')
        for a in additions:check(a['node_visits']>=32*(1+(a['index']-5)//2)**2,'Local threshold')
    if not m.get('compact_report'):
        check(len(m['iterations'])==n and sum(i['simulated_ticks'] for i in m['iterations'])==m['total_physics_ticks'],'Tick count')
    changes=sum(a['winner']!=b['winner'] for a,b in zip(checkpoints,checkpoints[1:]))
    return dict(completed=n,cap=cap,reason=m['budget_stop_reason'],elapsed_ms=m['elapsed_ms'],overrun_ms=m['time_overrun_ms'],
        root_candidates=len(root),selected_x=d['selected_x'],additions=len(additions),root_additions=sum(a['depth']==0 for a in additions),
        nonroot_additions=sum(a['depth']>0 for a in additions),added_visits=sum(a['final_visits'] for a in additions),added_revisits=sum(a['final_revisits'] for a in additions),
        added_actions=additions,checkpoints=checkpoints,selection_changes=changes,depth_metrics=m.get('depth_metrics'),physical_ticks=m['total_physics_ticks'])

def audit_game(folder,name,expected):
    manifest=read(folder/'run.json');ep=episode(folder,manifest,manifest['workers'][0],expected_settings=expected,flexible_mcts=True);ep['audit']=validate_run(folder)
    decisions=[];peak=0;go=0
    with (folder/'game_00.jsonl').open(encoding='utf-8-sig') as f:
        for line in f:
            r=json.loads(line)
            if r.get('event')!='transition':continue
            d=r['info']['planning'];m=d['mcts']
            for k,v in expected.items():
                actual=d['settings'].get(k)
                if not (math.isclose(v,actual,rel_tol=1e-6,abs_tol=1e-7) if type(v) in (int,float) and type(actual) in (int,float) else v==actual):raise ValueError('Executed setting differs: '+k)
            decisions.append(audit_decision(d));peak=max(peak,m['unity_allocated_sampled_peak_bytes']);go+=m['search_go_samples']
    counts=[d['completed'] for d in decisions];times=ep['planning_ms_per_action']
    ep.update(condition=name,iterations=expected['mcts_iterations'],depth=4,search_seed=expected['mcts_seed'],actual_iterations=counts,
        actual_iteration_mean=statistics.mean(counts) if counts else None,actual_iteration_min=min(counts,default=None),actual_iteration_max=max(counts,default=None),
        decision_audits=decisions,peak_unity_allocated_bytes=peak,planning_p95_ms=percentile(times),planning_total_seconds=sum(times)/1000,
        physical_ticks=sum(d['physical_ticks'] for d in decisions),search_go_samples=go)
    return ep

def summary(root,plan):
    report=summarize(root,plan)
    dest=sorted((root/'reports').iterdir())[-1]
    data=[dict(condition=e['condition'],seed=e['seed'],natural_go=e['natural_go'],final_score=e['final_score'],maximum_fruit_type=e['maximum_fruit_type'],**{k:e[k] for k in ['double_watermelon_known','double_watermelon_success','actual_events']}) for e in report['episodes']]
    save(dest/'actual_events.json',data)
    with (dest/'actual_events.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['condition','seed','natural_go','final_score','maximum_fruit_type','known','watermelons_created','double_watermelons'])
        for e in data:
            s=e['actual_events'] or {};w.writerow([e['condition'],e['seed'],e['natural_go'],e['final_score'],e['maximum_fruit_type'],e['double_watermelon_known'],s.get('watermelons_created'),s.get('double_watermelons')])
    allocation=[]
    for e in report['episodes']:
        for hand,d in enumerate(e['decision_audits'],1):allocation.append(dict(condition=e['condition'],seed=e['seed'],hand=hand,**d))
    save(dest/'allocation.json',allocation)
    fields=['condition','seed','hand','completed','cap','reason','elapsed_ms','overrun_ms','root_candidates','selected_x','additions','root_additions','nonroot_additions','added_visits','added_revisits','selection_changes','physical_ticks']
    with (dest/'allocation.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(allocation)
    rates={}
    for mode in plan['budgets']:
        valid=[e for e in report['episodes'] if e['condition']==mode and e['natural_go'] and not e['errors']]
        known=[e for e in valid if e['double_watermelon_known']]
        rates[mode]=dict(valid_natural_go=len(valid),event_known=len(known),unknown=len(valid)-len(known),
            first_watermelon_games=sum(e['actual_events']['watermelons_created']>=1 for e in known),
            double_games=sum(e['double_watermelon_success'] for e in known))
        rates[mode]['first_watermelon_rate']=rates[mode]['first_watermelon_games']/len(known) if known else None
        rates[mode]['double_rate']=rates[mode]['double_games']/len(known) if known else None
    save(dest/'achievement_rates.json',rates)
    return report

def run(root,plan):
    if sha(plan['exe'])!=plan['exe_sha256'] or assembly_sha(plan['exe'])!=plan['assembly_sha256']:raise ValueError('Saved Player changed')
    if any(sha(Path(__file__).parent/p)!=h for p,h in plan['python_sources'].items()):raise ValueError('Python changed; resume refused')
    for index,job in enumerate(plan['jobs'],1):
        if completed(root,job) is not None:continue
        name=job['iterations'];base=root/job['key'];base.mkdir(parents=True,exist_ok=True);attempt=0
        while (base/f'attempt_{attempt:03d}').exists():attempt+=1
        folder=base/f'attempt_{attempt:03d}';s=plan['settings'][name]
        print(json.dumps(dict(progress=index,total=len(plan['jobs']),condition=name,seed=job['seed'],attempt=attempt)),flush=True)
        run_parallel(Path(plan['exe']),folder,games=1,episodes=1,max_steps=plan['max_steps'],base_port=plan['base_port'],seed=job['seed'],headless=True,settings=s,main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION,step_timeout=plan['step_timeout'],episode_events=plan['episode_events'])
        ep=audit_game(folder,name,s)
        with (folder/'game_00.jsonl').open(encoding='utf-8-sig') as f:ev=audit_events(json.loads(line) for line in f)
        if plan['episode_events'] and not ev['double_watermelon_known']:raise ValueError('Player did not record actual events')
        ep.update(ev)
        if ep['actual_events'] and ep['actual_events']['drop_count']!=ep['successful_drops']:raise ValueError('Drop/event count mismatch')
        if ep['termination'] in ('stopped','incomplete_or_error') or ep['worker_errors']:
            save(folder/'interrupted_audit.json',ep);summary(root,plan);raise RuntimeError('Interrupted; retained, retry in new attempt on resume')
        errors=[e for e in ep['errors'] if not e.startswith('not_natural_go:')]
        if errors:raise ValueError('Integrity failure: '+str(errors))
        files=[folder/'run.json',folder/'game_00.jsonl',folder/'metadata/game_00.json'];save(base/'result.json',dict(job=job,episode=ep,hashes={str(p.relative_to(root)):sha(p) for p in files}));summary(root,plan)
    return summary(root,plan)


def make_plan(games,seed,search_seed,exe,max_steps,port,smoke,time_limit):
    if not 1<=games<=30 or max_steps<1 or (smoke and (games!=1 or max_steps>8)):raise ValueError('1..30 seeds; smoke one seed/at most eight hands')
    seeds=list(range(seed,seed+games));configs={n:settings(n,search_seed,time_limit) for n in MODES}
    for v in seeds:worker_specs(1,port,v)
    jobs=[]
    for i,v in enumerate(seeds):
        order=list(MODES[i%4:]+MODES[:i%4])
        if (i//4)%2:order.reverse()
        jobs.extend(dict(key=f'seed_{v}/{n}',seed=v,iterations=n) for n in order)
    sources=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'src/suika_ai').glob('*.py'))
    return dict(python_sources={str(p.relative_to(Path(__file__).parent)).replace('\\','/'):sha(p) for p in sources},
        purpose='smoke_not_strength' if smoke else 'allocation_natural_go',budgets=list(MODES),seeds=seeds,settings=configs,jobs=jobs,
        exe=str(exe.resolve()),exe_sha256=sha(exe),assembly_sha256=assembly_sha(exe),max_steps=max_steps,base_port=port,
        step_timeout=time_limit+90,rules_version=RULES_VERSION,episode_events=True,search_seed=search_seed,time_limit=time_limit,
        order='rotate order each seed, reverse alternate blocks of four; one Player')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    for key in ['games','seed','search-seed','max-steps','base-port']:p.add_argument('--'+key,type=int)
    p.add_argument('--time-limit',type=float);p.add_argument('--exe',type=Path);p.add_argument('--smoke',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--analyze-only',action='store_true');a=p.parse_args();root=a.output.resolve()
    if a.resume or a.analyze_only:
        plan=read(root/'experiment_plan.json')
        for k,v in [('games',len(plan['seeds'])),('seed',plan['seeds'][0]),('search_seed',plan['search_seed']),('time_limit',plan['time_limit']),('max_steps',plan['max_steps']),('base_port',plan['base_port'])]:
            if getattr(a,k) is not None and getattr(a,k)!=v:p.error('Resume differs: '+k)
        if a.exe is not None and str(a.exe.resolve())!=plan['exe']:p.error('Resume Player differs')
    else:
        plan=make_plan(a.games if a.games is not None else 3,a.seed if a.seed is not None else 763100,a.search_seed if a.search_seed is not None else 8191,a.exe or Path('../Unity/Builds/Step8X/SuikaGameAI.exe'),a.max_steps if a.max_steps is not None else 3000,a.base_port if a.base_port is not None else 39920,a.smoke,a.time_limit if a.time_limit is not None else 20)
        root.mkdir(parents=True,exist_ok=False);save(root/'experiment_plan.json',plan)
    with experiment_lock(root):
        if a.analyze_only:summary(root,plan)
        else:run(root,plan)
if __name__=='__main__':main()
