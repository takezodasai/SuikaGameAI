"""Optional model-disagreement query, explicitly exploratory, same total budget."""
import json,time
from collections import Counter
from pathlib import Path
from action_decision_plan import ROOT,write
from run_fresh_continuation import config,run
from collection_concurrency_probe import active_players

def main():
    plan=json.loads((ROOT/'plan.json').read_text());base=ROOT/'branches';inv=json.loads((base/'backup_inventory.json').read_text());used=inv['total_seconds'];left=plan['branch_budget_seconds']-used
    roles=inv.get('roots',[])
    if left<90 or not roles or active_players():write(base/'proposal_inventory.json',dict(skipped=True,total_seconds=used));return
    role=roles[0];folder=base/role['name'];pred=json.loads(Path(role['predictions']).read_text());votes=Counter(x for x in pred['selected_full'].values() if x is not None and x not in plan['actual_candidates'])
    if not votes:write(base/'proposal_inventory.json',dict(skipped=True,total_seconds=used));return
    # Highest number of frozen method proposals; ties by numeric coordinate.
    x=sorted(votes,key=lambda x:(-votes[x],x))[0];future=min(plan['branch_evaluation']['future_seeds'])
    write(base/'proposal_rule.json',dict(role='exploratory only, excluded from primary heldout metrics',remaining_seconds=left,used_seconds=used,rule='Most votes among unobserved full-six method choices, smallest planned future; no outcome-based coordinate choice',votes=dict(votes),x=x,future=future))
    cfg=json.loads((folder/'reference/config.json').read_text());start=time.monotonic();cap=min(180,left-10)
    p=config(folder/f'proposal_f{future}_x{str(x).replace(".","p")}',cfg['seed'],cfg['positions'],folder/'reference/trace.jsonl',True,x,future,cap)
    r=run(p,Path(plan['Player']),44340,cap+8)
    write(base/'proposal_inventory.json',dict(skipped=False,x=x,future=future,result=str(p.parent/'result.json'),seconds=time.monotonic()-start,total_seconds=used+time.monotonic()-start,primary_evaluation=False))

if __name__=='__main__':main()
