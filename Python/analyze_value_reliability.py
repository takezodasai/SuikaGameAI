"""Read-only analysis of frozen physics and value experiments; no model selection."""
import argparse,json,hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np
import torch
from torch import nn
from value_reliability_train import RiskValueNetwork
from suika_ai.long_value_model import GeometryValueNetwork
from suika_ai.value_checkpoint import load_checkpoint
from compare_candidate_value import expected_q,heuristic,rank_pairs

def read(path):return [json.loads(x) for x in Path(path).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def physical(snapshot):
    # Runtime observation IDs differ between processes; they are not physical state.
    return {k:sorted([{a:b for a,b in f.items() if a!='id'} for f in v],key=lambda f:(f['type'],f['x'],f['y'])) if k=='fruits' else v for k,v in snapshot.items()}
def analyze_physics(root):
    rows=read(root/'physics_on/audit.jsonl');groups=defaultdict(list)
    for r in rows:groups[r['label']].append(r)
    output=[]
    for name,rs in groups.items():
        safe=[r for r in rs if r['actual_drop'] and not r['actual_go']];predsafe=[r for r in rs if r['predicted']['drop_success'] and not r['predicted']['game_over']]
        a=max(safe or rs,key=lambda r:(r['actual_heuristic'],-r['x']));p=max(predsafe or rs,key=lambda r:(r['predicted_heuristic'],-r['x']))
        errors=[e for r in rs for e in r['comparison']['errors']]
        output.append(dict(label=name,source=rs[0]['source'],rows=len(rs),predicted_best=p['x'],actual_best=a['x'],
            actual_heuristic_regret=a['actual_heuristic']-p['actual_heuristic'],
            heuristic_rank=rank_pairs([r['predicted_heuristic'] for r in rs],[r['actual_heuristic'] for r in rs]),
            score_mismatches=sum(r['predicted']['reward']!=r['actual_score']-r['initial']['score'] for r in rs),
            merge_mismatches=sum(r['predicted']['merges']!=r['actual_merges'] for r in rs),go_mismatches=sum(r['predicted']['game_over']!=r['actual_go'] for r in rs),
            max_position_error=max(e['position'] for e in errors),max_velocity_error=max(e['velocity'] for e in errors),
            first_tolerance_ticks=[r['comparison']['first_tolerance_tick'] for r in rs],
            first_contact_ticks=[next((e['tick'] for e in r['comparison']['errors'] if not e['contacts_match']),None) for r in rs],
            initial_kinematics_match=all(not any(e['position'] or e['velocity'] or e['angle'] or e['angular_velocity'] for e in r['comparison']['errors'][:1]) for r in rs),
            initial_mass_match=all(not any(e['mass'] or e['inertia'] or e['center_of_mass'] for e in r['comparison']['errors'][:1]) for r in rs),
            mass_first_ticks=[next((e['tick'] for e in r['comparison']['errors'] if e['mass']>1e-6 or e['inertia']>1e-6 or e['center_of_mass']>1e-6),None) for r in rs],
            mcts_prediction_agreement=sum(r['mcts_first_agrees'] for r in rs),
            tick_agreement=all(r['actual_ticks']==r['predicted']['physics_steps'] and r['actual_drop_tick']==r['predicted']['drop_tick'] for r in rs),
            actual_rewards=[r['actual_score']-r['initial']['score'] for r in rs]))
    observed=read(root/'parity_on_02/audit.jsonl');off=read(root/'parity_off_02/audit.jsonl');control=read(root/'parity_off_repeat_02/audit.jsonl');parity=[]
    for r in off:
        on=next(x for x in observed if (x['label'],x['x'])==(r['label'],r['x']));again=next(x for x in control if (x['label'],x['x'])==(r['label'],r['x']))
        parity.append(dict(label=r['label'],x=r['x'],initial_equal=physical(on['initial'])==physical(r['initial']),after_equal=physical(on['actual_after'])==physical(r['actual_after']),off_off_after_equal=physical(again['actual_after'])==physical(r['actual_after']),score_go_ticks_merges_equal=all(on[k]==r[k] for k in ['actual_score','actual_go','actual_ticks','actual_merges'])))
    return dict(cases=output,observation_on_off=parity,limitation='Heuristic argmax disagreement is not proof of a different long-horizon optimal action; reconstructed fixtures and natural prefix are separate cohorts.')

class ScoreOnly(nn.Module):
    def __init__(self,model):super().__init__();self.model=model
    def forward(self,*args):return self.model(*args)[0]

def candidate_comparison(root):
    rows=[r for r in read('Python/outputs/candidate_value_02/branches.jsonl') if r.get('source')=='prediction_scene' and r.get('repeat')==0 and not r.get('error')]
    output={};torch.set_num_threads(1)
    for variant in ['A','B','C']:
        payload,path=load_checkpoint(root/variant/'checkpoints','best');model=RiskValueNetwork() if variant=='C' else GeometryValueNetwork();model.load_state_dict(payload['model']);model.eval()
        if variant=='C':model=ScoreOnly(model)
        groups=defaultdict(list)
        for r in rows:
            q,_=expected_q(model,'geometry',r);groups[(r['fixture'],r['x'])].append((q,r['total_reward'],heuristic(r['first']),r['first']['game_over']))
        byroot=defaultdict(list)
        for (fixture,x),v in groups.items():byroot[fixture].append(dict(x=x,q=float(np.mean([a[0] for a in v])),short_return=float(np.mean([a[1] for a in v])),heuristic=v[0][2],go=v[0][3]))
        details=[]
        for fixture,candidates in byroot.items():
            pool=[c for c in candidates if not c['go']] or candidates;best=max(pool,key=lambda c:(c['q'],-c['x']));h=max(pool,key=lambda c:(c['heuristic'],-c['x']));truth=max(c['short_return'] for c in pool)
            details.append(dict(fixture=fixture,selected_x=best['x'],heuristic_x=h['x'],short_return_regret=truth-best['short_return'],heuristic_short_return_regret=truth-h['short_return'],**rank_pairs([c['q'] for c in pool],[c['short_return'] for c in pool])))
        n=sum(d['comparable_pairs'] for d in details);correct=sum(d['correct']+.5*d['predicted_ties'] for d in details)
        output[variant]=dict(checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),details=details,pairs=n,accuracy=correct/n if n else None,mean_short_regret=float(np.mean([d['short_return_regret'] for d in details])))
    return dict(variants=output,limitation='Exploratory 6-drop prediction-scene continuation targets from a previous diagnostic. Not natural-GO labels, not independent game evidence, no D training or model selection.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args();result=dict(physics=analyze_physics(a.root),candidate_values=candidate_comparison(a.root))
    with (a.output or a.root/'reliability_analysis.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
