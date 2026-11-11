"""Validate fresh-process common prefixes and label ONLY observed short returns."""
import argparse,json
from pathlib import Path
from collections import defaultdict
from analyze_action_replay import compare_ticks

def load(folder):
    ticks={};end=None
    with (folder/'ticks.jsonl').open() as f:
        for line in f:
            if not line.endswith('\n'):raise ValueError('Incomplete active output')
            r=json.loads(line)
            if r['evt']=='tick':ticks[r['tick']]=r
            elif r['evt']=='end':end=r
            elif r['evt']=='error':raise ValueError(r['error'])
    if end is None:raise ValueError('No complete diagnostic result')
    return json.loads((folder/'config.json').read_text()),ticks,end

def analyze(root):
    root=Path(root);groups=defaultdict(list)
    for p in sorted(root.iterdir()):
        if p.is_dir():
            c,t,e=load(p);groups[c['seeds'][0]].append((p,c,t,e))
    results=[]
    for seed,runs in groups.items():
        p,c,t,e=runs[0];turn=c['branch_turn'];root_tick=e['commands'][turn-2]['completion_tick'];baseline=t[root_tick]
        reference_future=[t[x['completion_tick']]['state']['next_fruit_type'] for x in e['commands'][turn-1:]]
        candidates=[]
        for folder,cfg,rows,end in runs:
            if cfg['branch_turn']!=turn or end['commands'][:turn-1]!=e['commands'][:turn-1]:raise ValueError('Different prefix commands')
            errors=[compare_ticks(t[i],rows[i]) for i in range(1,root_tick+1)]
            # Stronger than tolerance: these prefixes must be numerically equal too.
            exact=all(v['within_tolerance'] and all(v[k]==0 for k in ['position','velocity','angle','omega','mass','inertia','com','fixed_time_error']) and v['callback_order'] and v['full_body_ids'] for v in errors)
            future=[rows[x['completion_tick']]['state']['next_fruit_type'] for x in end['commands'][turn-1:]]
            if not exact or future!=reference_future:raise ValueError('Prefix/future alignment failed; do not make candidate labels')
            candidates.append(dict(normalized_x=cfg['branch_x'],applied_x=end['commands'][turn-1]['applied_x'],source='actual_game',root_score=baseline['state']['score'],observed_end_score=end['state']['score'],observed_additional_points=end['state']['score']-baseline['state']['score'],completed_drops=len(end['commands'])-turn+1,elapsed_physics_ticks=end['tick']-root_tick,go=end['state']['game_over'],truncated=end['truncated'],mc_return_known=False,return_kind='censored_four_drop_actual_return',prefix_exact=True,folder=str(folder),wall_seconds=json.loads((folder/'execution.json').read_text())['seconds']))
        results.append(dict(seed_group=seed,branch_turn=turn,root_tick=root_tick,root_score=baseline['state']['score'],held=baseline['state']['current_fruit']['type'],public_next=baseline['state']['next_fruit_type'],future_streams=1,future_types_after_each_drop=reference_future,continuation='fixed public-agnostic coordinates [0,1,0.37] after candidate; no future RNG reads by actor',candidates=candidates,uncertainty='One future stream per root: within-root chance uncertainty/95% CI cannot be estimated. Not optimal-action or natural-GO labels.'))
    return dict(roots=results,natural_go_training_samples=0,model_training=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.input)
    with a.output.open('x',encoding='utf8') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
