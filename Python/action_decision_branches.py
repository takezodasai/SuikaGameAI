"""Bounded blind branch returns, fixed models, separate development/evaluation roots."""
import json,time
from pathlib import Path
from action_decision_plan import ROOT,write
from action_decision_models import Models
from run_fresh_continuation import config,run,read_rows
from collection_concurrency_probe import active_players
from suika_ai.collection_audit import initial_sequence

def root_prefix(rootfolder):
    rows=list(read_rows(rootfolder/'reference/trace.jsonl'));start=next(r for r in rows if r['evt']=='start');a=[r for r in rows if r['evt']=='action'];return ','.join(map(str,[start['state']['current_fruit']['type']]+[r['state']['current_fruit']['type'] for r in a[:7]]))

def main():
    base=ROOT/'branches';base.mkdir(exist_ok=False);plan=json.loads((ROOT/'plan.json').read_text());players=active_players()
    if players:write(base/'blocked.json',dict(existing_players=players));return
    models=Models();exe=Path(plan['Player']);start=time.monotonic();inventory=[];roles=[]
    # Inventory exposes only seeds/initial public fruit prefixes to the overlap check.
    registries=[Path('Python/outputs/policy_success_01/dataset/manifest.json'),Path('Python/outputs/step8ac_01/dataset/manifest.json'),Path('Python/outputs/value_reliability_01/dataset/manifest.json'),Path('Python/outputs/qv_compare_01/latest/test_reservation_manifest.json')]
    seeds=set();prefixes=set()
    for p in registries:
        for e in json.loads(p.read_text()).get('episodes',[]):seeds.add(e['seed']);prefixes.add(e.get('initial_sequence'))
    # Newer value Test manifests may omit the prefix. Read only the first eight
    # public held-fruit observations for split auditing, never their outcomes.
    for e in json.loads(Path('Python/outputs/value_reliability_01/dataset/manifest.json').read_text())['episodes']:
        if e['split']!='test':continue
        first=[];n=0
        with Path(e['source']).open() as f:
            for line in f:
                row=json.loads(line);first.append(row)
                if row['event']=='transition':
                    n+=1
                    if n==8:break
        prefixes.add(initial_sequence(first))
    for e in json.loads(Path('Python/outputs/qv_compare_01/latest/inventory.json').read_text())['items']:seeds.add(e['result']['game_seed']);prefixes.add(e['prefix'])
    prefixes.discard(None)
    write(base/'split_registry_audit.json',dict(reserved_seeds=len(seeds),reserved_initial8=len(prefixes),Test_use='Only seed/first8 public fruit split auditing, no model evaluation or fitting'))
    def remaining():return plan['branch_budget_seconds']-(time.monotonic()-start)
    def continuation(name,role,seed,positions,reference,root,futures,past=None):
        folder=base/name;folder.mkdir(exist_ok=True);models.evaluate(folder/'prediction',root)
        roles.append(dict(name=name,role=role,seed=seed,reference=str(reference),past=past,predictions=str(folder/'prediction/predictions.json')))
        for f in futures:
            for x in plan['actual_candidates']:
                if remaining()<45:return
                cap=min(plan['branch_process_cap'],remaining()-10);c=config(folder/f'f{f}_x{str(x).replace(".","p")}',seed,positions,reference,True,x,f,cap)
                r=run(c,exe,44340,cap+8);valid=bool(r.get('end') and r['end']['mc_return_known'] and not r['errors'] and not r['first_mismatch'] and r['exit_code']==0)
                inventory.append(dict(name=name,role=role,seed=seed,future=f,x=x,result=str(c.parent/'result.json'),valid=valid,seconds=r['wall_seconds']))
                if r['first_mismatch']:return
    # Run the reserved branch-evaluation root first, with fixed prediction rules.
    for seed in plan['branch_evaluation']['reserved_seeds']:
        if seed in seeds:raise ValueError('Reserved seed overlaps previous data')
        folder=base/f'evaluation_{seed}';folder.mkdir();positions=plan['branch_evaluation']['prefix_positions'];r=run(config(folder/'reference',seed,positions,seconds=60),exe,44340,68)
        if not r.get('root') or r['errors']:continue
        prefix=root_prefix(folder)
        if prefix in prefixes:write(folder/'quarantined.json',dict(reason='initial8 overlap'));continue
        # Every actual continuation repeats and verifies the prefix itself.
        continuation(folder.name,'branch_evaluation',seed,positions,folder/'reference/trace.jsonl',r['root'],plan['branch_evaluation']['future_seeds'])
        attempts=[v for v in inventory if v['name']==folder.name]
        # Never replace a slow/censored or low-return root with an easier one.
        prefix_failed=bool(attempts) and all(json.loads(Path(v['result']).read_text()).get('first_mismatch') for v in attempts)
        if not prefix_failed:break
    for e in plan['development']:
        if remaining()<60:break
        ref=Path(e['reference']);rr=[r for r in read_rows(ref) if r['evt']=='root'];root=rr[-1]
        continuation(e['name'],'development',e['seed'],e['config']['positions'],ref,root,[e['new_future']],e['past'])
    write(base/'inventory.json',dict(seconds=time.monotonic()-start,budget_seconds=plan['branch_budget_seconds'],runs=inventory,roots=roles))

if __name__=='__main__':main()
