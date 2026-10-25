"""Validate public-context open-loop diagnostics without treating shared statistics as copied physics."""
import argparse,collections,json
from pathlib import Path
from analyze_two_step_probe import trace_search

def validate_open_report(decision,m):
    if m['tree_policy']!='public_open_loop':raise ValueError('Not open-loop')
    nodes=m['nodes'];visits=[0]*len(nodes);arrivals=[0]*len(nodes);edge_counts=[[0]*len(n['actions']) for n in nodes];states=[set() for _ in nodes]
    for it in m['iterations']:
        count=len(it['actions']);arrivals[0]+=1
        if any(len(it[k])!=count for k in ['tree_node_ids','public_observations','state_signatures','rollout_steps']):raise ValueError('Incomplete public-state trace')
        for depth,action in enumerate(it['actions']):
            held=decision['held_fruit_type'] if depth==0 else decision['next_fruit_type'] if depth==1 else m['public_spawn_types'][it['chance_slots'][depth-2]]
            nxt=decision['next_fruit_type'] if depth==0 else -1 if depth==m['max_depth']-1 else m['public_spawn_types'][it['chance_slots'][depth-1]]
            expected=f'{held}:{nxt}'
            if it['public_observations'][depth]!=expected:raise ValueError('Wrong public held/NEXT timing')
            nid=it['tree_node_ids'][depth]
            if it['rollout_steps'][depth]:
                if nid!=-1:raise ValueError('Rollout falsely backed up as tree node')
                if depth+1<count and not it['rollout_steps'][depth+1]:raise ValueError('Rollout switched back into tree')
                continue
            if not 0<=nid<len(nodes):raise ValueError('Invalid node id')
            node=nodes[nid];history=''.join('/'+str(a) for a in it['actions'][:depth])
            if node['public_context']!=expected or node['history_key']!=history:raise ValueError('Different public contexts merged')
            expanded=edge_counts[nid][action]==0
            states[nid].add(it['state_signatures'][depth]);visits[nid]+=1;edge_counts[nid][action]+=1
            if depth+1<count:
                edge=node['actions'][action];slot=it['chance_slots'][depth]
                child=edge['chance_node_ids'][edge['chance_slots'].index(slot)]
                new=arrivals[child]==0;arrivals[child]+=1
                if it['rollout_steps'][depth+1]!=(expanded or new):raise ValueError('Wrong open-loop expansion/rollout boundary')
    for i,node in enumerate(nodes):
        if visits[i]!=node['visits'] or arrivals[i]!=node['arrivals'] or edge_counts[i]!=[a['visits'] for a in node['actions']]:raise ValueError('Open-loop visits not conserved')
        if len(states[i])!=node['distinct_states']:raise ValueError('Wrong distinct-state accounting')
    if m['leaf_cache_hits'] or m['skipped_physics_ticks']:raise ValueError('Unsafe shared-state leaf cache used')

def analyze(rows):
    result=[];groups={}
    for r in rows:
        if r.get('error'):raise ValueError(r['error'])
        if r['policy']=='information-tests':
            if not r['root_unchanged']:raise ValueError('Info test mutated root')
            continue
        d=r['decision'];m=r['report'];s=d['settings']
        if not(r['root_unchanged'] and m['source_unchanged'] and m['prefixes_match']):raise ValueError('Source changed')
        if s['tree_policy']=='chance':trace_search(r)
        else:validate_open_report(d,m)
        if m['common_chance']:
            for it in m['iterations']:
                for depth,c in enumerate(it['chance_slots']):
                    if c>=0 and c!=m['common_chance_samples'][it['iteration']*m['max_depth']+depth]:raise ValueError('Chance sample changed')
        its=m['iterations'];prefixes=collections.Counter(tuple(i['actions'][:2]) for i in its if len(i['actions'])>=2);paths=collections.Counter(tuple(i['actions']) for i in its)
        name='legacy' if not m['common_chance'] else 'A_chance' if s['tree_policy']=='chance' else 'B_public_open_loop'
        item=dict(fixture=Path(r['fixture']).stem,label=name,selected_x=d['selected_x'],settings=s,wall_ms=r['wall_ms'],ticks=m['total_physics_ticks'],advances=m['physics_advances'],nodes=m['decision_nodes'],root_actions=m['nodes'][0]['actions'],rollout_by_depth=m['rollout_by_depth'],depth_histogram=dict(collections.Counter(i['depth'] for i in its)),unique_two_action_prefixes=len(prefixes),two_action_revisits=sum(n-1 for n in prefixes.values()),full_path_revisits=sum(n-1 for n in paths.values()),visited_nonroot_nodes=sum(n['visits']>0 for n in m['nodes'][1:]),multi_state_nodes=sum(n['distinct_states']>1 for n in m['nodes']),known15_prefix=sum([a/(s['candidate_count']-1) for a in i['actions'][:2]]==[.125,.125] for i in its),known18_prefix=sum([a/(s['candidate_count']-1) for a in i['actions'][:2]]==[.5,0.] for i in its),mean_return=sum(i['reward'] for i in its)/len(its),max_return=max(i['reward'] for i in its),max_merges=max(i['merges'] for i in its),go_samples=sum(i['game_over'] for i in its),unity_start_bytes=m['unity_allocated_start_bytes'],unity_sampled_peak_bytes=m['unity_allocated_sampled_peak_bytes'],managed_start_bytes=m['managed_start_bytes'],managed_end_bytes=m['managed_end_bytes'],source_verified=True)
        result.append(item)
        if m['common_chance']:groups.setdefault(item['fixture'],[]).append(r)
    matching=[]
    for fixture,rs in groups.items():
        if len(rs)!=2 or rs[0]['report']['common_chance_samples']!=rs[1]['report']['common_chance_samples']:raise ValueError('Unmatched common chance table')
        x,y=rs
        fields=['actions','chance_slots','reward','merges','game_over','simulated_ticks','rollout_steps']
        equal=all(all(a[k]==b[k] for k in fields) for a,b in zip(x['report']['iterations'],y['report']['iterations']))
        matching.append(dict(fixture=fixture,all_iteration_transitions_equal=equal,common_chance_verified=True,shared_tick_budget=min(r['report']['total_physics_ticks'] for r in rs),same_physics_ticks=x['report']['total_physics_ticks']==y['report']['total_physics_ticks']))
    return dict(searches=result,matching=matching,information_cases=[r for r in rows if r['policy']=='information-tests'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=analyze([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,allow_nan=False)
    for s in report['searches']:print(json.dumps({k:s[k] for k in ['fixture','label','selected_x','wall_ms','two_action_revisits','multi_state_nodes','known18_prefix']}))
if __name__=='__main__':main()
