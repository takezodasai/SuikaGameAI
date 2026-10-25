"""STEP8-J paired fixed-five versus fixed-nine experiment. One Player at a time."""
import argparse,csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from compare_mcts_ai import episode,paired_ci,metrics,RULES_VERSION
from suika_ai.parallel_play import run_parallel,validate_run

POLICIES=('grid5','grid9')
def settings(policy):
    if policy not in POLICIES:raise ValueError('Unknown grid comparison profile')
    return dict(ai_mode='mcts',candidate_policy='grid',candidate_count=5 if policy=='grid5' else 9,post_drop_steps=25,mcts_iterations=32,mcts_max_depth=4,mcts_seed=8191,mcts_exploration=2**.5,mcts_point_scale=55.,score_scale=55.,weight_height=0.,weight_danger=0.,weight_roughness=.2,search_leaf='reward',inter_step_wait_ticks=0,execution_mode='sync',frame_tick_slicing=False)

def validate_geometry(rows,policy):
    count=settings(policy)['candidate_count'];expected=[i/(count-1) for i in range(count)]
    for row in rows:
        if row.get('event')!='transition':continue
        d=row['info']['planning'];m=d['mcts']
        if d['settings'].get('candidate_policy')!='grid' or m.get('candidate_policy')!='grid':raise ValueError('Grid policy missing or wrong Player')
        if [c['x'] for c in d['candidates']]!=expected:raise ValueError('Root grid mismatch')
        for node in m['nodes']:
            if [a['x'] for a in node['actions']]!=expected:raise ValueError('Future node grid mismatch')
        if sum(a['visits'] for a in m['nodes'][0]['actions'])!=32:raise ValueError('Root visit count mismatch')

def summarize(root,report_dir=None):
    root=Path(root);plan=json.loads((root/'comparison_plan.json').read_text());episodes={};audit=[]
    for p in sorted(root.glob('seed_*/*/run.json')):
        manifest=json.loads(p.read_text());policy=p.parent.name
        if policy not in POLICIES or len(manifest['workers'])!=1:raise ValueError('Unexpected policy or parallel expansion')
        w=manifest['workers'][0];ep=episode(p.parent,manifest,w,expected_settings=settings(policy));ep['policy']=policy;ep['planning_settings']=manifest['settings']
        try:
            audit.append(dict(run=str(p.parent),checks=validate_run(p.parent)))
            rows=[json.loads(l) for l in (p.parent/(w['game_id']+'.jsonl')).read_text().splitlines()]
            validate_geometry(rows,policy)
        except (ValueError,KeyError,OSError) as e:ep['errors'].append('audit:'+str(e))
        group=episodes.setdefault(w['seed'],{})
        if policy in group:raise ValueError('Duplicate seed/policy')
        group[policy]=ep
    for seed in plan['seeds']:episodes.setdefault(seed,{})
    pairs=[]
    for seed,eps in sorted(episodes.items()):
        reasons=[]
        for policy in POLICIES:
            if policy not in eps:reasons.append(policy+':missing')
            else:reasons.extend(policy+':'+e for e in eps[policy]['errors'])
        if all(k in eps for k in POLICIES):
            a,b=eps['grid5'],eps['grid9'];n=min(len(a['public_series']),len(b['public_series']))
            ac={k:v for k,v in a['planning_settings'].items() if k!='candidate_count'}
            bc={k:v for k,v in b['planning_settings'].items() if k!='candidate_count'}
            if ac!=bc:reasons.append('planning_settings_mismatch')
            if n<2 or a['public_series'][:n]!=b['public_series'][:n]:reasons.append('public_series_mismatch')
            if not a['environment_id'] or a['environment_id']!=b['environment_id']:reasons.append('environment_mismatch')
            if not a['exe_sha256'] or a['exe_sha256']!=b['exe_sha256']:reasons.append('binary_mismatch')
        valid=not reasons
        pairs.append(dict(seed=seed,eligible=valid,exclusion_reasons=reasons,difference=eps['grid9']['final_score']-eps['grid5']['final_score'] if valid else None,**eps))
    valid=[p for p in pairs if p['eligible']];diff=[p['difference'] for p in valid];modes={}
    for policy in POLICIES:
        es=[p[policy] for p in valid]
        modes[policy]=dict(scores=metrics([e['final_score'] for e in es]),operations=metrics([e['operations'] for e in es]),merges=metrics([e['merges'] for e in es]),game_mean_planning_ms=metrics([e['planning_ms']['mean'] for e in es]),game_wall_seconds=metrics([e['game_wall_seconds'] for e in es]),go_confusion={k:sum(e['go_confusion'][k] for e in es) for k in ['tp','tn','false_negative','false_positive']})
    result=dict(status='completed' if len(valid)==len(pairs) and pairs else 'incomplete_or_invalid',purpose=plan['purpose'],eligible_pairs=len(valid),excluded_pairs=len(pairs)-len(valid),pairs=pairs,modes=modes,audit=audit,wins=dict(grid5=sum(d<0 for d in diff),grid9=sum(d>0 for d in diff),tie=sum(d==0 for d in diff)),nine_minus_five=metrics(diff),paired_mean_difference_95ci=paired_ci(diff),statistics='Paired seed/game bootstrap. Never resample hands; n<2 has no interval. Truncated games are excluded, including smoke runs.')
    if plan['purpose']=='pipeline_smoke_not_strength':
        unexpected=[reason for pair in pairs for reason in pair['exclusion_reasons'] if ':not_natural_go:' not in reason]
        if not unexpected and pairs:result['status']='smoke_completed_not_strength'
    dest=Path(report_dir) if report_dir else root
    if report_dir:dest.mkdir(parents=True,exist_ok=False)
    with (dest/'grid_comparison.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
    with (dest/'grid_pairs.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['seed','eligible','grid5_score','grid9_score','nine_minus_five','reasons'])
        for p in pairs:writer.writerow([p['seed'],p['eligible'],p.get('grid5',{}).get('final_score'),p.get('grid9',{}).get('final_score'),p['difference'],';'.join(p['exclusion_reasons'])])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--pairs',type=int,default=10);p.add_argument('--seed',type=int,default=751100);p.add_argument('--base-port',type=int,default=38100);p.add_argument('--max-steps',type=int,default=3000);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'));p.add_argument('--smoke',action='store_true');p.add_argument('--analyze-only',action='store_true');p.add_argument('--report-dir',type=Path);a=p.parse_args()
    if not a.analyze_only:
        if a.pairs<1 or a.max_steps<1:p.error('Positive counts required')
        if a.smoke and (a.pairs!=1 or a.max_steps>12):p.error('Smoke is one pair, at most 12 hands per game')
        a.output.mkdir(parents=True,exist_ok=False)
        plan=dict(purpose='pipeline_smoke_not_strength' if a.smoke else 'paired_strength_comparison',seeds=list(range(a.seed,a.seed+a.pairs)),settings={x:settings(x) for x in POLICIES},player_concurrency=1,order='alternate paired policy order')
        with (a.output/'comparison_plan.json').open('x') as f:json.dump(plan,f,indent=2)
        for index,seed in enumerate(plan['seeds']):
            for policy in (POLICIES if index%2==0 else POLICIES[::-1]):
                run_parallel(a.exe,a.output/f'seed_{seed}'/policy,games=1,episodes=1,max_steps=a.max_steps,base_port=a.base_port,seed=seed,headless=True,settings=settings(policy),main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES_VERSION)
    r=summarize(a.output,a.report_dir)
    print(json.dumps({k:r[k] for k in ['status','purpose','eligible_pairs','excluded_pairs','modes','wins','nine_minus_five','paired_mean_difference_95ci']},ensure_ascii=False))
    if r['purpose']=='pipeline_smoke_not_strength':
        bad=[reason for pair in r['pairs'] for reason in pair['exclusion_reasons'] if ':not_natural_go:' not in reason]
        if bad:raise SystemExit(2)
    elif r['excluded_pairs'] or not r['eligible_pairs']:raise SystemExit(2)
if __name__=='__main__':main()
