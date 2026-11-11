"""Strict per-physics-tick actual replay comparison, with distinct event phases."""
import argparse,json,math
from pathlib import Path
from collections import defaultdict

def distance(a,b):return math.hypot(a['x']-b['x'],a['y']-b['y'])
def compare_ticks(a,b):
    sa,sb=a['state'],b['state'];fa={f['id']:f for f in a['bodies']['fruits']};fb={f['id']:f for f in b['bodies']['fruits']}
    livea={k:v for k,v in fa.items() if not v['merging']};liveb={k:v for k,v in fb.items() if not v['merging']}
    result=dict(score=sa['score']==sb['score'],go=sa['game_over']==sb['game_over'],held_next=(sa['current_fruit']['type'],sa['next_fruit_type'])==(sb['current_fruit']['type'],sb['next_fruit_type']),ids_types=set(livea)==set(liveb) and all(livea[k]['type']==liveb[k]['type'] for k in livea.keys()&liveb.keys()),full_body_ids=set(fa)==set(fb),position=0.,velocity=0.,angle=0.,omega=0.,mass=0.,inertia=0.,com=0.,contact_members=True,sleep=True,collision_eligibility=True,merge_events=[x for x in a['bodies']['events'] if x.startswith('merge:')]==[x for x in b['bodies']['events'] if x.startswith('merge:')],callback_order=a['bodies']['events']==b['bodies']['events'],rng=a['rng']==b['rng'],fixed_time_error=abs(a['relative_fixed_time']-b['relative_fixed_time']))
    for k in livea.keys()&liveb.keys():
        x,y=livea[k],liveb[k]
        for field,alias in [('position','position'),('velocity','velocity'),('center_of_mass','com')]:result[alias]=max(result[alias],distance(x[field],y[field]))
        result['angle']=max(result['angle'],abs((x['angle']-y['angle']+180)%360-180))
        for field,alias in [('angular_velocity','omega'),('mass','mass'),('inertia','inertia')]:result[alias]=max(result[alias],abs(x[field]-y[field]))
        result['sleep'] &= x['sleeping']==y['sleeping'];result['collision_eligibility'] &= x['has_collided']==y['has_collided']
        result['contact_members'] &= sorted(c['other'] for c in x['contacts'])==sorted(c['other'] for c in y['contacts'])
    result['within_tolerance']=all(result[k] for k in ['score','go','held_next','ids_types','full_body_ids','contact_members','sleep','collision_eligibility','merge_events','rng']) and result['position']<=1e-4 and result['velocity']<=1e-3 and result['angle']<=.01 and result['omega']<=.1 and result['mass']<=1e-6 and result['inertia']<=1e-6 and result['com']<=1e-6 and result['fixed_time_error']<=1e-8
    return result

def analyze(path):
    groups=defaultdict(dict);ends={};starts={}
    with Path(path).open(encoding='utf-8-sig') as f:
        for line in f:
            if not line.endswith('\n'):raise ValueError('Incomplete final line; do not validate a running/truncated file')
            r=json.loads(line);key=(r['seed'],r['repeat'])
            if r['evt']=='tick':
                if r['tick'] in groups[key]:raise ValueError('Duplicate tick')
                groups[key][r['tick']]=r
            elif r['evt']=='end':ends[key]=r
            elif r['evt']=='start':starts[key]=r
            elif r['evt']=='error':raise ValueError(r['error'])
    output=[]
    for (seed,rep),rows in groups.items():
        if rep==0:continue
        base=groups[(seed,0)];common=sorted(rows.keys()&base.keys());errors=[(t,compare_ticks(base[t],rows[t])) for t in common]
        failures=[(t,e) for t,e in errors if not e['within_tolerance']]
        numeric=['position','velocity','angle','omega','mass','inertia','com','fixed_time_error'];flags=['score','go','held_next','ids_types','full_body_ids','contact_members','sleep','collision_eligibility','merge_events','callback_order','rng']
        output.append(dict(seed=seed,repeat=rep,compared_ticks=len(common),same_tick_set=rows.keys()==base.keys(),completed=(seed,rep) in ends,commands_equal=ends[(seed,rep)]['commands']==ends[(seed,0)]['commands'],initial_rng_equal=starts[(seed,rep)]['rng']==starts[(seed,0)]['rng'],
            max_errors={k:max(e[k] for _,e in errors) for k in numeric},mismatch_tick_counts={k:sum(not e[k] for _,e in errors) for k in flags},first_failure_tick=failures[0][0] if failures else None,first_failure=failures[0][1] if failures else None,
            original_score=ends[(seed,0)]['state']['score'],replay_score=ends[(seed,rep)]['state']['score'],original_wall_ms=ends[(seed,0)]['wall_ms'],replay_wall_ms=ends[(seed,rep)]['wall_ms'],truncated=ends[(seed,rep)]['truncated']))
    valid=bool(output) and all(x['first_failure_tick'] is None and x['same_tick_set'] and x['commands_equal'] and x['completed'] for x in output)
    return dict(comparisons=output,verified_in_tested_prefix=valid,full_natural_go_return_labels=False,thresholds=dict(position=1e-4,velocity=1e-3,angle_degrees=.01,omega=.1),limitation='Tolerance checks of short actual reset prefixes, not a guarantee of long crowded/GO reproducibility. Removal callbacks and render-frame counts are separate from live-body accuracy.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.input)
    with a.output.open('x',encoding='utf8') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
