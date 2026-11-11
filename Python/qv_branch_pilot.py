"""Two frozen independent Validation roots, two actions, one common future each; 900s cap."""
import json,time,hashlib
from pathlib import Path
from run_fresh_continuation import source_positions,config,run
from qv_experiment import ROOT,write

def main():
    plan=json.loads((ROOT/'plan.json').read_text());base=ROOT/'branches';base.mkdir(exist_ok=False)
    exe=Path('Unity/Builds/FreshBranch_01/SuikaGameAI.exe');start=time.monotonic();inventory=[]
    write(base/'execution_plan.json',dict(budget_seconds=plan['branch_budget_seconds'],exe=str(exe.resolve()),sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),roots=plan['branch_roots'],prefix=24,x=plan['candidate_x'],future_seeds=plan['future_seeds']))
    for ri,e in enumerate(plan['branch_roots']):
        folder=base/f'root_{ri}';folder.mkdir();seed,xs,_=source_positions(e['source']);xs=xs[:24]
        if len(xs)<24 or time.monotonic()-start>plan['branch_budget_seconds']-60:break
        c=config(folder/'reference',seed,xs,seconds=60);ref=run(c,exe,port=42140,timeout=80)
        if not ref.get('root') or ref['errors']:
            inventory.append(dict(root=ri,source=e,excluded='Reference not completed'));continue
        for x in plan['candidate_x']:
            remaining=plan['branch_budget_seconds']-(time.monotonic()-start)
            if remaining<60:break
            cap=min(plan['branch_process_cap_seconds'],remaining-20)
            c=config(folder/('x'+str(x).replace('.','p')),seed,xs,folder/'reference/trace.jsonl',True,x,plan['future_seeds'][ri],cap)
            r=run(c,exe,port=42140,timeout=cap+15);inventory.append(dict(root=ri,source=e,x=x,future_seed=plan['future_seeds'][ri],path=str(c.parent),known_return=bool(r.get('end') and r['end']['mc_return_known'] and not r['errors'] and not r['first_mismatch']),seconds=r['wall_seconds']))
            if r['first_mismatch']:break
    write(base/'inventory.json',dict(seconds=time.monotonic()-start,runs=inventory))

if __name__=='__main__':main()
