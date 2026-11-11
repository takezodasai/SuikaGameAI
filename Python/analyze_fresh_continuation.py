"""Classify observed replay coverage; never promote truncated returns."""
import argparse,json
from pathlib import Path
from run_fresh_continuation import read_rows

def analyze(root):
    root=Path(root);result=[]
    for p in sorted(root.glob('*/result.json')):
        r=json.loads(p.read_text());rows=list(read_rows(p.parent/'trace.jsonl'));ticks=[x for x in rows if x['evt']=='prefix_tick'];actions=[x for x in rows if x['evt']=='action'];end=r['end'];first_wm=next((x['tick'] for x in ticks if x.get('watermelons',0)>0 or any(':9->10' in e for e in x.get('events') or [])),None)
        known=bool(end and end['mc_return_known'] and end['game_over'] and end['prefix_verified'] and not r.get('errors') and not r.get('first_mismatch') and r.get('exit_code',0)==0)
        root_state=r.get('root');cfg=json.loads((p.parent/'config.json').read_text()) if (p.parent/'config.json').exists() else {}
        result.append(dict(folder=p.parent.name,seconds=r['wall_seconds'],end_reason=end['reason'] if end else None,natural_go=end['game_over'] if end else False,known_return=known,return_points=end['score']-root_state['score'] if known and root_state else None,candidate_x=cfg.get('candidate_x'),future_seed=cfg.get('future_seed'),prefix_completed=end['prefix_complete'] if end else False,prefix_verified=end['prefix_verified'] if end else False,completed_actions=end['drops'] if end else None,max_prefix_fruits=max((x['fruit_count'] for x in ticks),default=0),first_watermelon_tick=first_wm,first_mismatch_tick=r['first_mismatch']['tick'] if r['first_mismatch'] else None,checkpoints=[dict(actions=x['drops'],tick=x['tick'],fruit_count=x['fruit_count'],score=x['score'],has_watermelon=any(f['type']==10 for f in x['state']['fruits'])) for x in actions if x['drops'] in [24,48,96,128,168,169,170,200,250,294]],go_candidate_observed=any(x.get('go_candidate',False) for x in ticks)))
    return dict(runs=result,natural_teacher_count=sum(x['known_return'] for x in result),limitation='Reference is a new actual replay of source coordinates, not an exact restoration of the historical game. Only prefix-verified natural continuations qualify as MC labels.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.root)
    with a.output.open('x',encoding='utf8') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
