"""Paired cold-root comparison; continuations do not become historical exact labels."""
import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from watermelon_lab import write,public_difference,sha


def mean(x):return statistics.mean(x) if x else None


def audit_game(folder):
    result=json.loads((folder/'result.json').read_text());cfg=json.loads((folder/'config.json').read_text())
    rows=[json.loads(l) for l in (folder/'trace.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    start=next((r for r in rows if r['evt']=='root'),None);end=result['end'];decisions=[r for r in rows if r['evt']=='decision'];releases=[r for r in rows if r['evt']=='release']
    times=[r['planning_ms'] for r in decisions];adds=[a for r in decisions for a in r['search']['additions']]
    selected_new=sum(any(abs(a['x']-r['command']['x'])<1e-6 for a in r['search']['additions']) for r in decisions)
    boards=[r['state']['fruits'] for r in rows if r.get('state') and r['state'].get('fruits')]
    before_go=next((r for r in reversed(rows) if r['evt']!='end' and r.get('state') and not r['state'].get('game_over')),None)
    initial_melons=sum(f['type']==9 for f in start['state']['fruits']) if start else None
    g=dict(mode=cfg['mode'],future=cfg['future_seed'],fixture=cfg['fixture'],folder=str(folder),natural_go=result['natural_go'],reason=end['reason'] if end else 'no_end',error=result['process_error'],
           extra_score=end['additional_score'] if end else None,accepted_drops=end['accepted_drops'] if end else None,completed_actions=end['completed_actions'] if end else None,
           new_watermelons=end['new_watermelons'] if end else None,two_present=end['two_watermelons_present'] if end else None,doubles=end['double_watermelons'] if end else None,
           max_watermelons_present=end['max_watermelons_present'] if end else None,mean_decision_ms=mean(times),wall_seconds=result['wall_seconds'],
           initial_observed_melons=initial_melons,max_observed_melons=max((sum(f['type']==9 for f in fs) for fs in boards),default=0),
           max_observed_pineapples=max((sum(f['type']==8 for f in fs) for fs in boards),default=0),
           watermelon_and_two_melons_observed=any(any(f['type']==10 for f in fs) and sum(f['type']==9 for f in fs)>=2 for fs in boards),
           decisions=len(decisions),selected_added_count=selected_new,selected_added_rate=selected_new/len(decisions) if decisions else None,
           candidate_counts=dict(Counter(len(r['search']['root']) for r in decisions)),addition_count=len(adds),addition_visits=[a['final_visits'] for a in adds],
           addition_revisits=sum(a['final_revisits'] for a in adds),additions_predicted_GO=sum(a['immediate_go'] for a in adds),
           root_visit_sum_audit=all(sum(e['visits'] for e in r['search']['root'])==128==r['search']['completed_iterations'] for r in decisions),
           actual_max_depths=dict(Counter(r['search']['max_depth'] for r in decisions)),
           mean_nodes=mean([r['search']['nodes'] for r in decisions]),mean_physics_ticks=mean([r['search']['physics_ticks'] for r in decisions]),
           source_audit=all(r['search']['source_unchanged'] for r in decisions),
           remaining_scenes=end['retained_scenes'] if end else None,pending_unloads=end['pending_unloads'] if end else None,
           go_state=end['state'] if end else None,
           last_nonterminal_observation={k:before_go[k] for k in ['evt','tick','accepted_drops','score','state']} if before_go else None,
           public_sequence=[start['state']['current_fruit']['type'],start['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in releases] if start else [])
    if start:g['root_state']=start['state'];g['root_rng']=start['rng']
    import numpy as np
    g['p95_decision_ms']=float(np.percentile(times,95)) if times else None
    return g


def analyze(root):
    plan=json.loads((root/'plan.json').read_text());games=[];pairs=[];incomplete=[];unstarted=[];unfinished=[]
    for i in range(3):
        for future in plan['future_seeds']:
            cases={}
            for mode in ['baseline','refined']:
                folder=root/f'root{i}_f{future}'/mode
                if not (folder/'result.json').exists():
                    item=dict(root=i,future=future,mode=mode);incomplete.append(item)
                    (unfinished if folder.exists() else unstarted).append(item)
                    continue
                g=audit_game(folder);g['root']=i;games.append(g);cases[mode]=g
            if len(cases)!=2:continue
            a,b=cases['baseline'],cases['refined'];n=min(len(a['public_sequence']),len(b['public_sequence']))
            valid=a['natural_go'] and b['natural_go'] and not a['error'] and not b['error']
            pairs.append(dict(root=i,future=future,valid_natural_pair=valid,baseline_score=a['extra_score'],refined_score=b['extra_score'],
                              difference=b['extra_score']-a['extra_score'] if valid else None,baseline_drops=a['accepted_drops'],refined_drops=b['accepted_drops'],
                              shared_public_sequence_length=n,shared_public_sequence_equal=a['public_sequence'][:n]==b['public_sequence'][:n],
                              root_public_difference=public_difference(a['root_state'],b['root_state']),root_rng_equal=a['root_rng']==b['root_rng'],
                              root_geometry_equal=a['root_state']['geometry']==b['root_state']['geometry'],
                              root_cooldown_delta=b['root_state']['drop_cooldown_remaining']-a['root_state']['drop_cooldown_remaining'],
                              root_held_position_equal=all(a['root_state']['current_fruit'].get(k)==b['root_state']['current_fruit'].get(k) for k in ['x','y']),
                              exact_native_state_guaranteed=False))
    summary={}
    for mode in ['baseline','refined']:
        gs=[g for g in games if g['mode']==mode and g['natural_go'] and not g['error']]
        scores=[g['extra_score'] for g in gs];selection=sum(g['selected_added_count'] for g in gs);decisions=sum(g['decisions'] for g in gs)
        visits=[v for g in gs for v in g['addition_visits']]
        summary[mode]=dict(natural_games=len(gs),independent_source_roots=len(set(g['root'] for g in gs)),mean_extra_score=mean(scores),median_extra_score=statistics.median(scores) if scores else None,
                           min_extra_score=min(scores) if scores else None,max_extra_score=max(scores) if scores else None,mean_drops=mean([g['accepted_drops'] for g in gs]),
                           new_watermelon_games=sum(g['new_watermelons']>0 for g in gs),coexist_games=sum(g['two_present'] for g in gs),double_games=sum(g['doubles']>0 for g in gs),double_count=sum(g['doubles'] for g in gs),
                           mean_decision_ms=mean([g['mean_decision_ms'] for g in gs]),mean_game_wall_seconds=mean([g['wall_seconds'] for g in gs]),mean_nodes=mean([g['mean_nodes'] for g in gs]),mean_physics_ticks=mean([g['mean_physics_ticks'] for g in gs]),
                           additions=len(visits),mean_addition_visits=mean(visits),unvisited_additions=sum(v==0 for v in visits),selected_added=selection,decisions=decisions,selected_added_rate=selection/decisions if decisions else None,
                           candidate_counts=dict(sum((Counter(g['candidate_counts']) for g in gs),Counter())))
    valid=[p for p in pairs if p['valid_natural_pair']];diff=[p['difference'] for p in valid]
    paired=dict(n=len(valid),source_roots=len(set(p['root'] for p in valid)),wins=sum(d>0 for d in diff),losses=sum(d<0 for d in diff),ties=sum(d==0 for d in diff),mean_difference=mean(diff),median_difference=statistics.median(diff) if diff else None,
                per_root_mean_difference={i:mean([p['difference'] for p in valid if p['root']==i]) for i in range(3)},
                uncertainty='Only three chosen approximate source roots; future repeats are not nine independent original games. No general-population significance claim.')
    paired_keys={(p['root'],p['future']) for p in valid};matched_summary={}
    for mode in ['baseline','refined']:
        gs=[g for g in games if g['mode']==mode and (g['root'],g['future']) in paired_keys]
        scores=[g['extra_score'] for g in gs]
        matched_summary[mode]=dict(games=len(gs),mean_extra_score=mean(scores),median_extra_score=statistics.median(scores) if scores else None,
                                  mean_drops=mean([g['accepted_drops'] for g in gs]),mean_completed_actions=mean([g['completed_actions'] for g in gs]),
                                  mean_decision_ms=mean([g['mean_decision_ms'] for g in gs]),mean_wall_seconds=mean([g['wall_seconds'] for g in gs]),
                                  new_watermelon_games=sum(g['new_watermelons']>0 for g in gs),coexist_games=sum(g['two_present'] for g in gs),double_games=sum(g['doubles']>0 for g in gs))
    # Technical and ordinary source files are frozen, all experiment files are new.
    changes=[f for f,h in plan['protected'].items() if sha(f)!=h]
    return dict(summary=summary,matched_summary=matched_summary,paired=paired,pairs=pairs,games=games,incomplete=incomplete,unstarted=unstarted,unfinished=unfinished,changed_protected_sources=changes)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--name',default='analysis');a=p.parse_args();r=analyze(a.output)
    write(a.output/(a.name+'.json'),r)
    with (a.output/(a.name+'.csv')).open('x',encoding='utf8',newline='') as f:
        keys=['root','future','mode','natural_go','reason','extra_score','accepted_drops','completed_actions','new_watermelons','two_present','doubles','mean_decision_ms','p95_decision_ms','wall_seconds','selected_added_rate']
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(r['games'])
    print(json.dumps(dict(summary=r['summary'],paired=r['paired'],incomplete=len(r['incomplete']),changed_protected=r['changed_protected_sources'])),flush=True)


if __name__=='__main__':main()
