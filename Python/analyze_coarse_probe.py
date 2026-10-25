"""Audit root-only Coarse-to-Fine, variable action counts and full candidate cost."""
import argparse,collections,json
from pathlib import Path
from analyze_two_step_probe import trace_search

def validate_decision(d,m):
    s=d['settings'];ref=m.get('refinement');ctf=s['candidate_policy']=='coarse-root';xs=[a['x'] for a in m['nodes'][0]['actions']]
    if m['candidate_policy']!=s['candidate_policy'] or s.get('expansion_policy','legacy')!='legacy' or s.get('action_order_policy','index')!='index':raise ValueError('Wrong candidate/expansion/order policy')
    expected=[i/(len(xs)-1) for i in range(len(xs))]
    if ctf:
        if len(xs)!=7 or len(set(xs))!=7 or xs!=sorted(xs) or not set([0,.25,.5,.75,1]).issubset(xs) or ref['positions']!=xs:raise ValueError('Coarse anchors or root mapping lost')
        if len(ref['added'])!=2 or len(set(ref['parents']))!=2 or set(ref['added'])!=set(xs)-{0,.25,.5,.75,1}:raise ValueError('Invalid refinement diversity')
        if any(x not in [.125,.375,.625,.875] for x in ref['added']):raise ValueError('Invalid midpoint')
        for parent,x in zip(ref['parents'],ref['added']):
            if abs(x-parent/4)>.125001:raise ValueError('Wrong parent neighborhood')
        coarse=ref['coarse'];rank=sorted(range(5),key=lambda i:(not(coarse[i]['drop_success'] and not coarse[i]['predicted_game_over']),-coarse[i]['evaluation']['value'],-ref['geometry'][i],i))
        if ref['ranking']!=rank:raise ValueError('Wrong coarse ranking')
        if ref['physics_advances']!=5 or sum(c['physics_steps'] for c in coarse)!=ref['physics_ticks']:raise ValueError('Refinement work missing')
        for c in coarse:
            if abs(c['evaluation']['value']-(c['reward']/s['score_scale']-s['weight_roughness']*c['evaluation']['roughness']))>1e-5:raise ValueError('Coarse formula mismatch')
            if c['reward']!=c['movement_reward']+c['cooldown_wait_reward']+c['post_drop_reward']:raise ValueError('Coarse reward accounting mismatch')
    elif xs!=expected:raise ValueError('Fixed grid changed')
    if [c['x'] for c in d['candidates']]!=xs:raise ValueError('Action and candidate mapping mismatch')
    for node in m['nodes'][1:]:
        count=5 if ctf else s['candidate_count']
        if [a['x'] for a in node['actions']]!=[i/(count-1) for i in range(count)]:raise ValueError('Future grid changed')
    traces=trace_search(dict(decision=d,report=m))
    if sum(i['simulated_ticks'] for i in m['iterations'])!=m['total_physics_ticks'] or sum(i['depth']-int(i['cached_leaf']) for i in m['iterations'])!=m['physics_advances']:raise ValueError('MCTS physical work mismatch')
    if m['common_chance']:
        for it in m['iterations']:
            for depth,chance in enumerate(it['chance_slots']):
                if chance>=0 and chance!=m['common_chance_samples'][it['iteration']*s['mcts_max_depth']+depth]:raise ValueError('Chance sample changed')
    if m['extra_decisions'] or any(i['extra_decisions'] for i in m['iterations']):raise ValueError('Additional expansion enabled')
    return traces

def analyze(rows):
    result=[];groups={}
    for r in rows:
        if r.get('error') or not r['root_unchanged']:raise ValueError('Probe/source failure')
        d=r['decision'];m=r['report'];s=d['settings'];trace=validate_decision(d,m);ref=m.get('refinement') if s['candidate_policy']=='coarse-root' else None
        if not m['source_unchanged'] or not m['prefixes_match']:raise ValueError('Source/prefix changed')
        label='coarse7-root' if ref else 'grid'+str(s['candidate_count'])
        prefixes=collections.Counter(tuple(t['x'] for t in it['steps'][:2]) for it in trace if it['depth']>=2)
        item=dict(fixture=Path(r['fixture']).stem,seed=m['seed'],label=label,selected_x=d['selected_x'],root_actions=m['nodes'][0]['actions'],refinement=ref,nodes=m['decision_nodes'],nonroot_edge_revisits=sum(max(0,a['visits']-1) for n in m['nodes'][1:] for a in n['actions']),registered_by_depth=[sum(a['visits']>0 for n in m['nodes'] if n['depth']==depth for a in n['actions']) for depth in range(s['mcts_max_depth'])],depth_histogram=dict(collections.Counter(i['depth'] for i in m['iterations'])),known15_prefix=prefixes[(.125,.125)],known18_prefix=prefixes[(.5,0)],mean_reward=sum(i['reward'] for i in m['iterations'])/len(m['iterations']),max_reward=max(i['reward'] for i in m['iterations']),mean_merges=sum(i['merges'] for i in m['iterations'])/len(m['iterations']),go_samples=sum(i['game_over'] for i in m['iterations']),root_go=d['candidates'][d['selected_index']]['predicted_game_over'],mcts_ticks=m['total_physics_ticks'],generation_ticks=ref['physics_ticks'] if ref else 0,total_ticks=m['total_physics_ticks']+(ref['physics_ticks'] if ref else 0),generation_ms=m['candidate_generation_ms'],mcts_ms=m['mcts_search_ms'],total_ms=r['wall_ms'],gc0=r['gc0'],managed_delta=m['managed_end_bytes']-m['managed_start_bytes'],unity_sampled_delta=m['unity_allocated_sampled_peak_bytes']-m['unity_allocated_start_bytes'],iterations=m['iterations'],trace=trace)
        result.append(item);groups.setdefault((r['fixture'],m['seed']),[]).append((item,m))
    matched=[]
    for key,group in groups.items():
        if len(group)!=3 or len({json.dumps(m['common_chance_samples']) for x,m in group})!=1:raise ValueError('Unmatched A/B/C chance conditions')
        budget=min(x['total_ticks'] for x,m in group)
        for x,m in group:
            ticks=x['generation_ticks'];kept=[]
            for it in x['iterations']:
                if ticks+it['simulated_ticks']>budget:break
                ticks+=it['simulated_ticks'];kept.append(it)
            matched.append(dict(fixture=x['fixture'],seed=x['seed'],label=x['label'],budget=budget,ticks=ticks,iterations=len(kept),mean_reward=sum(i['reward'] for i in kept)/len(kept),generation_ms=x['generation_ms'],prefix_iteration_ms=sum(i['elapsed_ms'] for i in kept),note='Post-hoc complete iteration prefix, generation ticks charged first; not a separate time-budgeted run'))
    return dict(searches=result,matched_tick_prefixes=matched)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2,allow_nan=False)
    for x in r['searches']:print(json.dumps({k:x[k] for k in ['fixture','seed','label','selected_x','mean_reward','go_samples','generation_ms','mcts_ms','total_ms','total_ticks']}))
if __name__=='__main__':main()
