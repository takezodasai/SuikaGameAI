"""Audit fixed-root STEP8-K diagnostics; never runs games or changes input logs."""
import argparse,csv,json,math
from pathlib import Path

def trace_search(row):
    report=row['report'];settings=row['decision']['settings'];count=settings['candidate_count']
    coarse=settings.get('candidate_policy')=='coarse-root'
    widening=settings.get('mcts_widening',False);additions=report.get('candidate_additions') or [];applied=set()
    def apply_additions(iteration,nid):
        for k,a in enumerate(additions):
            if a['iteration']!=iteration or a['node_id']!=nid:continue
            if k in applied:raise ValueError('Duplicate candidate addition')
            n=nodes[nid];index=len(n['edges'])
            if a['index']!=index or a['node_visits']!=n['visits'] or not 0<=a['left']<a['x']<a['right']<=1 or abs(a['x']-(a['left']+a['right'])/2)>1e-7:raise ValueError('Invalid widening event')
            old=[z['x'] for z in report['nodes'][nid]['actions'][:index]]
            if any(abs(x-a['x'])<settings['widening_min_spacing']*.999 for x in old) or abs(report['nodes'][nid]['actions'][index]['x']-a['x'])>1e-7:raise ValueError('Duplicate/mismatched candidate')
            n['edges'].append(dict(visits=0,total=0.,children={}));applied.add(k)

    # Reconstruct only control-flow and visit counts. No invented child rewards.
    nodes=[dict(visits=0,arrivals=0,edges=[dict(visits=0,total=0.,children={}) for _ in range(count)])]
    trace=[];extend=settings.get('expansion_policy','legacy')=='chance_decision'
    shuffle=settings.get('action_order_policy','index')=='shuffle'
    if shuffle:
        for node in report['nodes']:
            if sorted(node.get('unvisited_order') or [])!=list(range(count)):raise ValueError('Invalid shuffle permutation')
    for it in report['iterations']:
        if widening:apply_additions(it['iteration'],0)
        root=nodes[0];safe=any(e['visits']==0 or (not m['immediate_go'] and m['drop_success']) for e,m in zip(root['edges'],report['nodes'][0]['actions']))
        scores=[];expected=None
        for index,(e,m) in enumerate(zip(root['edges'],report['nodes'][0]['actions'])):
            if safe and e['visits'] and (m['immediate_go'] or not m['drop_success']):scores.append(None);continue
            if e['visits']==0:
                scores.append(None)
                if expected is None:expected=index
            else:scores.append(e['total']/e['visits']/settings['mcts_point_scale']+settings['mcts_exploration']*math.sqrt(math.log(max(1,root['visits']))/e['visits']))
        if shuffle:
            unvisited=[a for a in report['nodes'][0]['unvisited_order'] if root['edges'][a]['visits']==0]
            if unvisited:expected=unvisited[0]
        if expected is None and safe:expected=max((i for i,v in enumerate(scores) if v is not None),key=lambda i:scores[i])
        coverage=it['iteration']<settings.get('pair_coverage_iterations',0)
        if 'coverage_requested' in it and it['coverage_requested']!=coverage:raise ValueError('Coverage request mismatch')
        if coverage:
            proposed=it['iteration']%5;e=root['edges'][proposed];metric=report['nodes'][0]['actions'][proposed]
            if not e['visits'] or (not metric['immediate_go'] and metric['drop_success']):expected=proposed
        if safe and expected!=it['actions'][0]:raise ValueError('Root UCT replay mismatch')
        root['arrivals']+=1;node_id=0;rollout=False;pending=[];steps=[];extra_used=False;extra_pending=False;extras=0;expansions=0;new_nodes=0
        for depth,(action,chance) in enumerate(zip(it['actions'],it['chance_slots'])):
            if extra_pending:extra_used=True;extra_pending=False;extras+=1
            if 'rollout_steps' in it and rollout!=it['rollout_steps'][depth]:raise ValueError('Rollout boundary mismatch')
            if widening and not rollout and depth>0:apply_additions(it['iteration'],node_id)
            local_count=len(nodes[node_id]['edges']) if widening and not rollout else 5 if coarse and depth>0 else count
            if not 0<=action<local_count:raise ValueError('Action outside local candidate count')
            actual_x=report['nodes'][node_id]['actions'][action]['x'] if widening and not rollout else report['nodes'][0]['actions'][action]['x'] if coarse and depth==0 else action/(local_count-1)
            if (coarse or widening) and (len(it.get('action_x') or [])!=len(it['actions']) or abs(it['action_x'][depth]-actual_x)>1e-7):raise ValueError('Root/future coordinate mapping mismatch')
            e=None if rollout else nodes[node_id]['edges'][action]
            if shuffle and not rollout:
                first=next((a for a in report['nodes'][node_id]['unvisited_order'] if nodes[node_id]['edges'][a]['visits']==0),None)
                if first is not None and action!=first:raise ValueError('Shuffled first visit order mismatch')
            if settings.get('pair_coverage_iterations',0):
                proposed=it['iteration']%5 if depth==0 else [0,2,4,1,3][it['iteration']//5] if depth==1 and coverage else None
                force=coverage and depth<2
                if force and not rollout:
                    prior=nodes[node_id]['edges'][proposed];metric=report['nodes'][node_id]['actions'][proposed]
                    force=not prior['visits'] or (not metric['immediate_go'] and metric['drop_success'])
                if len(it.get('coverage_forced_steps') or [])!=len(it['actions']) or it['coverage_forced_steps'][depth]!=force:raise ValueError('Coverage force accounting mismatch')
                if force and action!=proposed:raise ValueError('Coverage schedule mismatch')
            expanded=e is not None and e['visits']==0
            if expanded:expansions+=1
            steps.append(dict(depth=depth+1,action_index=action,x=actual_x,chance=chance,node_id=None if rollout else node_id,phase='rollout' if rollout else 'expansion' if expanded else 'selection_replay'))
            if e is not None:pending.append((node_id,e))
            if depth+1<len(it['actions']) and not rollout:
                new=chance not in e['children']
                if new:new_nodes+=1;e['children'][chance]=len(nodes);nodes.append(dict(visits=0,arrivals=0,edges=[dict(visits=0,total=0.,children={}) for _ in range(5 if coarse else count)]))
                node_id=e['children'][chance];nodes[node_id]['arrivals']+=1
                extra_pending=extend and new and not extra_used
                rollout=(expanded or new) and not extra_pending
                steps[-1]['next_rollout_reason']='expanded_edge_and_new_chance' if expanded and new else 'new_chance' if new else 'expanded_edge' if expanded else None
        if extras>1:raise ValueError('Extra-decision quota exceeded')
        for key,value in [('extra_decisions',extras),('expanded_actions',expansions),('new_chance_nodes',new_nodes)]:
            if key in it and it[key]!=value:raise ValueError('Expansion accounting mismatch: '+key)
        trace.append(dict(extra_decisions=extras,expanded_actions=expansions,new_chance_nodes=new_nodes,iteration=it['iteration'],root_visits_before=root['visits'],root_uct_before=scores,steps=steps,reward=it['reward'],merges=it['merges'],game_over=it['game_over'],depth=it['depth']))
        for nid,e in pending:nodes[nid]['visits']+=1;e['visits']+=1
        root['edges'][it['actions'][0]]['total']+=it['total_points']
    if widening and len(applied)!=len(additions):raise ValueError('Unapplied candidate addition')
    if len(nodes)!=len(report['nodes']):raise ValueError('Node creation replay mismatch')
    for node,logged in zip(nodes,report['nodes']):
        if node['visits']!=logged['visits'] or node['arrivals']!=logged['arrivals'] or [e['visits'] for e in node['edges']]!=[a['visits'] for a in logged['actions']]:raise ValueError('Tree visit replay mismatch')
    for e,m in zip(nodes[0]['edges'],report['nodes'][0]['actions']):
        if 'mean_points' in m and abs((e['total']/e['visits'] if e['visits'] else 0)-m['mean_points'])>1e-8:raise ValueError('Root reward backpropagation mismatch')
    return trace

def analyze(path):
    rows=[json.loads(l) for l in Path(path).read_text(encoding='utf-8-sig').splitlines()]
    if any(r.get('error') for r in rows):raise ValueError('Probe reports a failure')
    scans=[r for r in rows if r['policy']=='exhaustive-nine']
    if len(scans)!=1:raise ValueError('Exactly one fixed fixture required')
    scan=scans[0];d=scan['exhaustive'];outcomes=d['outcomes']
    if len(outcomes)!=81 or {(r['first_index'],r['second_index']) for r in outcomes}!={(i,j) for i in range(9) for j in range(9)}:raise ValueError('Incomplete pair grid')
    if not all(d[k] for k in ['root_unchanged','random_unchanged','live_unchanged']):raise ValueError('Source contamination')
    for r in outcomes:
        if not r['prefix_match'] or r['total_reward']!=r['first_reward']+r['second_reward'] or r['ticks']!=r['first_ticks']+r['second_ticks']:raise ValueError('Pair conservation or prefix failure')
        if r['first_go'] and (r['second_drop'] or r['second_ticks']):raise ValueError('Drop after first GO')
    def rank(r):
        safe=not r['game_over'] and r['first_drop'] and r['second_drop']
        return (not safe,0 if safe else r['terminal_excess'],0 if safe else -r['ticks'],-r['total_reward'],r['first_index'],r['second_index'])
    if d['selected_path']!=min(range(81),key=lambda i:rank(outcomes[i])):raise ValueError('Diagnostic best-path selection mismatch')
    known=outcomes[10];result=dict(fixture=scan['fixture'],initial_score=scan['initial']['score'],initial_current=scan['initial']['current_fruit'],initial_next=scan['initial']['next_fruit_type'],initial_build_ms=scan['initial_build_ms'],exhaustive=d,known_pair=known,searches=[])
    for row in rows:
        if row['policy']!='grid':continue
        trace=trace_search(row);report=row['report'];count=row['decision']['settings']['candidate_count'];selected=row['decision']['selected_x']
        histogram={str(depth):sum(t['depth']==depth for t in trace) for depth in range(1,5)}
        target=[t for t in trace if count==9 and t['steps'][0]['action_index']==1]
        prefixes=sorted({tuple(s['x'] for s in t['steps'][:2]) for t in trace if t['steps'][0]['x']==selected and len(t['steps'])>=2})
        prefix_outcomes=[r for r in outcomes if (r['first_x'],r['second_x']) in prefixes]
        result['searches'].append(dict(count=count,iterations=report['completed_iterations'],selected_x=selected,wall_ms=row['wall_ms'],physics_advances=report['physics_advances'],ticks=report['total_physics_ticks'],nodes=report['decision_nodes'],managed_start_bytes=report['managed_start_bytes'],managed_end_bytes=report['managed_end_bytes'],unity_start_bytes=report['unity_allocated_start_bytes'],unity_sampled_peak_bytes=report['unity_allocated_sampled_peak_bytes'],depth_histogram=histogram,root_actions=report['nodes'][0]['actions'],known_first_visits=target,known_prefix_visits=[t for t in target if len(t['steps'])>=2 and t['steps'][1]['action_index']==1],selected_first_two_prefixes=prefix_outcomes,trace=trace,control_flow_verified=True))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=analyze(a.input)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    csv_path=a.output.with_suffix('.csv')
    with csv_path.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result['exhaustive']['outcomes'][0]));w.writeheader();w.writerows(result['exhaustive']['outcomes'])
    print(json.dumps(dict(best=result['exhaustive']['outcomes'][result['exhaustive']['selected_path']],known=result['known_pair']),ensure_ascii=False))
if __name__=='__main__':main()
