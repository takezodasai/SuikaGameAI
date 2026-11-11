"""Summarize actual continuations without turning cold fixtures into exact branches."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from watermelon_lab import sha, write, public_difference


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.output
    plan=json.loads((root/'plan.json').read_text());games=[];roots={}
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'result.json').exists():continue
        r=json.loads((folder/'result.json').read_text());cfg=json.loads((folder/'config.json').read_text())
        rows=[json.loads(l) for l in (folder/'trace.jsonl').read_text().splitlines()] if (folder/'trace.jsonl').exists() else []
        end=r.get('end');start=r.get('root');decisions=[x for x in rows if x['evt']=='decision']
        item=dict(run=folder.name,fixture=cfg['fixture'],future_seed=cfg['future_seed'],first_x=cfg['first_x'],iterations=cfg['iterations'],depth=cfg['depth'],
                  natural_go=r['natural_go'],process_error=r['process_error'],exit_code=r['exit_code'],
                  historical_exact=False,mean_decision_ms=statistics.mean(x['planning_ms'] for x in decisions) if decisions else None,
                  decisions=len(decisions),wall_seconds=r['wall_seconds'])
        if end:
            for k in ['reason','initial_score','score','additional_score','accepted_drops','completed_actions','initial_watermelons','new_watermelons','second_watermelon_generated','two_watermelons_present','double_watermelons','elapsed_seconds','retained_scenes','pending_unloads']:
                item[k]=end[k]
            item['allocated_mb_start']=start['allocated_bytes']/1024**2
            item['allocated_mb_end']=end['allocated_bytes']/1024**2
            item['score_conserved']=all(x['additional_score']==x['score']-x['initial_score'] for x in rows)
            item['relative_tick_consistent']=all(x['command']['completion_tick']-x['command']['drop_tick']==25 for x in rows if x['evt']=='action')
            item['selected_coordinate_consistent']=all(x['command']['x']==x['planning']['selected_x'] or x['command']['forced'] for x in decisions)
        else:item['reason']='failed_or_interrupted_no_end'
        games.append(item)
        if start:roots[folder.name]=(cfg,start)
    comparisons=[]
    for name,(cfg,r) in roots.items():
        for other,(c,s) in roots.items():
            if name>=other or cfg['fixture']!=c['fixture'] or cfg['future_seed']!=c['future_seed']:continue
            d=public_difference(r['state'],s['state'])
            comparisons.append(dict(a=name,b=other,public_difference=d,rng_equal=r['rng']==s['rng'],
                                    same_native_root_guaranteed=False,strict_candidate_ranking_teacher=False))
    allowed={'watermelon_lab.py','SuikaWatermelonLab.cs','SuikaWatermelonLabBuild.cs','test_watermelon_lab.py'}
    changed=[f for f,h in plan['sources_protected'].items() if Path(f).name not in allowed and sha(f)!=h]
    protected=dict(checked_existing_sources=sum(Path(f).name not in allowed for f in plan['sources_protected']),changed_existing_sources=changed,
                   source_logs=[dict(path=x['source'],unchanged=sha(x['source'])==x['source_sha256']) for x in plan['inventory'] if x['stage']=='after'])
    write(root/'analysis.json',dict(games=games,root_comparisons=comparisons,protection=protected,
         caveat='Natural-GO returns are real for these approximate experimental trajectories, not exact historical-game counterfactual labels; truncated returns are lower-horizon observations only.'))
    keys=list(dict.fromkeys(k for g in games for k in g))
    with (root/'analysis.csv').open('x',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(games)
    print(json.dumps(dict(games=games,root_comparisons=comparisons,protection=protected),ensure_ascii=False),flush=True)
    if changed or any(not x['unchanged'] for x in protected['source_logs']):raise RuntimeError('Protected source changed')


if __name__=='__main__':main()
