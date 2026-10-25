"""Audit STEP8-L fixed-board rollout logs and matched-tick prefixes."""
import argparse,collections,json
from pathlib import Path
from analyze_two_step_probe import trace_search

def summarize_rows(rows):
    groups={};output=[]
    for row in rows:
        if row.get('error') or not row['root_unchanged']:raise ValueError('Probe failure or root contamination')
        s=row['decision']['settings'];m=row['report'];trace=trace_search(row)
        if not m['source_unchanged'] or not m['prefixes_match']:raise ValueError('Source/prefix contamination')
        for it,t in zip(m['iterations'],trace):
            inferred=[p['phase']=='rollout' for p in t['steps']]
            if inferred!=it['rollout_steps']:raise ValueError('Rollout phase mismatch')
            if len(it['guided_steps'])!=len(inferred) or any(g and not r for g,r in zip(it['guided_steps'],inferred)):raise ValueError('Guidance outside rollout')
            if m['common_chance']:
                if len(m['common_chance_samples'])!=s['mcts_iterations']*s['mcts_max_depth']:raise ValueError('Incomplete chance table')
                for depth,chance in enumerate(it['chance_slots']):
                    if chance>=0 and chance!=m['common_chance_samples'][it['iteration']*s['mcts_max_depth']+depth]:raise ValueError('Chance sample mismatch')
        counts=[sum(len(it['rollout_steps'])>d and it['rollout_steps'][d] for it in m['iterations']) for d in range(s['mcts_max_depth'])]
        if counts!=m['rollout_by_depth'] or sum(counts)!=m['rollout_calls']:raise ValueError('Rollout count mismatch')
        if sum(sum(it['guided_steps']) for it in m['iterations'])!=m['guided_calls']:raise ValueError('Guided count mismatch')
        count=s['candidate_count'];its=m['iterations'];label='legacy' if not m['common_chance'] else 'A_random' if s['rollout_policy']=='random' else 'B_guided90' if abs(s['rollout_random_probability']-.1)<1e-6 else 'C_mixed50'
        item=dict(fixture=Path(row['fixture']).stem,label=label,settings=s,selected_x=row['decision']['selected_x'],wall_ms=row['wall_ms'],ticks=m['total_physics_ticks'],advances=m['physics_advances'],rollout_calls=m['rollout_calls'],guided_calls=m['guided_calls'],rollout_by_depth=counts,rollout_choice_ms=m['rollout_choice_ms'],choice_mean_ms=m['rollout_choice_ms']/m['rollout_calls'] if m['rollout_calls'] else 0,depth_histogram=dict(collections.Counter(it['depth'] for it in its)),root_actions=m['nodes'][0]['actions'],nodes=m['decision_nodes'],max_sample_reward=max(it['reward'] for it in its),mean_sample_reward=sum(it['reward'] for it in its)/len(its),max_sample_merges=max(it['merges'] for it in its),terminal_samples=sum(it['game_over'] for it in its),known15_prefix_count=sum([a/(count-1) for a in it['actions'][:2]]==[.125,.125] for it in its),known18_prefix_count=sum([a/(count-1) for a in it['actions'][:2]]==[.5,0.] for it in its),common_chance_samples=m.get('common_chance_samples'),iterations=its,source_verified=True,unity_delta_bytes=m['unity_allocated_sampled_peak_bytes']-m['unity_allocated_start_bytes'])
        output.append(item)
        if m['common_chance']:groups.setdefault((item['fixture'],count,s['mcts_iterations']),[]).append(item)
    matched=[]
    for key,items in groups.items():
        if any(i['common_chance_samples']!=items[0]['common_chance_samples'] for i in items):raise ValueError('Common chance tables differ')
        budget=min(i['ticks'] for i in items)
        for item in items:
            prefix=[];ticks=0
            for it in item['iterations']:
                if ticks+it['simulated_ticks']>budget:break
                prefix.append(it);ticks+=it['simulated_ticks']
            n=item['settings']['candidate_count'];visits=[0]*n;scores=[0.]*n
            for it in prefix:visits[it['actions'][0]]+=1;scores[it['actions'][0]]+=it['total_points']
            legal=[i for i,a in enumerate(item['root_actions']) if not a['immediate_go'] and a['drop_success'] and visits[i]]
            best=max(legal,key=lambda i:(visits[i],scores[i]/visits[i])) if legal else None
            matched.append(dict(fixture=key[0],count=key[1],label=item['label'],shared_tick_budget=budget,iterations=len(prefix),ticks=ticks,iteration_time_ms=sum(it['elapsed_ms'] for it in prefix),selected_x=None if best is None else best/(n-1),visits=visits,mean_sample_reward=sum(it['reward'] for it in prefix)/len(prefix),terminal_samples=sum(it['game_over'] for it in prefix),note='Post-hoc complete-iteration prefix, not a separate wall-time-budgeted run; excludes setup/report/cleanup overhead'))
    return dict(searches=output,matched_tick_prefixes=matched)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=summarize_rows([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
    for s in result['searches']:print(json.dumps({k:s[k] for k in ['fixture','label','selected_x','wall_ms','ticks','known15_prefix_count','known18_prefix_count','terminal_samples']}))
if __name__=='__main__':main()
