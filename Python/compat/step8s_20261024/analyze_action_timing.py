"""Separate wall time and game fixed-clock time in opt-in runtime action logs."""
import argparse,json
from collections import defaultdict
from pathlib import Path
from analyze_mcts_benchmark import distribution

def analyze(directory):
    result={}
    for condition in sorted(Path(directory).iterdir()):
        if not (condition/'results.json').exists():continue
        stages=defaultdict(lambda:defaultdict(list));intervals=defaultdict(list);count=0
        for path in condition.glob('*_runtime.jsonl'):
            groups={};order=[]
            for line in path.open(encoding='utf-8'):
                r=json.loads(line)
                if r.get('evt')!='action_clock':continue
                key=(r['episode'],r['action_id'])
                if key not in groups:groups[key]={};order.append(key)
                groups[key][r['phase']]=r
            previous={}
            for index,key in enumerate(order):
                events=groups[key]
                if not all(p in events for p in ('decision_start','movement_start','drop','complete')):continue
                count+=1;stage='early' if index<2 else 'dense'
                for label,start,end in [('planning','decision_start','movement_start'),('move_and_cooldown','movement_start','drop'),('post_drop_window','drop','complete')]:
                    a,b=events[start],events[end]
                    stages[stage][label+'_wall_ms'].append((b['wall']-a['wall'])*1000)
                    stages[stage][label+'_game_ms'].append((b['fixed_time']-a['fixed_time'])*1000)
                stages[stage]['cooldown_remaining_at_movement_ms'].append(events['movement_start']['cooldown']*1000)
                old=previous.get(key[0])
                if old is not None:
                    for label,a,b in [('drop_to_drop',old['drop'],events['drop']),('previous_drop_to_decision',old['drop'],events['decision_start']),('response_and_next_request',old['complete'],events['decision_start'])]:
                        intervals[label+'_wall_ms'].append((b['wall']-a['wall'])*1000)
                        intervals[label+'_game_ms'].append((b['fixed_time']-a['fixed_time'])*1000)
                previous[key[0]]=events
        result[condition.name]=dict(actions=count,stages={k:{n:distribution(v) for n,v in values.items()} for k,values in stages.items()},same_episode_intervals={k:distribution(v) for k,v in intervals.items()},note='Only consecutive same-episode drops count; fixture resets excluded. Game time uses fixed clock. p95 from small samples is descriptive.')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.input)
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    for k,v in r.items():print(k,json.dumps(v['same_episode_intervals']))
if __name__=='__main__':main()
