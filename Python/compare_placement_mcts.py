"""STEP8-U: sequential legacy/grid9/widening comparisons, actual-only event audit."""
import argparse,csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from compare_adaptive_mcts import make_plan,audit_game
from compare_mcts_budget import read,save,sha,assembly_sha,completed,experiment_lock,summarize
from suika_ai.parallel_play import run_parallel
from compare_mcts_ai import RULES_VERSION
from episode_events import audit_events

def summary(root,plan):
    report=summarize(root,plan)
    dest=sorted((root/'reports').iterdir())[-1]
    data=[dict(condition=e['condition'],seed=e['seed'],natural_go=e['natural_go'],final_score=e['final_score'],maximum_fruit_type=e['maximum_fruit_type'],**{k:e[k] for k in ['double_watermelon_known','double_watermelon_success','actual_events']}) for e in report['episodes']]
    save(dest/'actual_events.json',data)
    with (dest/'actual_events.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['condition','seed','natural_go','final_score','maximum_fruit_type','known','watermelons_created','double_watermelons'])
        for e in data:
            s=e['actual_events'] or {};w.writerow([e['condition'],e['seed'],e['natural_go'],e['final_score'],e['maximum_fruit_type'],e['double_watermelon_known'],s.get('watermelons_created'),s.get('double_watermelons')])
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

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--profiles',nargs='+',choices=['legacy','grid9','widening'],default=None);p.add_argument('--games',type=int);p.add_argument('--seed',type=int);p.add_argument('--search-seed',type=int);p.add_argument('--iterations',type=int);p.add_argument('--depth',type=int);p.add_argument('--max-steps',type=int);p.add_argument('--base-port',type=int);p.add_argument('--exe',type=Path);p.add_argument('--smoke',action='store_true');p.add_argument('--no-events',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--analyze-only',action='store_true');a=p.parse_args();root=a.output.resolve()
    if a.resume or a.analyze_only:
        plan=read(root/'experiment_plan.json')
        for key,value in [('profiles',plan['budgets']),('games',len(plan['seeds'])),('seed',plan['seeds'][0]),('search_seed',plan['options']['search_seed']),('iterations',plan['options']['iterations']),('depth',plan['options']['depth']),('max_steps',plan['max_steps']),('base_port',plan['base_port'])]:
            if getattr(a,key) is not None and getattr(a,key)!=value:p.error('Resume setting differs: '+key)
        if a.exe is not None and str(a.exe.resolve())!=plan['exe']:p.error('Resume Player differs')
        if a.no_events and plan['episode_events']:p.error('Resume event setting differs')
    else:
        options=dict(iterations=a.iterations if a.iterations is not None else 128,depth=a.depth if a.depth is not None else 4,candidates=5,time_limit=5.,max_iterations=256,widen_after=10,widen_max=9,search_seed=a.search_seed if a.search_seed is not None else 8191)
        games=a.games if a.games is not None else 3;seed=a.seed if a.seed is not None else 761100
        if games<1:p.error('games must be positive')
        plan=make_plan(a.profiles or ['legacy','grid9','widening'],list(range(seed,seed+games)),a.exe or Path('../Unity/Builds/Step8U/SuikaGameAI.exe'),a.max_steps if a.max_steps is not None else 3000,a.base_port if a.base_port is not None else 39700,a.smoke,options)
        plan['episode_events']=not a.no_events
        # Include every local Python module used by collection/audit in resume fingerprint.
        for f in list((Path(__file__).parent/'src/suika_ai').glob('*.py'))+[Path(__file__),Path(__file__).with_name('episode_events.py')]:plan['python_sources'][str(f.relative_to(Path(__file__).parent)).replace('\\','/')]=sha(f)
        root.mkdir(parents=True,exist_ok=False);save(root/'experiment_plan.json',plan)
    with experiment_lock(root):
        if a.analyze_only:summary(root,plan)
        else:run(root,plan)
if __name__=='__main__':main()
