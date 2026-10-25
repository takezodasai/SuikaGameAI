"""STEP8-R audits: scheduled two-action coverage within a fixed iteration budget."""
import argparse,collections,json
from pathlib import Path
from analyze_expansion_probe import summarize_rows

def analyze(rows):
    groups={}
    for r in rows:
        if r.get('error'):raise ValueError(r['error'])
        s=r['decision']['settings']
        if s['expansion_policy']!='legacy' or s['rollout_policy']!='random':raise ValueError('Unexpected expansion/rollout')
        groups.setdefault((r['fixture'],s['mcts_seed'],s['candidate_count'],s['mcts_iterations']),[]).append(r)
    results=[];matched=[]
    for key,rs in groups.items():
        if len(rs)!=2 or {r['decision']['settings']['pair_coverage_iterations'] for r in rs}!={0,15}:raise ValueError('Missing paired policies')
        rs.sort(key=lambda r:r['decision']['settings']['pair_coverage_iterations'])
        check=summarize_rows(rs)
        for r,x in zip(rs,check['searches']):
            m=r['report'];s=x['settings'];x['label']='coverage15' if s['pair_coverage_iterations'] else 'legacy';x['seed']=s['mcts_seed'];x['gc0']=r['gc0']
            if m['pair_coverage_iterations']!=s['pair_coverage_iterations']:raise ValueError('Player ignored coverage budget')
            x['second_action_matrix']=[[0]*5 for i in range(5)]
            for it in m['iterations']:
                if len(it['actions'])>=2:x['second_action_matrix'][it['actions'][0]][it['actions'][1]]+=1
            x['coverage_complete_pairs']=len({tuple(it['actions'][:2]) for it in m['iterations'] if it['coverage_requested'] and len(it['actions'])>=2 and all(it['coverage_forced_steps'][:2])})
            x['reached_depth3']=sum(i['depth']>=3 for i in m['iterations']);x['reached_depth4']=sum(i['depth']>=4 for i in m['iterations'])
            x['nonroot_expansion_histogram']=[0]*s['candidate_count'];x['tree_second_histogram']=[0]*s['candidate_count']
            for t in x['trace']:
                for step in t['steps'][1:]:
                    if step['phase']=='expansion':x['nonroot_expansion_histogram'][step['action_index']]+=1
                if len(t['steps'])>1 and t['steps'][1]['phase']!='rollout':x['tree_second_histogram'][t['steps'][1]['action_index']]+=1
            x['nonroot_node_revisits']=sum(max(0,n['visits']-1) for n in m['nodes'][1:])
            x['chosen_mean_points']=x['root_actions'][r['decision']['selected_index']]['mean_points']
            x['selected_drop']=r['decision']['candidates'][r['decision']['selected_index']]
            x['node_orders']=[n.get('unvisited_order') for n in m['nodes']]
            results.append(x)
        for item,r in zip(check['matched_tick_prefixes'],rs):item['label']='coverage15' if r['decision']['settings']['pair_coverage_iterations'] else 'legacy';item['seed']=key[1];matched.append(item)
    return dict(searches=results,matched_tick_prefixes=matched,note='Three search seeds on three boards; not independent games, not a score-strength test.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
    for x in result['searches']:print(json.dumps({k:x[k] for k in ['fixture','seed','label','selected_x','unique_two_action_prefixes','coverage_complete_pairs','reached_depth3','reached_depth4','nonroot_tree_edge_revisits','known18_prefix','mean_return','physical_ticks','wall_ms']}))
if __name__=='__main__':main()
