"""Observation-only milestone extraction. Unknown is never converted to failure."""
KINDS=('watermelon_one','watermelon_melon_one','watermelon_melon_two','watermelon_two','double_watermelon')
V1={'first_watermelon':'watermelon_one','two_watermelons_present':'watermelon_two','double_watermelon':'double_watermelon'}

def extract(rows):
    exact={}; sampled={}; seen_ids={}; v1_known=False; extended_known=False;previous_extended=[]
    for row in rows:
        s=row.get('state') or {}; snap=s.get('episode_events') or {}
        if snap.get('source')=='actual_game' and snap.get('known'):
            v1_known=True
            for e in snap.get('events',[]):
                eid=e['event_id']
                if eid in seen_ids and seen_ids[eid]!=e:raise ValueError('Rewritten actual event')
                seen_ids[eid]=e
                kind=V1.get(e.get('kind'))
                if kind and kind not in exact:exact[kind]=dict(kind=kind,source='actual_game',precision='merge_callback',score=e['score'],drop_count=e['drop_count'],fixed_time=e['fixed_time'])
            extra=snap.get('learning') or {}
            if extra.get('version')=='learning-milestones-v1' and extra.get('known'):
                history=extra.get('events',[]);kinds=[e.get('kind') for e in history]
                if any(k not in KINDS for k in kinds):raise ValueError('Unknown learning milestone')
                if len(set(kinds))!=len(kinds):raise ValueError('Duplicate learning milestone')
                if history[:len(previous_extended)]!=previous_extended:raise ValueError('Rewritten learning history')
                previous_extended=history
                if type(extra.get('melons_present')) is not int or type(extra.get('watermelons_present')) is not int or min(extra['melons_present'],extra['watermelons_present'])<0:raise ValueError('Invalid learning counters')
                if isinstance(s.get('fruits'),list):
                    for kind,key in [(9,'melons_present'),(10,'watermelons_present')]:
                        if sum(f.get('type')==kind and not f.get('is_merging',False) for f in s['fruits'])!=extra[key]:raise ValueError('Learning board/count mismatch')
                clock=(-1,-float('inf'),-1)
                for e in history:
                    now=(e['drop_count'],e['fixed_time'],e['score'])
                    if any(a<b for a,b in zip(now,clock)) or e['score']>s['score']:raise ValueError('Invalid learning event clock/score')
                    w=e['watermelons_present'];m=e['melons_present'];goal=e['kind']
                    if w<0 or m<0 or (goal=='watermelon_one' and w<1) or (goal=='watermelon_melon_one' and (w<1 or m<1)) or (goal=='watermelon_melon_two' and (w<1 or m<2)) or (goal=='watermelon_two' and w<2):raise ValueError('Invalid learning milestone counts')
                    clock=now
                extended_known=True
                for e in extra.get('events',[]):
                    kind=e['kind']
                    if kind not in KINDS:raise ValueError('Unknown learning milestone')
                    if kind not in exact:exact[kind]=dict(e,source='actual_game',precision='merge_callback')
        fruit=s.get('fruits')
        if isinstance(fruit,list):
            w=sum(f.get('type')==10 and not f.get('is_merging',False) for f in fruit)
            m=sum(f.get('type')==9 and not f.get('is_merging',False) for f in fruit)
            for kind,condition in [('watermelon_melon_one',w>=1 and m>=1),('watermelon_melon_two',w>=1 and m>=2)]:
                if condition and kind not in sampled:sampled[kind]=dict(kind=kind,source='actual_game',precision='saved_snapshot_only',score=s['score'],drop_count=snap.get('drop_count'),action_id=row.get('action_id'),snapshot_fixed_time=s.get('snapshot_fixed_time'))
    labels={}
    for kind in KINDS:
        complete=extended_known if kind.startswith('watermelon_melon_') else v1_known
        found=exact.get(kind) or sampled.get(kind)
        labels[kind]=dict(known=bool(found) or complete,achieved=bool(found) if found or complete else None,exact_timing=kind in exact)
    return dict(labels=labels,events=list(exact.values()),snapshot_evidence=list(sampled.values()),limitation='Old melon coexistence absence is unknown; saved snapshots can miss transient milestones.')

def rewards(audit,weights):
    """One learning reward per milestone/episode; never modifies game score."""
    if set(weights)-set(KINDS):raise ValueError('Unknown reward key')
    if any(type(v) not in (int,float) or not __import__('math').isfinite(v) or v<0 for v in weights.values()):raise ValueError('Invalid reward weight')
    if weights.get('double_watermelon',0)<max([v for k,v in weights.items() if k!='double_watermelon'] or [0]):raise ValueError('Double reward must be largest')
    seen=set();items=[]
    for e in audit['events']:
        if e['kind'] in seen:continue
        seen.add(e['kind']);items.append(dict(e,learning_reward=weights.get(e['kind'],0)))
    return dict(events=items,total_learning_reward=sum(x['learning_reward'] for x in items),game_score_unchanged=True,unresolved=[k for k,v in audit['labels'].items() if not v['known']],snapshot_only_not_rewarded=[e['kind'] for e in audit['snapshot_evidence'] if e['kind'] not in seen])
