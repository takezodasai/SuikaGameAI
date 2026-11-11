"""Immutable planning only; no training, gameplay, or old file writes."""
import hashlib,json
from pathlib import Path
from suika_ai.long_value_train import load_trained

ROOT=Path('Python/outputs/action_decision_validation_01')

def write(path,value):
    with Path(path).open('x',encoding='utf8') as f:json.dump(value,f,indent=2)

def main():
    ROOT.mkdir(exist_ok=False);base=Path('Python/outputs/qv_compare_01');models=[]
    for kind in ['Q','V']:
        for seed in [20261101,20261102,20261103]:models.append(base/f'latest_models/{kind}_{seed}/best.pt')
    _,_,_,p=load_trained(Path('Python/outputs/step8ac_01/geometry'));models.append(p)
    old=json.loads((base/'branches/root_0/reference/config.json').read_text());old2=json.loads((base/'branches/root_2/reference/config.json').read_text())
    plan=dict(models={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in models},ensemble='Arithmetic mean of three original training seeds, fixed; no new model selection',
      Player='Unity/Builds/FreshBranch_01/SuikaGameAI.exe',collection_Player='Unity/Builds/SyncOptimized_03/SuikaGameAI.exe',
      branch_budget_seconds=1200,branch_process_cap=180,actual_candidates=[0.,.37],prediction_candidates=[0.,.25,.37,.5,.75,1.],q_scan_step=.005,
      development=[dict(name='dev_761110',seed=old['seed'],config=old,reference=str(base/'branches/root_0/reference/trace.jsonl'),past=str(base/'branches/root_0'),new_future=20261211),dict(name='dev_761107',seed=old2['seed'],config=old2,reference=str(base/'branches/root_2/reference/trace.jsonl'),past=str(base/'branches/root_2'),new_future=20261213)],
      branch_evaluation=dict(reserved_seeds=[882610391,882610392],prefix_positions=old['positions'],prefix=24,future_seeds=[20261221,20261222],rule='First reproducible seed with no training/validation/Test seed or initial8 overlap; fallback only on prefix/split failure, never returns'),
      continuation='Existing heuristic5, post-drop25, no neural model; future seeds known only to experiment runner',
      holdout='New branch-only evaluation roots separate from development; not final game-strength Test. Existing Test19 not evaluated.',
      benchmark=dict(budget_seconds=480,phase_cap_seconds=240,game_cap_seconds=90,seeds=[892610401,892610402,892610403,892610404],drops=24,iterations=256,depth=4,think_seconds=30,timeout=720,order=[2,4],architecture='one two-worker supervisor then two two-worker supervisors; same four seeds each phase'),
      interpretation='Only observed two-candidate ranking/regret evaluated; full-six winner unobserved. Few roots cannot establish strength. No retraining or tuning on new branches.')
    for path in [Path(plan['Player']),Path(plan['collection_Player'])]:plan.setdefault('player_sha256',{})[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    write(ROOT/'plan.json',plan)

if __name__=='__main__':main()
