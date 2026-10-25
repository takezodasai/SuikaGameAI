"""Audit STEP8-N chance-decision expansion, returns, visits and bounded physical work."""
import argparse,collections,json
from pathlib import Path
from analyze_two_step_probe import trace_search

def summarize_rows(rows):
    output=[];groups={}
    for row in rows:
        if row.get('error') or not row['root_unchanged']:raise ValueError('Probe/source failure')
        d=row['decision'];m=row['report'];s=d['settings'];trace=trace_search(row);its=m['iterations'];n=s['candidate_count']
        if not m['source_unchanged'] or not m['prefixes_match']:raise ValueError('Source or prefix changed')
        for key in ['extra_decisions','expanded_actions','new_chance_nodes']:
            if sum(i[key] for i in its)!=m[key]:raise ValueError('Wrong total '+key)
        if m['new_chance_nodes']!=m['decision_nodes']-1:raise ValueError('Chance node creation mismatch')
        if sum(i['simulated_ticks'] for i in its)!=m['total_physics_ticks'] or sum(i['depth']-int(i['cached_leaf']) for i in its)!=m['physics_advances']:raise ValueError('Physical work accounting mismatch')
        for it,t in zip(its,trace):
            if it['depth']>s['mcts_max_depth']:raise ValueError('Depth changed')
            if m['common_chance']:
                for depth,chance in enumerate(it['chance_slots']):
                    if chance>=0 and chance!=m['common_chance_samples'][it['iteration']*s['mcts_max_depth']+depth]:raise ValueError('Chance sample changed')
            if s['expansion_policy']=='chance_decision':
                for depth,step in enumerate(t['steps']):
                    if it['tree_node_ids'][depth]!=(-1 if step['phase']=='rollout' else step['node_id']):raise ValueError('Wrong backed-up node')
                    held=d['held_fruit_type'] if depth==0 else d['next_fruit_type'] if depth==1 else m['public_spawn_types'][it['chance_slots'][depth-2]]
                    nxt=d['next_fruit_type'] if depth==0 else -1 if depth==s['mcts_max_depth']-1 else m['public_spawn_types'][it['chance_slots'][depth-1]]
                    if it['public_observations'][depth]!=f'{held}:{nxt}':raise ValueError('Public fruit timing mismatch')
        prefix=collections.Counter(tuple(i['actions'][:2]) for i in its if i['depth']>=2)
        phase_depth=[sum(len(i['rollout_steps'])>depth and not i['rollout_steps'][depth] for i in its) for depth in range(s['mcts_max_depth'])]
        edge_depth=[sum(a['visits']>0 for node in m['nodes'] if node['depth']==depth for a in node['actions']) for depth in range(s['mcts_max_depth'])]
        label='legacy_rng' if not m['common_chance'] else 'A_legacy' if s['expansion_policy']=='legacy' else 'B_chance_decision'
        item=dict(fixture=Path(row['fixture']).stem,label=label,settings=s,selected_x=d['selected_x'],root_actions=m['nodes'][0]['actions'],nodes=m['decision_nodes'],chance_expansions=m['new_chance_nodes'],decision_action_expansions=m['expanded_actions'],extra_decisions=m['extra_decisions'],registered_actions_by_depth=edge_depth,tree_action_visits_by_depth=phase_depth,unused_nodes=sum(node['visits']==0 for node in m['nodes']),nonroot_tree_edge_revisits=sum(max(0,a['visits']-1) for node in m['nodes'][1:] for a in node['actions']),two_action_revisits=sum(v-1 for v in prefix.values()),unique_two_action_prefixes=len(prefix),rollout_by_depth=m['rollout_by_depth'],rollout_start_depths=dict(collections.Counter(next((j+1 for j,b in enumerate(i['rollout_steps']) if b),0) for i in its)),depth_histogram=dict(collections.Counter(i['depth'] for i in its)),known15_prefix=sum([a/(n-1) for a in i['actions'][:2]]==[.125,.125] for i in its),known18_prefix=sum([a/(n-1) for a in i['actions'][:2]]==[.5,0] for i in its),mean_return=sum(i['reward'] for i in its)/len(its),max_return=max(i['reward'] for i in its),max_merges=max(i['merges'] for i in its),go_samples=sum(i['game_over'] for i in its),physics_advances=m['physics_advances'],physical_ticks=m['total_physics_ticks'],logical_ticks=sum(i['ticks'] for i in its),wall_ms=row['wall_ms'],managed_start_bytes=m['managed_start_bytes'],managed_end_bytes=m['managed_end_bytes'],unity_start_bytes=m['unity_allocated_start_bytes'],unity_sampled_peak_bytes=m['unity_allocated_sampled_peak_bytes'],iterations=its,trace=trace)
        output.append(item)
        if m['common_chance']:groups.setdefault((item['fixture'],n,s['mcts_iterations']),[]).append((item,m))
    matched=[]
    for key,group in groups.items():
        if len(group)!=2 or group[0][1]['common_chance_samples']!=group[1][1]['common_chance_samples']:raise ValueError('Unmatched common chance tables')
        budget=min(i['physical_ticks'] for i,m in group)
        for item,m in group:
            its=[];ticks=0
            for i in item['iterations']:
                if ticks+i['simulated_ticks']>budget:break
                its.append(i);ticks+=i['simulated_ticks']
            counts=[0]*key[1];scores=[0.]*key[1]
            for i in its:counts[i['actions'][0]]+=1;scores[i['actions'][0]]+=i['total_points']
            legal=[a for a in range(key[1]) if counts[a] and not item['root_actions'][a]['immediate_go'] and item['root_actions'][a]['drop_success']]
            choice=max(legal,key=lambda a:(counts[a],scores[a]/counts[a])) if legal else None
            matched.append(dict(fixture=key[0],candidates=key[1],label=item['label'],tick_budget=budget,iterations=len(its),ticks=ticks,iteration_time_ms=sum(i['elapsed_ms'] for i in its),selected_x=None if choice is None else choice/(key[1]-1),mean_return=sum(i['reward'] for i in its)/len(its),go_samples=sum(i['game_over'] for i in its),note='post-hoc complete iteration prefix; not a separately timed run'))
    return dict(searches=output,matched_tick_prefixes=matched)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=summarize_rows([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2,allow_nan=False)
    for s in r['searches']:print(json.dumps({k:s[k] for k in ['fixture','label','selected_x','decision_action_expansions','registered_actions_by_depth','known18_prefix','mean_return','go_samples','physical_ticks','wall_ms']}))
if __name__=='__main__':main()
