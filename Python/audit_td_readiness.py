"""Check temporal targets without training or touching Test data.

Some complete games ended between operations: their packed MC states omit a
terminal. Recover only observed natural-GO snapshots from the original log.
"""
import argparse,json,hashlib
from pathlib import Path
from collections import defaultdict
from suika_ai.temporal_value_targets import n_step_pairs

def audit(dataset,output):
    dataset=Path(dataset);output=Path(output);output.mkdir(exist_ok=False)
    manifest=json.loads((dataset/'manifest.json').read_text());records=[json.loads(x) for x in (dataset/'records.jsonl').read_text().splitlines()];original_count=len(records)
    groups=defaultdict(list)
    for i,r in enumerate(records):
        if r['split'] in ('train','validation'):groups[r['episode']].append(i)
    extra=[]
    for episode,ids in groups.items():
        if records[ids[-1]]['game_over']:continue
        e=next(e for e in manifest['episodes'] if e['id']==episode);source=Path(e['source']);terminal=None;hash_=hashlib.sha256()
        with source.open('rb') as f:
            for line in f:
                hash_.update(line);row=json.loads(line)
                if row.get('event')=='episode_end' and row.get('episode_id')==episode.split('|')[-1]:terminal=row
        if not terminal or not terminal.get('game_over') or terminal.get('truncated') or terminal.get('reason')!='game_over':raise ValueError('No actual natural terminal; never infer one')
        state=terminal['state']
        if not state['game_over'] or state['score']!=terminal['final_score'] or state['score']!=records[ids[-1]]['score']+records[ids[-1]]['target']:raise ValueError('Terminal score mismatch')
        r=dict(records[ids[-1]],score=state['score'],target=0,game_over=True,source_event='episode_end')
        idx=len(records);records.append(r);ids.append(idx)
        extra.append(dict(index=idx,episode=episode,seed=e['seed'],split=e['split'],score=state['score'],tail_reward=state['score']-records[ids[-2]]['score'],source=str(source),source_sha256=hash_.hexdigest(),state=state))
    horizons={}
    for n in [1,3,5]:
        summary={}
        for split in ['train','validation']:
            pairs=[]
            for ids in groups.values():
                if records[ids[0]]['split']==split:pairs+=n_step_pairs(records,ids,n,natural_go=True)
            summary[split]=dict(pairs=len(pairs),terminal_targets=sum(p['terminal'] for p in pairs),external_terminal_targets=sum(p['bootstrap_index']>=original_count for p in pairs),nonzero_reward_fraction=sum(p['score_delta']>0 for p in pairs)/len(pairs),mean_score_delta=sum(p['score_delta'] for p in pairs)/len(pairs))
        horizons[str(n)]=summary
    with (output/'observed_terminals.jsonl').open('x',encoding='utf8') as f:
        for r in extra:f.write(json.dumps(r)+'\n')
    result=dict(original_states=original_count,recovered_observed_terminals=len(extra),terminal_seeds=[e['seed'] for e in extra],horizons=horizons,test_used=False,trained=False,interpretation='Reward differences include between-operation score. Horizon is observed state transitions, not seconds. External terminals are observed episode_end states, never fabricated.')
    with (output/'readiness.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.dataset,a.output)
