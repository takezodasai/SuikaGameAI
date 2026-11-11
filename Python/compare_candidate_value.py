"""Evaluate frozen AC values within a root, not across unrelated games.

Consumes opt-in Unity counterfactual diagnostics. Short continuations are censored
simulator returns, never relabelled as natural-GO or actual counterfactual truth.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.value_data import encode
from suika_ai.long_value_model import geometry_features
from suika_ai.long_value_train import load_trained


def predict(model,kind,snapshot):
    f,g=encode(dict(state=snapshot,geometry=snapshot['geometry']))
    fruit=torch.zeros(1,max(1,len(f)),30);mask=torch.zeros(1,max(1,len(f)),dtype=torch.bool)
    if f:fruit[0,:len(f)]=torch.tensor(f);mask[0,:len(f)]=True
    inputs=[fruit,mask,torch.tensor([g])]
    if kind=='geometry':inputs.append(torch.tensor(geometry_features(f,g)).unsqueeze(0))
    with torch.inference_mode():return float(model(*inputs).item()*1000)


def expected_q(model,kind,row):
    """C is unknown at root. Integrate public slots, never select an action by C.

    The physical afterstate is independent of this undropped preview. A pre-drop
    terminal still has the originally public NEXT; do not invent a new C there.
    """
    state=row['after_first'];reward=row['first']['reward']
    if not row['first']['drop_success'] or state['game_over']:
        q=reward+predict(model,kind,state)
        return q,[dict(next_type=state['next_fruit_type'],probability=1.,q=q)]
    values=[];types=row['public_spawn_types']
    for kind_ in types:
        observation=dict(state,next_fruit_type=kind_)
        values.append(dict(next_type=kind_,probability=1/len(types),q=reward+predict(model,kind,observation)))
    return sum(x['probability']*x['q'] for x in values),values


def heuristic(first,bins=9):
    f=first['evaluation_features'];height=f['go_y']-f['floor_y'];width=f['right_x']-f['left_x'];sky=[0.]*bins
    for fruit in f['fruits']:
        if not fruit['contacted']:continue
        h=max(0,min(1,(fruit['top_y']-f['floor_y'])/height))
        for b in range(bins):
            left=f['left_x']+width*b/bins;right=f['left_x']+width*(b+1)/bins
            if fruit['max_x']>left and fruit['min_x']<right:sky[b]=max(sky[b],h)
    roughness=min(1,2*float(np.std(sky)))
    return first['reward']-11*roughness


def rank_pairs(predicted,returns,tolerance=1e-6):
    correct=tied=total=0
    for i in range(len(returns)):
        for j in range(i):
            delta=returns[i]-returns[j]
            if abs(delta)<=tolerance:continue
            total+=1;p=predicted[i]-predicted[j]
            if abs(p)<=tolerance:tied+=1
            elif p*delta>0:correct+=1
    return dict(comparable_pairs=total,correct=correct,predicted_ties=tied,
                accuracy_with_half_credit_ties=(correct+.5*tied)/total if total else None)


def aggregate(rows):
    groups=defaultdict(list)
    for row in rows:
        if row.get('source')=='prediction_scene' and not row.get('error') and row['repeat']==0:groups[(row['fixture'],row['x'])].append(row)
    result=[]
    for (fixture,x),items in groups.items():
        result.append(dict(fixture=fixture,x=x,future_samples=len(items),q_value=float(np.mean([r['q_value'] for r in items])),
            immediate=float(np.mean([r['first']['reward'] for r in items])),heuristic=float(np.mean([r['heuristic'] for r in items])),
            continuation_mean=float(np.mean([r['total_reward'] for r in items])),continuation_sd=float(np.std([r['total_reward'] for r in items],ddof=1)) if len(items)>1 else None,
            initial_go=any(r['first']['game_over'] for r in items),drop_success=all(r['first']['drop_success'] for r in items),
            future_go_samples=sum(r['game_over'] for r in items),natural_go_verified=False,
            simulated_terminal_samples=sum(r['game_over'] for r in items),completed_actions=[r['completed_actions'] for r in items],
            first_merges=items[0]['first']['merges'],first_ticks=items[0]['first']['physics_steps']))
    return result


def analyze(input_path,model_path):
    torch.set_num_threads(1);model,kind,payload,checkpoint=load_trained(model_path)
    with input_path.open(encoding='utf8') as source:
        rows=[json.loads(x) for x in source if x.strip()]
    valid=[];errors=[];repeats=defaultdict(list);live=[]
    for row in rows:
        if row.get('error'):errors.append(row);continue
        if row['source']=='prediction_scene':
            if row['first']['reward']!=row['after_first']['score']-row['initial']['score']:raise ValueError('Immediate score double-count/mismatch')
            if row['total_reward']!=row['final']['score']-row['initial']['score']:raise ValueError('Continuation score mismatch')
            if not row['root_unchanged'] or not row['random_unchanged']:raise ValueError('Contamination')
            row['value_remaining']=predict(model,kind,row['after_first']);row['q_sampled']=row['first']['reward']+row['value_remaining']
            row['q_value'],row['q_by_public_next_slot']=expected_q(model,kind,row);row['heuristic']=heuristic(row['first'])
            repeats[(row['fixture'],row['seed'],row['x'])].append(row);valid.append(row)
        else:live.append(row)
    repeat_failures=[]
    for key,items in repeats.items():
        signatures={(r['final_signature'],r['total_reward'],r['total_merges'],r['total_ticks'],r['game_over'],tuple(r['continuation_x'])) for r in items}
        if len(signatures)>1:repeat_failures.append(key)
    candidates=aggregate(valid);by_fixture=defaultdict(list)
    for r in candidates:by_fixture[r['fixture']].append(r)
    evaluations=[]
    for fixture,items in by_fixture.items():
        for subset in ('fixed5','with_middle'):
            selected=[r for r in items if subset!='fixed5' or r['x'] in (0,.25,.5,.75,1)]
            safe=[r for r in selected if r['drop_success'] and not r['initial_go']]
            for name in ('q_value','heuristic','immediate'):
                pool=safe or selected
                best=max(pool,key=lambda r:(r[name],-r['x']));truth=max(r['continuation_mean'] for r in pool)
                evaluations.append(dict(fixture=fixture,subset=subset,method=name,safe_candidates=len(safe),selected_x=best['x'],
                    selected_continuation_mean=best['continuation_mean'],estimated_short_horizon_regret=truth-best['continuation_mean'],
                    selected_future_go_samples=best['future_go_samples'],**rank_pairs([r[name] for r in pool],[r['continuation_mean'] for r in pool])))
    return dict(model=str(model_path.resolve()),model_kind=kind,epoch=payload['epoch'],checkpoint=str(checkpoint),
        source_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),prediction_rows=len(valid),errors=errors,repeat_failures=repeat_failures,
        candidates=candidates,evaluations=evaluations,live_comparisons=live,
        limitation='6-drop (configurable) simulated common-stream heuristic-policy returns; no natural-GO long-horizon ranking ground truth; original solver cache/RNG unavailable')


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--model',type=Path,default=Path('outputs/step8ac_01/geometry'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    result=analyze(a.input,a.model)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:result[k] for k in ('model_kind','epoch','prediction_rows','repeat_failures')},ensure_ascii=False))
    for r in result['evaluations']:print(json.dumps(r,ensure_ascii=False))


if __name__=='__main__':main()
