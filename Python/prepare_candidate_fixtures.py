"""Export declared cold fixtures from a completed log; never pretend native restore.

Raw input is read only. Missing held/cooldown fields require --allow-cold.
Source episode ancestry must be carried into any subsequent learning split.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def fixture(row,phase,allow_cold=False):
    state=row.get('decision_source') if phase=='decision_source' else row.get('state')
    if not isinstance(state,dict):raise ValueError('Missing requested source phase')
    required=['fruits','current_fruit','next_fruit_type','score']
    if any(k not in state for k in required):raise ValueError('Missing core state')
    if state.get('game_over'):raise ValueError('Terminal source cannot accept a drop')
    held=state['current_fruit'];missing=[]
    if type(held.get('type')) is not int or not 0<=held['type']<=10 or type(state['next_fruit_type']) is not int or not 0<=state['next_fruit_type']<=10:raise ValueError('Unknown held/NEXT type')
    if type(held.get('x')) not in (int,float) or not math.isfinite(held['x']):raise ValueError('Invalid held x')
    if type(state['score']) is not int or state['score']<0:raise ValueError('Invalid score')
    if not held.get('y_known',False) or type(held.get('y')) not in (int,float) or not math.isfinite(held.get('y',float('nan'))):missing.append('held_y')
    if 'drop_cooldown_remaining' not in state:missing.append('drop_cooldown_remaining')
    if 'game_tick' not in state:missing.append('original_game_tick')
    if missing and not allow_cold:raise ValueError('Missing fields require explicit --allow-cold: '+','.join(missing))
    for f in state['fruits']:
        if any(type(f.get(k)) not in (int,float) or not math.isfinite(f[k]) for k in ('x','y','vx','vy','angle','angular_velocity')):raise ValueError('Missing/nonfinite fruit kinematics')
    p=row.get('info',{}).get('planning') or {};bounds=p.get('drop_range') or state.get('drop_range') or {}
    geo=[bounds.get('left_wall_inner'),bounds.get('right_wall_inner'),p.get('floor_y'),p.get('game_over_y')]
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in geo) or geo[1]<=geo[0] or geo[3]<=geo[2]:raise ValueError('Missing environment geometry; do not impute from current Prefabs')
    return dict(fruits=state['fruits'],score=state['score'],current_fruit_type=held['type'],next_fruit_type=state['next_fruit_type'],held_x=held['x'],
        drop_cooldown_remaining=state.get('drop_cooldown_remaining',0),game_over_y=geo[3],snapshot=dict(state,geometry=geo),source_phase=phase,
        source_action_id=row['action_id'],source_episode=row.get('episode_id'),source_environment_id=state.get('environment_id'),unknown_fields=missing,
        missing_native=['solver_contact_cache','native_sleep_timer','original_Unity_Random.state'],
        explicit_assumptions={k:('current prefab spawn height' if k=='held_y' else 0 if k=='drop_cooldown_remaining' else 'relative clock only') for k in missing},
        restoration_claim='visible-field cold reconstruction only; never an exact native checkpoint')


def main():
    p=argparse.ArgumentParser();p.add_argument('--log',type=Path,required=True);p.add_argument('--actions',type=int,nargs='+',required=True);p.add_argument('--phase',choices=['decision_source','post_state'],default='post_state');p.add_argument('--allow-cold',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    selected=[];last=None;sha=hashlib.sha256()
    with a.log.open('rb') as source:
        for line in source:
            sha.update(line);row=json.loads(line);last=row
            if row.get('event')=='transition' and row.get('action_id') in a.actions:selected.append(row)
    if not last or last.get('event')!='episode_end' or not last.get('game_over') or last.get('truncated') or not last.get('conserved'):raise ValueError('Only completed, conserved natural-GO source logs accepted')
    if len(selected)!=len(set(a.actions)):raise ValueError('Missing or duplicated action IDs')
    data=[fixture(r,a.phase,a.allow_cold) for r in selected];a.output.mkdir()
    for d in data:
        d.update(source_file=str(a.log.resolve()),source_sha256=sha.hexdigest())
        (a.output/f"action_{d['source_action_id']:06d}.json").write_text(json.dumps(d,ensure_ascii=False),encoding='utf8')
    print(json.dumps(dict(fixtures=len(data),source_sha256=sha.hexdigest(),native_checkpoint_exact=False)))


if __name__=='__main__':main()
