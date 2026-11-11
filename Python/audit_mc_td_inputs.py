"""Independent raw-end and temporal-boundary audit; never runs a model."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from mc_td_data import load_restricted

def observed_end(path,episode):
    path=Path(path)
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-1024*1024));lines=f.read().splitlines()
    for line in reversed(lines):
        try:r=json.loads(line)
        except ValueError:continue
        if r.get('event')=='episode_end' and r.get('episode_id')==episode:return r
    with path.open('rb') as f:
        for line in f:
            r=json.loads(line)
            if r.get('event')=='episode_end' and r.get('episode_id')==episode:return r
    raise ValueError('Missing observed end')

def audit(root):
    root=Path(root);m,records,*_=load_restricted(root/'dataset');t=np.load(root/'dataset/temporal.npz');ends=[];phases=Counter();external={e['index']:e for e in m['external_terminals']};count=0
    for ep in m['episodes']:
        end=observed_end(ep['source'],ep['id'].split('|')[-1])
        if end.get('game_over') is not True or end.get('truncated') is not False or end.get('reason')!='game_over' or end.get('conserved') is not True:raise ValueError('Unverified/truncated episode')
        if end['final_score']!=ep['final_score'] or end['state']['score']!=ep['final_score'] or not end['state']['game_over']:raise ValueError('Final-score mismatch')
        phases[end['state'].get('snapshot_phase','unknown')]+=1;ends.append(ep['id'])
    for i,r in enumerate(records):
        if r['game_over']:continue
        j=int(t['next_index'][i]);reward=float(t['reward'][i]);done=bool(t['terminal'][i]);count+=1
        if j<len(records):
            future=records[j]
            if any(future[k]!=r[k] for k in ('episode','group','split','seed')):raise ValueError('Episode/seed/split crossing')
            if done!=future['game_over']:raise ValueError('Wrong terminal bootstrap flag')
            if reward!=future['score']-r['score'] or reward+future['target']!=r['target']:raise ValueError('Dropped/double-counted score')
        else:
            terminal=external[j]
            if not done or terminal['episode']!=r['episode'] or reward!=terminal['score']-r['score'] or reward!=r['target']:raise ValueError('External observed GO not closed correctly')
    result=dict(raw_natural_go_ends_verified=len(ends),temporal_nonterminal_pairs_verified=count,episode_seed_group_split_crossings=0,score_conservation_errors=0,excluded_test_games=m['test_excluded_games'],test_in_tensor_dataset=0,external_observed_go=len(external),terminal_observation_phases=dict(phases),n='3 observed transitions, including actual inter-operation GO closure',bootstrap='zero only at observed GO; no inferred terminal',source_hashes={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ['Python/compare_mc_td_learning.py','Python/mc_td_data.py']})
    with (root/'temporal_audit.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();audit(a.root)
