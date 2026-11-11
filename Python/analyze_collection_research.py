"""Read-only, completed-attempt collection census for the 2026-10-28 research report.

Never launches/stops a Player and never rewrites collection files.
Rates use summed per-game elapsed time (worker-hours), not session throughput.
"""
import argparse
import csv
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    at = (len(values)-1)*q
    lo = int(at)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(at-lo)


def analyze(root):
    started = time.perf_counter()
    # Freeze the completion-file inventory before opening any decision trajectories.
    inventory = sorted(root.glob('overnight*/jobs/job_*/attempt_*_result.json'))
    groups, games, excluded = defaultdict(list), [], []
    for p in inventory:
        try:
            g = json.loads(p.read_text(encoding='utf-8-sig'))
            if not (g.get('natural_go') and g.get('valid_for_return_learning') and not g.get('errors')):
                excluded.append({'path':str(p),'reason':g.get('errors') or g.get('end_reason')})
                continue
            attempt = Path(g['attempt'])
            cfg_path = p.parents[2]/'collection.json'
            cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
            decisions = []
            dp = attempt/'decisions.jsonl'
            if dp.exists():
                with dp.open(encoding='utf-8-sig') as source:
                    decisions = [json.loads(line) for line in source if line.strip()]
            profile = g['profile']
            row = dict(g, result_path=str(p), session=p.parents[2].name,
                       think_seconds=cfg['think_seconds'], workers=cfg['workers'],
                       decision_records=len(decisions))
            games.append(row)
            key=(g['player_sha256'],cfg['think_seconds'],profile['depth'],profile['iterations'])
            groups[key].append((row,decisions))
        except (OSError,ValueError,KeyError) as exc:
            excluded.append({'path':str(p),'reason':repr(exc)})
    summaries=[]
    for key, items in sorted(groups.items()):
        gs=[g for g,_ in items]; ds=[d for _,dd in items for d in dd]
        times=[d['elapsed_ms']/1000 for d in ds]
        actual=[d['actual_iterations'] for d in ds]
        entropies=[]; peak_shares=[]
        for d in ds:
            counts=[a.get('visits',0) for a in (d.get('root_actions') or [])]
            total=sum(counts)
            if total and len(counts)>1:
                ps=[n/total for n in counts]
                entropies.append(-sum(v*math.log(v) for v in ps if v)/math.log(len(ps)))
                peak_shares.append(max(ps))
        worker_hours=sum(g['elapsed_seconds'] for g in gs)/3600
        levels=defaultdict(lambda:defaultdict(int))
        for d in ds:
            for l in d.get('depth_metrics',[]):
                for k in ('nodes','action_visits','revisits','tree_actions','rollout_actions'):
                    levels[l['depth']][k]+=l.get(k,0)
        summaries.append(dict(player_sha256=key[0],think_seconds=key[1],depth=key[2],iterations=key[3],
            games=len(gs), decisions=len(ds), elapsed_worker_hours=worker_hours,
            game_minutes_mean=statistics.mean(g['elapsed_seconds']/60 for g in gs),
            games_per_worker_hour=len(gs)/worker_hours,decisions_per_worker_hour=len(ds)/worker_hours,
            thinking_seconds_mean=statistics.mean(times) if times else None,
            thinking_seconds_median=quantile(times,.5),thinking_seconds_p95=quantile(times,.95),
            actual_iterations_mean=statistics.mean(actual) if actual else None,
            time_limit_fraction=sum(bool(d.get('time_limit_reached')) for d in ds)/len(ds) if ds else None,
            score_mean=statistics.mean(g['final_score'] for g in gs),
            score_median=statistics.median(g['final_score'] for g in gs),
            score_sd=statistics.stdev(g['final_score'] for g in gs) if len(gs)>1 else None,
            score_min=min(g['final_score'] for g in gs),score_max=max(g['final_score'] for g in gs),
            watermelon_games=sum(g.get('watermelon_events',0)>0 for g in gs if g.get('events_known')),
            events_known_games=sum(bool(g.get('events_known')) for g in gs),
            high3000_games=sum(g['final_score']>=3000 for g in gs),
            double_events=sum(g.get('double_events',0) for g in gs if g.get('events_known')),
            root_normalized_entropy=statistics.mean(entropies) if entropies else None,
            root_max_visit_share=statistics.mean(peak_shares) if peak_shares else None,
            depth_totals=dict(levels),sessions=sorted(set(g['session'] for g in gs))))
    return dict(snapshot_utc=datetime.now(timezone.utc).isoformat(),
                inventory_files=len(inventory),completed_games=len(games),excluded=excluded,
                methodology='Completed natural-GO attempts only; completed-game worker-hour rates, censored ongoing games excluded. Profiles/seeds/builds not randomized paired comparisons. No new simulations.',
                summaries=summaries,games=games,analysis_seconds=time.perf_counter()-started)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():
        raise SystemExit('Refusing to overwrite output directory')
    result=analyze(a.root);a.output.mkdir(parents=True)
    (a.output/'collection_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[{k:v for k,v in s.items() if k not in ('depth_totals','sessions')} for s in result['summaries']]
    if rows:
        with (a.output/'profiles.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps({k:result[k] for k in ('snapshot_utc','inventory_files','completed_games','analysis_seconds')},indent=2))
    for s in result['summaries']:
        print(json.dumps({k:v for k,v in s.items() if k not in ('depth_totals','sessions')},ensure_ascii=False))


if __name__=='__main__':
    main()
