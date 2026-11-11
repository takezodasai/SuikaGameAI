"""One technical retry of same root; repeat original prediction calls in prefix."""
import json,time
from pathlib import Path
import frozen_model_actual_play as play
from frozen_model_actual_play import ROOT,write
from run_fresh_continuation import read_rows
from collection_concurrency_probe import active_players

def main():
    base=ROOT/'branches_parity';base.mkdir(exist_ok=False)
    if active_players():write(base/'blocked.json',dict(reason='Active Player, no launch'));return
    original=json.loads((ROOT/'branches/plan.json').read_text());used=json.loads((ROOT/'branches/summary.json').read_text())['seconds'];budget=600-used
    write(base/'plan.json',dict(**original,remaining_seconds=budget,modification='Replay executes the same five Predict calls and public model shadow evaluations as original Q source before each recorded action; no physical/rule change, no tolerance relaxation, same root/candidates/futures. One retry only.'))
    play.EXE=Path('Unity/Builds/FrozenModels_04/SuikaGameAI.exe');models=play.Models();started=time.monotonic();common=dict(seed=original['seed'],mode='D',reference=str(Path(original['source']).resolve()),prefix_drops=original['prefix_drops'],replay_shadow=True,prefix_mode='B',max_drops=600)
    ref=play.run_game(base/'reference',dict(common,prefix_only=True,max_seconds=70),models,port=44660)
    verified=any(r['evt']=='branch_root' and r['prefix_verified'] for r in read_rows(base/'reference/trace.jsonl'))
    if not verified:
        write(base/'summary.json',dict(prefix_verified=False,reason='Same-call parity retry still failed strict prefix; no teacher and no continuation',reference=ref,seconds=time.monotonic()-started,previous_seconds=used));return
    results=[]
    for future in original['futures']:
        for x in original['candidates']:
            left=budget-(time.monotonic()-started)
            if left<30:break
            folder=base/f'D_f{future}_x{x}';r=play.run_game(folder,dict(common,candidate_x=x,future_seed=future,max_seconds=min(130,left)),models,port=44660)
            root=next((r for r in read_rows(folder/'trace.jsonl') if r['evt']=='branch_root' and r['prefix_verified']),None);valid=bool(root and r['natural_go'] and not r['errors'])
            results.append(dict(future=future,x=x,valid_natural_return=valid,return_points=r['score']-root['score'] if valid else None,root_score=root['score'] if root else None,result=str(folder/'result.json'),seconds=r['wall_seconds']))
    write(base/'summary.json',dict(prefix_verified=True,results=results,seconds=time.monotonic()-started,previous_seconds=used,MCTS_continuation='Not run: matched pair estimated from 767s full MCTS game exceeds remaining 600s branch budget.',note='Heuristic continuation only; no censored/mismatched record is an MC target.'))

if __name__=='__main__':main()
