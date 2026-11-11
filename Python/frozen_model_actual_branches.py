"""Small, predeclared model-proposed action experiment, fresh native prefixes only."""
import json,time
from pathlib import Path
from frozen_model_actual_play import ROOT,Models,run_game,write
from run_fresh_continuation import read_rows

def main():
    base=ROOT/'branches';base.mkdir(exist_ok=False)
    # First eligible disagreement by temporal order, not by its later score/return.
    source=ROOT/'seed_882610501'/'B';candidates=[]
    for p in sorted((source/'bridge').glob('prediction_*.json')):
        r=json.loads(p.read_text());xs=sorted(set(r['choices'].values()))
        if r['id']>=25 and r['choices']['B']!=r['choices']['C']:
            candidates=xs;turn=r['id'];break
    if not candidates:write(base/'skipped.json',dict(reason='No eligible model disagreement'));return
    # At most two actual proposals, deterministic policy order, not return selection.
    selected=[]
    for mode in ['B','C']:
        x=r['choices'][mode]
        if x not in selected:selected.append(x)
    selected=selected[:2];models=Models();started=time.monotonic();cap=600
    plan=dict(source=str(source/'trace.jsonl'),seed=882610501,prefix_drops=turn-1,choices=r['choices'],candidates=selected,futures=[20261301,20261302],budget_seconds=cap,process_cap_seconds=155,
        rule='First Q/V disagreement at decision >=25; distinct actual Q/V proposals in policy order. No outcomes used. Heuristic shadow tie-breaking is only diagnostic and not a branch action proposal. Heuristic common continuation first. MCTS pair only if both fit remaining budget using measured A game cost estimate.',
        test19_used=False)
    write(base/'plan.json',plan)
    reference=run_game(base/'reference',dict(seed=plan['seed'],mode='D',reference=str(Path(plan['source']).resolve()),prefix_drops=plan['prefix_drops'],prefix_only=True,max_seconds=70,max_drops=600),models,port=44620)
    rows=list(read_rows(base/'reference/trace.jsonl'));verified=any(x['evt']=='branch_root' and x['prefix_verified'] for x in rows)
    if not verified:
        write(base/'summary.json',dict(prefix_verified=False,reason='Strict prefix mismatch: no return collection',reference=reference,seconds=time.monotonic()-started));return
    results=[]
    for future in plan['futures']:
        for x in selected:
            left=cap-(time.monotonic()-started)
            if left<30:break
            folder=base/f'D_f{future}_x{x}'
            result=run_game(folder,dict(seed=plan['seed'],mode='D',reference=str(Path(plan['source']).resolve()),prefix_drops=plan['prefix_drops'],candidate_x=x,future_seed=future,max_seconds=min(155,left),max_drops=600),models,port=44620)
            root=next((r for r in read_rows(folder/'trace.jsonl') if r['evt']=='branch_root' and r['prefix_verified']),None)
            valid=bool(root and result['natural_go'] and not result['errors'])
            results.append(dict(policy='D',future=future,x=x,valid_natural_return=valid,return_points=result['score']-root['score'] if valid else None,result=str(folder/'result.json'),seconds=result['wall_seconds']))
    # A full MCTS continuation pair can be much costlier. Do not spend remaining
    # budget on just one candidate and pretend it is a policy comparison.
    a_path=ROOT/'seed_882610501/A/result.json';left=cap-(time.monotonic()-started)
    estimate=json.loads(a_path.read_text())['wall_seconds']*2 if a_path.exists() else float('inf')
    mcts_note='MCTS pair skipped: measured full-game cost for two continuations exceeds remaining branch budget.'
    if left>estimate+30 and estimate<500:
        for x in selected:
            folder=base/f'A_f{plan["futures"][0]}_x{x}'
            result=run_game(folder,dict(seed=plan['seed'],mode='A',reference=str(Path(plan['source']).resolve()),prefix_drops=plan['prefix_drops'],candidate_x=x,future_seed=plan['futures'][0],max_seconds=min(280,cap-(time.monotonic()-started)),max_drops=600),models,port=44620)
            root=next((r for r in read_rows(folder/'trace.jsonl') if r['evt']=='branch_root' and r['prefix_verified']),None);valid=bool(root and result['natural_go'] and not result['errors'])
            results.append(dict(policy='A',future=plan['futures'][0],x=x,valid_natural_return=valid,return_points=result['score']-root['score'] if valid else None,result=str(folder/'result.json'),seconds=result['wall_seconds']))
        mcts_note='Attempted matched MCTS pair; only natural verified returns are labels.'
    write(base/'summary.json',dict(prefix_verified=True,results=results,seconds=time.monotonic()-started,mcts=mcts_note,note='Development root, fixed continuation policy results, not optimal-action truth. No censored or mismatch returns are MC labels.'))

if __name__=='__main__':main()
