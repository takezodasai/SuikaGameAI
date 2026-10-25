"""Audit actual-game event snapshots; never infer double success from max fruit."""
def audit_events(rows):
    last=None;known=None
    for row in rows:
        state=row.get('state')
        if not state:continue
        snap=state.get('episode_events')
        if not snap or not snap.get('known'):
            if known:raise ValueError('Event recording disappeared within episode')
            continue
        known=True
        if snap['source']!='actual_game' or snap['version']!='step8u-events-v1':raise ValueError('Wrong event source/version')
        events=snap['events'];created=present=doubles=0;kinds={};previous_drop=0;previous_time=-float('inf');previous_score=0
        for i,e in enumerate(events,1):
            if e['event_id']!=i:raise ValueError('Duplicate/missing actual event')
            if e['drop_count']<previous_drop or e['drop_count']>snap['drop_count'] or e['fixed_time']<previous_time or e['score']<previous_score or e['score']>state['score']:raise ValueError('Invalid event clock/score')
            previous_drop=e['drop_count'];previous_time=e['fixed_time'];previous_score=e['score'];kind=e['kind'];kinds[kind]=kinds.get(kind,0)+1
            if kind=='watermelon_created':created+=1;present+=1
            elif kind=='watermelon_pair_disappeared':present-=2;doubles+=1
            elif kind=='first_watermelon':
                if created!=1 or kinds[kind]!=1:raise ValueError('Invalid first watermelon')
            elif kind=='second_watermelon':
                if created!=2 or kinds[kind]!=1:raise ValueError('Invalid second watermelon')
            elif kind=='two_watermelons_present':
                if present<2:raise ValueError('Invalid simultaneous presence')
            elif kind=='double_watermelon':
                if kinds[kind]!=doubles:raise ValueError('Invalid double event')
            else:raise ValueError('Unknown actual event')
            if (e['watermelons_created'],e['watermelons_present'],e['double_watermelons'])!=(created,present,doubles) or present<0:raise ValueError('Event count mismatch')
        if (snap['watermelons_created'],snap['watermelons_present'],snap['double_watermelons'])!=(created,present,doubles):raise ValueError('Snapshot counters differ')
        if kinds.get('first_watermelon',0)!=int(created>=1) or kinds.get('second_watermelon',0)!=int(created>=2) or kinds.get('double_watermelon',0)!=doubles:raise ValueError('Missing milestone')
        if last and (snap['drop_count']<last['drop_count'] or events[:len(last['events'])]!=last['events']):raise ValueError('Actual event history was rewritten')
        board=sum(f['type']==10 for f in state.get('fruits',[]))
        if board!=present:raise ValueError('Actual watermelon board/event count differs')
        last=snap
    if last is None:return dict(double_watermelon_known=False,double_watermelon_success=None,actual_events=None)
    return dict(double_watermelon_known=True,double_watermelon_success=last['double_watermelons']>0,actual_events=last)
