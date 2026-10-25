"""Offline STEP8-T native probe audit. Never launches or changes games."""
import argparse,json,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from adaptive_profiles import audit_decision
from compare_mcts_budget import save

def load(path):return [json.loads(l) for l in Path(path).read_text(encoding='utf-8-sig').splitlines()]
def physics(it):return {k:it[k] for k in ['actions','chance_slots','reward','merges','game_over','depth','ticks','simulated_ticks','cached_leaf','leaf_points','total_points']}
def analyze(rows):
    summaries=[];checks=[]
    for r in rows:
        if r['error']:
            if r['name']!='zero_time' or 'completed_iterations=0; no drop' not in r['error']:raise ValueError(r['error'])
            summaries.append(dict(fixture=Path(r['fixture']).stem,name=r['name'],completed=0,expected_no_drop=True));continue
        d=dict(r['decision'],mcts=r['report']);a=audit_decision(d);m=r['report'];a.update(fixture=Path(r['fixture']).stem,name=r['name'],selected_x=d['selected_x'],root_visits=[v['visits'] for v in m['nodes'][0]['actions']],root_means=[v['mean_points'] for v in m['nodes'][0]['actions']],root_positions=[v['x'] for v in m['nodes'][0]['actions']],max_predicted_reward=max(i['reward'] for i in m['iterations']),max_merges=max(i['merges'] for i in m['iterations']),search_go_samples=sum(i['game_over'] for i in m['iterations']),depth=m['max_depth'],unity_sampled_peak_bytes=m['unity_allocated_sampled_peak_bytes'],checkpoints=m['budget_checkpoints'],candidate_additions=m['candidate_additions']);summaries.append(a)
    for fixture in sorted({r['fixture'] for r in rows}):
        by={r['name']:r for r in rows if r['fixture']==fixture};a,b=by['widen256'],by['widen256_repeat']
        equal=all(physics(i)==physics(j) for i,j in zip(a['report']['iterations'],b['report']['iterations'])) and a['report']['nodes']==b['report']['nodes'] and a['report']['candidate_additions']==b['report']['candidate_additions']
        if not equal:raise ValueError('Widening repeat differs')
        checks.append(dict(fixture=Path(fixture).stem,kind='widening_reproducible',passed=True))
        a,b=by['adaptive'],by['fixed128'];n=a['report']['completed_iterations']
        if [physics(i) for i in a['report']['iterations']]!=[physics(i) for i in b['report']['iterations'][:n]]:raise ValueError('Adaptive restarted or changed simulation prefix')
        checks.append(dict(fixture=Path(fixture).stem,kind='adaptive_continuation_prefix',completed=n,passed=True))
    return dict(searches=summaries,checks=checks,scope='Fixed cases and search statistics only; not natural-GO score evidence. Wall-clock stopping counts depend on machine load.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(load(a.input));save(a.output,r)
    for s in r['searches']:print(json.dumps({k:s[k] for k in ['fixture','name','completed'] if k in s}|{k:s[k] for k in ['reason','elapsed_ms','overrun_ms','additions','nonroot_additions'] if k in s}))
if __name__=='__main__':main()
