"""STEP8-T allocation profiles and strict report audits, without launching games."""
import math
from suika_ai.unity_env import validate_planning_settings
from analyze_two_step_probe import trace_search
PROFILES=('legacy','time','adaptive','grid9','widening')
def profile(name,iterations=32,depth=4,candidates=5,time_limit=5.,max_iterations=256,widen_after=10,widen_max=9,search_seed=8191):
    if name not in PROFILES:raise ValueError('Unknown adaptive profile')
    s=dict(ai_mode='mcts',candidate_count=9 if name=='grid9' else candidates,mcts_iterations=iterations,mcts_max_depth=depth,mcts_seed=search_seed,mcts_budget_mode=name if name in ('time','adaptive') else 'fixed',mcts_time_limit_seconds=time_limit,mcts_max_iterations=max_iterations,mcts_widening=name=='widening',widening_after_visits=widen_after,widening_max_candidates=widen_max)
    return validate_planning_settings(s)

def audit_decision(d):
    s=d['settings'];m=d['mcts'];n=m['completed_iterations'];cap=s['mcts_iterations'] if s['mcts_budget_mode']=='fixed' else s['mcts_max_iterations']
    if not 1<=n<=cap or len(m['iterations'])!=n or m['iteration_cap']!=cap:raise ValueError('Incorrect iteration cap/completed count')
    if s['mcts_budget_mode']=='fixed' and n!=cap:raise ValueError('Fixed budget truncated')
    if m['max_depth']!=s['mcts_max_depth'] or not m['source_unchanged'] or not m['prefixes_match'] or not d['same_source_verified']:raise ValueError('Depth/source mismatch')
    if sum(i['simulated_ticks'] for i in m['iterations'])!=m['total_physics_ticks']:raise ValueError('Physical updates double counted or lost')
    if sum(a['visits'] for a in m['nodes'][0]['actions'])!=n:raise ValueError('Root visit conservation failed')
    if any(len(i['actions'])!=i['depth'] or i['depth']>s['mcts_max_depth'] for i in m['iterations']):raise ValueError('Depth accounting failed')
    if m['common_chance'] or m['tree_policy']!='chance' or m['rollout_policy']!='random' or m['expansion_policy']!='legacy':raise ValueError('Unintended tree/rollout change')
    trace_search(dict(decision=d,report=m))
    if s['mcts_budget_mode']!='fixed':
        if m['budget_stop_reason']=='iteration_limit' and n!=cap:raise ValueError('False iteration-limit claim')
        if m['budget_stop_reason']=='time_limit' and m['elapsed_ms']+1e-5<m['time_limit_ms']:raise ValueError('False time-limit claim')
        if m['budget_stop_reason']=='adaptive_stable' and (not m['budget_checkpoints'] or not m['budget_checkpoints'][-1]['stable']):raise ValueError('Unjustified adaptive stop')
        if abs(m['time_overrun_ms']-max(0,m['elapsed_ms']-s['mcts_time_limit_seconds']*1000))>.01:raise ValueError('Time overrun misreported')
    if len(d['candidates'])!=len(m['nodes'][0]['actions']):raise ValueError('Root candidates not synchronized')
    for node in m['nodes']:
        xs=[a['x'] for a in node['actions']]
        if any(not 0<=x<=1 for x in xs) or len(set(xs))!=len(xs):raise ValueError('Illegal/duplicate candidate')
    for it in m['iterations']:
        for depth,chance in enumerate(it['chance_slots']):
            if chance>=0:
                if depth+2>=m['max_depth'] or chance>=m['public_spawn_slots']:raise ValueError('Unexpected future chance')
            elif chance!=(-1 if depth+1==m['max_depth'] else -2 if depth+2==m['max_depth'] else -99):raise ValueError('Invalid chance boundary')
        if s['mcts_widening'] or s['mcts_budget_mode']!='fixed':
            if len(it['public_observations'])!=it['depth'] or len(it['tree_node_ids'])!=it['depth']:raise ValueError('Public/trace observations missing')
            for depth,key in enumerate(it['public_observations']):
                held=d['held_fruit_type'] if depth==0 else d['next_fruit_type'] if depth==1 else m['public_spawn_types'][it['chance_slots'][depth-2]]
                nxt=d['next_fruit_type'] if depth==0 else -1 if depth+1==m['max_depth'] else m['public_spawn_types'][it['chance_slots'][depth-1]]
                if key!=f'{held}:{nxt}':raise ValueError('Hidden/public fruit timing mismatch')
    if d['selected_index']>=0:
        c=d['candidates'][d['selected_index']]
        if not c['success'] or m['nodes'][0]['actions'][d['selected_index']]['visits']==0:raise ValueError('Unvisited/invalid candidate selected')
        if c['predicted_game_over'] and not d['all_predicted_terminal']:raise ValueError('Excluded GO selected')
    return dict(completed=n,cap=cap,reason=m['budget_stop_reason'],elapsed_ms=m['elapsed_ms'],overrun_ms=m['time_overrun_ms'],additions=len(m['candidate_additions'] or []),nonroot_additions=sum(a['depth']>0 for a in m['candidate_additions'] or []),physical_ticks=m['total_physics_ticks'])
