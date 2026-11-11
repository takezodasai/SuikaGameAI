"""Replace only a prefix-rejected root, within the original 900s execution budget."""
import json,time
from pathlib import Path
from qv_experiment import ROOT,VALUE,POLICY,write
from run_fresh_continuation import source_positions,config,run

def main():
    plan=json.loads((ROOT/'plan.json').read_text());inventory=json.loads((ROOT/'branches/inventory.json').read_text());used=inventory['seconds'];budget=plan['branch_budget_seconds']-used
    if len([r for r in inventory['runs'] if r.get('known_return')])>=4:raise ValueError('Do not replace a completed root based on its outcomes')
    pm=json.loads((POLICY/'manifest.json').read_text());present={e['id'] for e in pm['episodes']};vm=json.loads((VALUE/'manifest.json').read_text());excluded={e['group'] for e in plan['branch_roots']}
    e=next(e for e in sorted(vm['episodes'],key=lambda e:(e['group'],e['seed'],e['id'])) if e['split']=='validation' and e['group'] not in excluded and e['id'] in present)
    folder=ROOT/'branches/root_2';folder.mkdir(exist_ok=False);write(folder/'plan.json',dict(source=e,reason='Previous root prefix mismatch; selected next sorted independent Validation group without model predictions',remaining_seconds=budget,future_seed=20261113,candidates=[0.,.37]))
    seed,xs,_=source_positions(e['source']);xs=xs[:24];exe=Path('Unity/Builds/FreshBranch_01/SuikaGameAI.exe');start=time.monotonic();results=[]
    if budget<80:return
    ref=run(config(folder/'reference',seed,xs,seconds=60),exe,42140,80)
    if ref.get('root') and not ref['errors']:
        for x in [0.,.37]:
            remaining=budget-(time.monotonic()-start)
            if remaining<60:break
            cap=min(180,remaining-20);c=config(folder/('x'+str(x).replace('.','p')),seed,xs,folder/'reference/trace.jsonl',True,x,20261113,cap)
            r=run(c,exe,42140,cap+15);results.append(dict(x=x,result=str(c.parent/'result.json'),known_return=bool(r.get('end') and r['end']['mc_return_known'] and not r['first_mismatch'] and not r['errors'])))
            if r['first_mismatch']:break
    write(folder/'inventory.json',dict(prior_seconds=used,seconds=time.monotonic()-start,total_seconds=used+time.monotonic()-start,results=results))

if __name__=='__main__':main()
