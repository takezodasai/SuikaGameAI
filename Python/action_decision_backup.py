"""Technical-prefix fallback only, sharing the original total simulation budget."""
import json,time
from pathlib import Path
from action_decision_plan import ROOT,write
from action_decision_models import Models
from run_fresh_continuation import config,run,read_rows
from action_decision_branches import root_prefix
from collection_concurrency_probe import active_players
from suika_ai.collection_audit import initial_sequence

def main():
    plan=json.loads((ROOT/'plan.json').read_text());base=ROOT/'branches';inv=json.loads((base/'inventory.json').read_text());used=inv['seconds'];remaining=plan['branch_budget_seconds']-used
    failed=any(json.loads(Path(v['result']).read_text()).get('first_mismatch') for v in inv['runs'] if v['role']=='branch_evaluation')
    amendment=dict(reason='Any prefix failure disqualifies the first reserved evaluation root from a paired final diagnosis; fallback depends on technical reproducibility only, never its score',used_seconds=used,remaining_seconds=remaining)
    write(base/'fallback_rule.json',amendment)
    if not failed or remaining<270 or active_players():write(base/'backup_inventory.json',dict(skipped=True,total_seconds=used,runs=[],roots=[]));return
    seed=plan['branch_evaluation']['reserved_seeds'][1];folder=base/f'evaluation_{seed}';folder.mkdir(exist_ok=False);start=time.monotonic();models=Models();exe=Path(plan['Player']);positions=plan['branch_evaluation']['prefix_positions'];runs=[];roles=[]
    r=run(config(folder/'reference',seed,positions,seconds=60),exe,44340,68)
    if r.get('root') and not r['errors']:
        prefix=root_prefix(folder);reserved=set();reserved_seeds=set()
        paths=['Python/outputs/policy_success_01/dataset/manifest.json','Python/outputs/step8ac_01/dataset/manifest.json','Python/outputs/value_reliability_01/dataset/manifest.json','Python/outputs/qv_compare_01/latest/test_reservation_manifest.json']
        for p in paths:
            for e in json.loads(Path(p).read_text()).get('episodes',[]):
                reserved.add(e.get('initial_sequence'));reserved_seeds.add(e['seed'])
                if e.get('split')=='test' and not e.get('initial_sequence') and e.get('source'):
                    rows=[];n=0
                    with Path(e['source']).open() as f:
                        for line in f:
                            v=json.loads(line);rows.append(v)
                            if v['event']=='transition':
                                n+=1
                                if n==8:break
                    reserved.add(initial_sequence(rows))
        for e in json.loads(Path('Python/outputs/qv_compare_01/latest/inventory.json').read_text())['items']:reserved.add(e['prefix']);reserved_seeds.add(e['result']['game_seed'])
        if seed in reserved_seeds or prefix in reserved:write(folder/'quarantined.json',dict(reason='seed/initial8 overlap'))
        else:
            models.evaluate(folder/'prediction',r['root']);roles.append(dict(name=folder.name,role='branch_evaluation_backup',seed=seed,reference=str(folder/'reference/trace.jsonl'),past=None,predictions=str(folder/'prediction/predictions.json')))
            for future in plan['branch_evaluation']['future_seeds']:
                left=remaining-(time.monotonic()-start)
                if left<100:break
                cap=min(180,(left-20)/2)
                for x in plan['actual_candidates']:
                    c=config(folder/f'f{future}_x{str(x).replace(".","p")}',seed,positions,folder/'reference/trace.jsonl',True,x,future,cap)
                    rr=run(c,exe,44340,cap+8);valid=bool(rr.get('end') and rr['end']['mc_return_known'] and not rr['errors'] and not rr['first_mismatch'] and rr['exit_code']==0)
                    runs.append(dict(name=folder.name,role='branch_evaluation_backup',seed=seed,future=future,x=x,result=str(c.parent/'result.json'),valid=valid,seconds=rr['wall_seconds']))
                    if rr['first_mismatch']:break
                if any(json.loads(Path(v['result']).read_text()).get('first_mismatch') for v in runs):break
    write(base/'backup_inventory.json',dict(seconds=time.monotonic()-start,total_seconds=used+time.monotonic()-start,runs=runs,roots=roles))

if __name__=='__main__':main()
