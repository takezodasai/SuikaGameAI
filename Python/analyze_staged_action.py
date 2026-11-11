"""Analyze branch ranks and allocation policies separately; no model fitting."""
import argparse,csv,json,statistics
from pathlib import Path
from watermelon_lab import public_difference,write,sha


def mean(xs):return statistics.mean(xs) if xs else None


def game(folder):
    if not (folder/'done.json').exists():return None
    result=json.loads((folder/'result.json').read_text());cfg=json.loads((folder/'config.json').read_text());rows=[json.loads(l) for l in (folder/'trace.jsonl').read_text().splitlines()];end=result['end'];start=result['root'];ds=[r for r in rows if r['evt']=='decision'];releases=[r for r in rows if r['evt']=='release'];times=[r['planning_ms'] for r in ds]
    import numpy as np
    expected=next((r for r in reversed(rows) if r.get('state') and not r['state']['game_over']),None)
    return dict(folder=str(folder),mode=cfg['mode'],future=cfg['future_seed'],first_x=cfg['first_x'],normal=cfg['normal_start'],natural_go=result['natural_go'],reason=end['reason'] if end else None,
                score=end['score'] if end else None,extra=end['additional_score'] if end else None,initial_score=start['score'],drops=end['accepted_drops'] if end else None,completed=end['completed_actions'] if end else None,
                initial_wm=start['initial_watermelons'],new_wm=end['new_watermelons'] if end else None,second_wm=end['second_watermelon_generated'] if end else None,two_present=end['two_watermelons_present'] if end else None,doubles=end['double_watermelons'] if end else None,
                mean_ms=mean(times),p95_ms=float(np.percentile(times,95)) if times else None,wall_seconds=result['wall_seconds'],decisions=len(ds),first_native_x=ds[0]['planning']['selected_x'] if ds else None,
                first_drop_tick=releases[0]['command']['drop_tick'] if releases else None,score_at_first_release=releases[0]['score'] if releases else None,
                initial_root=start['state'],initial_rng=start['rng'],public_sequence=[start['state']['current_fruit']['type'],start['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in releases],
                mean_physics_advances=mean([r['search']['physics_advances'] for r in ds]),mean_physics_ticks=mean([r['search']['physics_ticks'] for r in ds]),
                total_iterations=sum(r['search']['completed_iterations'] for r in ds),iterations128=all(r['search']['completed_iterations']==128 and sum(e['visits'] for e in r['search']['root'])==128 for r in ds),
                source_unchanged=all(r['search']['source_unchanged'] for r in ds),root_five=all(len(r['search']['root'])==5 for r in ds),
                baseline_reference_valid=all(r['command']['x']==r['planning']['selected_x'] for r in ds),allocations=[r['search']['allocation'] for r in ds if r['search']['allocation']],
                go_state=end['state'] if end else None,last_nonterminal=expected['state'] if expected else None,process_error=result['process_error'])


def match(a,b):
    n=min(len(a['public_sequence']),len(b['public_sequence']));valid=a['natural_go'] and b['natural_go'] and not a['process_error'] and not b['process_error']
    return dict(valid_natural_pair=valid,a_natural_go=a['natural_go'],b_natural_go=b['natural_go'],difference=b['extra']-a['extra'] if valid else None,drops_difference=b['drops']-a['drops'] if valid else None,
                difference_lower_bound=b['extra']-a['extra'] if a['natural_go'] and b['extra'] is not None else None,
                difference_upper_bound=b['extra']-a['extra'] if b['natural_go'] and a['extra'] is not None else None,
                bound_note='Nonterminal observed scores are lower bounds under nondecreasing game score; not final returns.',
                initial_public=public_difference(a['initial_root'],b['initial_root']),initial_rng_equal=a['initial_rng']==b['initial_rng'],
                geometry_equal=a['initial_root']['geometry']==b['initial_root']['geometry'],shared_fruit_length=n,shared_fruit_equal=a['public_sequence'][:n]==b['public_sequence'][:n],
                exact_native_state_guaranteed=False)


def analyze(root):
    plan=json.loads((root/'plan.json').read_text());selection=json.loads((root/'selections.json').read_text());branches=[];policies=[];games=[];missing=[]
    for r in plan['roots']:
        key=r['id']
        for future in plan['future_seeds']:
            path=root/'branches'/f'{key}_f{future}';a=game(path/'recommended');b=game(path/'alternative');c=game(root/'staged'/f'{key}_f{future}')
            for role,g in [('recommended',a),('alternative',b),('staged',c)]:
                if g:g.update(root=key,role=role);games.append(g)
                else:missing.append(dict(root=key,future=future,role=role))
            if a and b:branches.append(dict(root=key,future=future,recommended=a['extra'],alternative=b['extra'],recommended_x=selection[key]['recommended_x'],alternative_x=selection[key]['alternative_x'],**match(a,b)))
            if a and c:policies.append(dict(root=key,future=future,baseline=a['extra'],staged=c['extra'],reference_is_native=a['baseline_reference_valid'],**match(a,c)))
    normal=[]
    for mode in ['baseline','staged']:
        g=game(root/'normal'/mode)
        if g:g.update(root='normal',role=mode);normal.append(g)
    def summary(pairs,a,b):
        vs=[p for p in pairs if p['valid_natural_pair']];ds=[p['difference'] for p in vs]
        return dict(pairs=len(vs),source_roots=len(set(p['root'] for p in vs)),wins=sum(d>0 for d in ds),losses=sum(d<0 for d in ds),ties=sum(d==0 for d in ds),mean_difference=mean(ds),median_difference=statistics.median(ds) if ds else None,
                    mean_a=mean([p[a] for p in vs]),mean_b=mean([p[b] for p in vs]),per_root_mean={r['id']:mean([p['difference'] for p in vs if p['root']==r['id']]) for r in plan['roots']})
    aggregate={}
    for role in ['recommended','alternative','staged']:
        gs=[g for g in games if g['role']==role and g['natural_go']];xs=[g['extra'] for g in gs]
        aggregate[role]=dict(n=len(gs),mean_extra=mean(xs),median_extra=statistics.median(xs) if xs else None,mean_drops=mean([g['drops'] for g in gs]),mean_ms=mean([g['mean_ms'] for g in gs]),mean_wall=mean([g['wall_seconds'] for g in gs]),mean_physics_advances=mean([g['mean_physics_advances'] for g in gs]),mean_physics_ticks=mean([g['mean_physics_ticks'] for g in gs]),
                             new_watermelon_games=sum(g['new_wm']>0 for g in gs),second_games=sum(g['second_wm'] for g in gs),coexist_games=sum(g['two_present'] for g in gs),double_games=sum(g['doubles']>0 for g in gs))
    return dict(selection=selection,branch_pairs=branches,branch_summary=summary(branches,'recommended','alternative'),policy_pairs=policies,policy_summary=summary(policies,'baseline','staged'),aggregate=aggregate,games=games,normal=normal,normal_pair=match(*normal) if len(normal)==2 else None,
                missing=missing,protected_changes=[p for p,h in plan['protected'].items() if sha(p)!=h],note='Root branches compare first action with a common legacy continuation; staged comparison changes the whole policy. Two independent source roots; finite futures, not true optimal action labels.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--name',default='analysis_final');a=p.parse_args();r=analyze(a.output);write(a.output/(a.name+'.json'),r)
    keys=['root','future','role','natural_go','reason','score','extra','drops','new_wm','second_wm','two_present','doubles','mean_ms','p95_ms','wall_seconds','mean_physics_advances','total_iterations']
    with (a.output/(a.name+'.csv')).open('x',encoding='utf8',newline='') as f:w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(r['games']+r['normal'])
    print(json.dumps(dict(branch=r['branch_summary'],policy=r['policy_summary'],aggregate=r['aggregate'],missing=len(r['missing']),normal_games=len(r['normal']),protected_changes=r['protected_changes'])),flush=True)


if __name__=='__main__':main()
