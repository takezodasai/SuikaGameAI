"""Matched post-first-drop physical ticks. No integration/position correction."""
import argparse,json,math,re
from pathlib import Path

def canonical(name,aliases):
    name=re.sub(r'f[0-9]+',lambda m:aliases.get(m[0],m[0]),name)
    def norm(s):
        if not s.startswith('m('):return s
        text=s[2:-1];depth=0
        for i,c in enumerate(text):
            if c=='(':depth+=1
            elif c==')':depth-=1
            elif c==',' and depth==0:return 'm('+','.join(sorted([norm(text[:i]),norm(text[i+1:])]))+')'
        raise ValueError('Invalid merge lineage')
    return norm(name)

def board(row,sample):
    aliases={x['from']:x['to'] for x in row['aliases']}
    out={}
    for f in sample['fruits']:
        if f['preview'] or f['merging']:continue
        key=canonical(f['id'],aliases)
        if key in out:raise ValueError('Duplicate lineage')
        out[key]=f
    return out

def difference(a,b):
    common=a.keys()&b.keys();unmatched=len(a.keys()^b.keys());pos=[];vel=[];angle=[]
    for key in common:
        x,y=a[key],b[key]
        if x['type']!=y['type']:raise ValueError('Same lineage different type')
        pos.append(math.hypot(x['position']['x']-y['position']['x'],x['position']['y']-y['position']['y']))
        vel.append(math.hypot(x['velocity']['x']-y['velocity']['x'],x['velocity']['y']-y['velocity']['y']))
        angle.append(abs((x['angle']-y['angle']+180)%360-180))
    return dict(unmatched_lineages=unmatched,max_position=max(pos,default=0),max_velocity=max(vel,default=0),max_angle=max(angle,default=0),count_a=len(a),count_b=len(b))

def analyze(rows):
    by={(r['mode'],r['x'],r['second']):r for r in rows}
    if len(by)!=8:raise ValueError('Eight trajectories required')
    output=[];physics=[]
    for r in rows:
        if [s['elapsed_ticks'] for s in r['samples']]!=[25,50,75,100]:raise ValueError('Incomplete matched ticks')
    for x in [.5,.75]:
        for mode in ['prediction','live']:
            a,b=by[(mode,x,False)],by[(mode,x,True)];points=[]
            for sa,sb in zip(a['samples'],b['samples']):
                points.append(dict(tick=sa['elapsed_ticks'],wait_score=sa['score'],wait_merges=sa['merges'],second_score=sb['score'],second_merges=sb['merges'],net_second_score=sb['score']-sa['score'],board_difference=difference(board(a,sa),board(b,sb))))
            output.append(dict(x=x,mode=mode,second_drop_elapsed=b['second_drop_tick']-b['first_drop_tick'],first_legal_offset=b['first_legal_offset'],points=points,wait_changes=[e for e in a['changes'] if 0<=e['elapsed_tick']<=100],second_changes=[e for e in b['changes'] if 0<=e['elapsed_tick']<=100]))
        for second in [False,True]:
            p,l=by[('prediction',x,second)],by[('live',x,second)];points=[]
            for sp,sl in zip(p['samples'],l['samples']):points.append(dict(tick=sp['elapsed_ticks'],score_match=sp['score']==sl['score'],merges_match=sp['merges']==sl['merges'],go_match=sp['game_over']==sl['game_over'],**difference(board(p,sp),board(l,sl))))
            physics.append(dict(x=x,second=second,drop1_prediction=p['first_drop_tick'],drop1_live=l['first_drop_tick'],drop2_prediction=p['second_drop_tick'],drop2_live=l['second_drop_tick'],points=points))
    return dict(counterfactuals=output,live_vs_prediction=physics,limitation='Restored cold layout; fixed-step input controller mirrors UDP rules, no network delay. Score differences are matched-time intervention effects, not per-fruit causal credit. Snapshots after 100 and unfinished-step work are excluded.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze([json.loads(l) for l in a.input.read_text(encoding='utf-8-sig').splitlines()])
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2,allow_nan=False)
    for x in r['counterfactuals']:print(json.dumps(x))
if __name__=='__main__':main()
