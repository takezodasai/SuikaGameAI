"""Read-only final analysis after the owned study exits. Never launches a game."""
import argparse,ctypes,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('Python/outputs/frozen_v_pair_12_01')

def write(p,r):
    with Path(p).open('x',encoding='utf8') as f:json.dump(r,f,indent=2,allow_nan=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-pid',type=int,required=True);a=parser.parse_args();h=ctypes.windll.kernel32.OpenProcess(0x100000,False,a.wait_pid)
    if h:
        try:
            while ctypes.windll.kernel32.WaitForSingleObject(h,1000)==258:pass
        finally:ctypes.windll.kernel32.CloseHandle(h)
    with (ROOT/'analysis_final.log').open('x') as f:
        subprocess.run([sys.executable,'Python/analyze_frozen_v_pairs.py'],stdout=f,stderr=subprocess.STDOUT,check=True,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    r=json.loads((ROOT/'analysis_final.json').read_text());plan=json.loads((ROOT/'plan.json').read_text());start=json.loads((ROOT/'execution_start.json').read_text())
    old=json.loads(Path('Python/outputs/mc_td_compare_01/protected.json').read_text());frozen=json.loads(Path('Python/outputs/mc_td_compare_01/frozen_checkpoints.json').read_text())['models'];checkpoints=[e for c in frozen.values() for group in c.values() for e in group]
    collection=json.loads(Path('Python/outputs/overnight_diverse_20261029_012253_922ae62c/collection.json').read_text());base=Path(collection['exe']).parent
    audit=dict(old_sources=len(old),changed_old_sources=[p for p,h in old.items() if sha(p)!=h],frozen_models=len(plan['models']),changed_models=[p for p,h in plan['models'].items() if sha(p)!=h],
        frozen_input_files=len(plan['scoring_files']),changed_input_files=[p for p,h in plan['scoring_files'].items() if sha(p)!=h],old_checkpoints=len(checkpoints),changed_checkpoints=[e['checkpoint'] for e in checkpoints if sha(e['checkpoint'])!=e['checkpoint_sha256']],
        protected_production_files=len(collection['player_files']),changed_production_files=[p for p,h in collection['player_files'].items() if sha(base/p)!=h],preregistered_plan_unchanged=sha(ROOT/'plan.json')==start['plan_sha'])
    write(ROOT/'protection_audit_final.json',audit)
    write(ROOT/'used_development_seeds.json',dict(role='development evaluation, not untouched Test',planned_seeds=plan['seeds'],observed_games=[dict(seed=g['seed'],mode=g['mode'],initial8=g.get('initial8'),natural_go=g['natural_go']) for g in r['games']]))
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        pairs=r['pairs'];fig,axes=plt.subplots(1,2,figsize=(12,6));ys=list(range(len(pairs)))
        for i,p in enumerate(pairs):axes[0].plot([p['heuristic'],p['V']],[i,i],color='#aaaaaa',lw=1)
        axes[0].scatter([p['heuristic'] for p in pairs],ys,label='Heuristic',c='#777777');axes[0].scatter([p['V'] for p in pairs],ys,label='Frozen V',c='#1769aa');axes[0].set_yticks(ys,[str(p['seed']) for p in pairs]);axes[0].set_xlabel('Natural-GO score');axes[0].legend()
        axes[1].barh(ys,[p['difference'] for p in pairs],color=['#1769aa' if p['difference']>0 else '#b24c39' for p in pairs]);axes[1].axvline(0,color='black',lw=.8);axes[1].set_yticks(ys,[str(p['seed']) for p in pairs]);axes[1].set_xlabel('V minus heuristic score');fig.suptitle(f"Frozen V vs heuristic: {len(pairs)} complete development pairs");fig.tight_layout();path=ROOT/'paired_scores.png'
        if path.exists():raise FileExistsError(path)
        fig.savefig(path,dpi=150);plt.close(fig)
    except Exception as e:write(ROOT/'plot_unavailable.json',dict(error=str(e)))
    from collection_concurrency_probe import active_players
    if active_players():write(ROOT/'tests_deferred.json',dict(reason='External Player active, avoid CPU interference'))
    else:
        with (ROOT/'python_tests_final.log').open('x') as f:
            p=subprocess.run([sys.executable,'-m','unittest','discover','-s','Python/tests'],stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        write(ROOT/'test_execution.json',dict(exit_code=p.returncode))
    write(ROOT/'finalization_complete.json',dict(complete=True,observed_games=r['observed_games'],natural_games=r['natural_games'],pairs=len(r['pairs'])))

if __name__=='__main__':main()
