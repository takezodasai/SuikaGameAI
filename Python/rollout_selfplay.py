"""Version-pinned rollout self-play. Own processes only; no in-game checkpoint restore."""
import csv,json,os,statistics,subprocess,time,uuid
from pathlib import Path
from watermelon_lab import ROOT,sha,write
from compare_watermelon_dynamic import active_players
from suika_ai.collection_metadata import atomic_metadata as atomic
from suika_ai.overnight_collection import exclusive_lock,process_memory
from suika_ai.parallel_play import check_ports,worker_specs

DEFAULT_MODEL=ROOT/'Python/outputs/learned_rollout_01/training/model.json'
DEFAULT_EXE=ROOT/'Unity/Builds/PolicySelfPlay_01/SuikaGameAI.exe'
RESERVATION=ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json'

def reservations():
    rs=json.loads(RESERVATION.read_text())['episodes']
    return {r['seed'] for r in rs},{r['initial_sequence'] for r in rs}

def read_rows(path):
    rows=[];partial=False
    if Path(path).exists():
        for raw in Path(path).read_bytes().splitlines():
            try:rows.append(json.loads(raw))
            except ValueError:partial=True
    return rows,partial

def audit_trace(folder,job,actor_sha,iterations=256,exit_code=0,override=None):
    rows,partial=read_rows(Path(folder)/'trace.jsonl');errors=[]
    if partial:errors.append('partial_or_invalid_trace')
    end=next((r for r in reversed(rows) if r['evt']=='end'),None);root=next((r for r in rows if r['evt']=='root'),None)
    decisions=[r for r in rows if r['evt']=='decision'];releases=[r for r in rows if r['evt']=='release'];score=None
    for r in decisions:
        s=r['search'];p=r['rollout']
        if s['completed_iterations']!=iterations or sum(a['visits'] for a in s['root'])!=iterations or not s['source_unchanged']:errors.append('MCTS_iteration_or_source_audit')
        if p['model_sha256']!=actor_sha or p['rollout_calls']!=p['learned_calls']+p['random_calls']+p['fallback_calls'] or p['learned_calls']!=s['guided_calls']:errors.append('actor_or_rollout_audit')
        if r['command']['x']!=r['planning']['selected_x']:errors.append('root_selection_changed')
    errors += [r.get('error','native_error') for r in rows if r['evt']=='error']
    prefix=[]
    if root:prefix=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in releases]
    reserved_seeds,reserved_prefixes=reservations();initial8=','.join(map(str,prefix[:8])) if len(prefix)>=8 else None
    if job['game_seed'] in reserved_seeds or initial8 in reserved_prefixes:errors.append('reserved_Test19_quarantine')
    if root and (root['restoration']!='fresh_game_from_start_no_fixture' or root['initial_score']!=0):errors.append('not_normal_game')
    natural=bool(end and end['natural_go'] and not end['truncated'] and end['reason']=='natural_go')
    if exit_code!=0:errors.append('player_exit_'+str(exit_code))
    if override:errors.append(override)
    if natural and (not root or end['accepted_drops']!=len(releases) or len(prefix)<8):errors.append('incomplete_episode_audit')
    natural=natural and not errors
    if natural:score=end['score']
    status='natural_go' if natural else 'quarantined' if 'reserved_Test19_quarantine' in errors else override or (end['reason'] if end else 'missing_end')
    return dict(job=job['index'],game_seed=job['game_seed'],search_seed=job['search_seed'],actor_sha256=actor_sha,exit_code=exit_code,natural_go=natural,valid_for_learning=natural,status=status,final_score=score,last_observed_score=rows[-1]['score'] if rows else None,drops=len(releases),decisions=len(decisions),initial8=initial8,errors=sorted(set(errors)),elapsed_seconds=end['elapsed_seconds'] if end else None,new_watermelons=end['new_watermelons'] if end else None,double_watermelons=end['double_watermelons'] if end else None,mean_planning_ms=statistics.mean(r['planning_ms'] for r in decisions) if decisions else None,model_calls=sum(r['rollout']['learned_calls'] for r in decisions),physics_ticks=sum(r['search']['physics_ticks'] for r in decisions),trace_sha256=sha(Path(folder)/'trace.jsonl') if rows else None,attempt=str(Path(folder).resolve()),resume_mode='fresh-process whole-game retry; no native-state restoration')

def job_results(out):
    found=[]
    for d in sorted((Path(out)/'jobs').glob('job_*')):
        rs=[json.loads(p.read_text()) for p in sorted(d.glob('attempt_*/result.json'))]
        good=next((r for r in rs if r['valid_for_learning']),None)
        if good:found.append(good)
        elif rs:found.append(rs[-1])
    return found

def summary(out,persist=True):
    out=Path(out);rs=job_results(out);good=[r for r in rs if r['valid_for_learning']];scores=[r['final_score'] for r in good]
    value=dict(jobs_with_results=len(rs),natural_go=len(good),invalid_or_censored=len(rs)-len(good),mean_score=statistics.mean(scores) if scores else None,median_score=statistics.median(scores) if scores else None,max_score=max(scores) if scores else None,min_score=min(scores) if scores else None,new_watermelons=sum(r['new_watermelons'] for r in good),double_watermelons=sum(r['double_watermelons'] for r in good),jobs=rs)
    if persist:
        atomic(out/'summary.json',value)
        with (out/'games.csv').open('w',newline='',encoding='utf-8-sig') as f:
            fields=['job','game_seed','search_seed','status','natural_go','final_score','last_observed_score','drops','new_watermelons','double_watermelons','mean_planning_ms','elapsed_seconds'];w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rs)
    return value

def completed_job(d,max_attempts):
    rs=[json.loads(p.read_text()) for p in sorted(d.glob('attempt_*/result.json'))]
    if any(r['valid_for_learning'] or r['status'] in ['drop_limit','wall_limit','quarantined'] for r in rs):return True
    # User interruptions do not consume the technical-error retry allowance.
    return sum(r['status'] not in ['interrupted','abandoned_partial'] for r in rs)>=max_attempts

def collect(out,config=None,resume=False):
    out=Path(out).resolve()
    if resume:
        config=json.loads((out/'collection.json').read_text())
    else:
        if out.exists():raise FileExistsError('Protect old session: use --resume or a fresh output')
        config=dict(config,version='rollout-selfplay-v1',session_id=uuid.uuid4().hex,model=str(Path(config['model']).resolve()),exe=str(Path(config['exe']).resolve()))
        config.update(actor_sha256=sha(config['model']),exe_sha256=sha(config['exe']),assembly_sha256=sha(Path(config['exe']).parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll'),rules_version='step8e-all-fruit-go-v2',go_ratio=.83)
    if not 1<=config['workers']<=4 or not 0<config['hours']<=168 or not 0<config['game_seconds']<=86400 or not 1<=config['max_drops']<=100000 or config['iterations']!=256 or config['depth']!=4 or not 0<=config['mixture']<=1 or not 0<=config['seed_base']<=2147483646-config['max_jobs'] or not 1<=config['max_attempts']<=3 or config['stall_seconds']<10:raise ValueError('Invalid fixed self-play configuration')
    if active_players():raise RuntimeError('Existing Player(s) active: leave them untouched; retry later')
    check_ports(worker_specs(config['workers'],config['base_port']))
    if sha(config['model'])!=config['actor_sha256'] or sha(config['exe'])!=config['exe_sha256'] or sha(Path(config['exe']).parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')!=config['assembly_sha256']:raise ValueError('Pinned model/Player changed')
    if not resume:out.mkdir(parents=True);write(out/'collection.json',config)
    (out/'jobs').mkdir(exist_ok=True)
    with exclusive_lock(out/'collector.lock'),(out/'collector_events.jsonl').open('a',encoding='utf8') as events:
        runtime=json.loads((out/'runtime.json').read_text()) if (out/'runtime.json').exists() else {};used=runtime.get('used_seconds',0);start=time.monotonic();active={};drain=False;forced=False;last_save=0;last_progress=0;consecutive=0;deadline_announced=False;interrupted_once=False
        reserved,reserved_prefixes=reservations();reserved|=set(config.get('excluded_seeds',[]))
        def emit(event,**kw):
            row=dict(event=event,unix=time.time(),**kw);events.write(json.dumps(row)+'\n');events.flush();os.fsync(events.fileno());print(json.dumps(row),flush=True)
        def allocate(slot):
            for i in range(config['max_jobs']):
                d=out/'jobs'/f'job_{i:06d}'
                if any(a['job']['index']==i for a in active.values()):continue
                d.mkdir(exist_ok=True)
                jp=d/'job.json'
                if jp.exists():job=json.loads(jp.read_text())
                else:
                    seed=config['seed_base']+i
                    if seed in reserved:continue
                    search=int.from_bytes(__import__('hashlib').sha256((config['session_id']+':search:'+str(i)).encode()).digest()[:4],'little')&0x7fffffff
                    job=dict(index=i,game_seed=seed,search_seed=search,source_group='seed:'+str(seed));write(jp,job)
                attempts=sorted(d.glob('attempt_*'))
                for attempt in attempts:
                    if not (attempt/'result.json').exists():
                        recovered=audit_trace(attempt,job,config['actor_sha256'],256,None)
                        if not recovered['valid_for_learning']:recovered['status']='abandoned_partial'
                        atomic(attempt/'result.json',recovered)
                if completed_job(d,config['max_attempts']):continue
                folder=d/f'attempt_{len(attempts):03d}';folder.mkdir();return job,folder
            return None
        def launch(slot,item):
            job,folder=item
            if sha(config['model'])!=config['actor_sha256']:raise RuntimeError('Actor changed; cannot mix model versions')
            cfg=dict(output=str(folder/'trace.jsonl'),policy_model=config['model'],mode='learned',mixture=config['mixture'],normal_start=True,final_selection='legacy',game_seed=job['game_seed'],future_seed=job['game_seed'],search_seed=job['search_seed'],iterations=256,depth=4,max_drops=config['max_drops'],max_seconds=config['game_seconds'],first_x=-1)
            write(folder/'config.json',cfg);port=config['base_port']+2*slot
            args=[config['exe'],'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(job['game_seed']),'--suika-listen-port',str(port),'--suika-python-port',str(port+1),'-suikaRuntimeProbe',str(folder/'runtime.jsonl'),'-suikaPolicySelfPlayLab',str(folder/'config.json'),'-logFile',str(folder/'player.log')]
            proc=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            write(folder/'launch.json',dict(pid=proc.pid,command=args,actor_sha256=config['actor_sha256'],exe_sha256=config['exe_sha256'],assembly_sha256=config['assembly_sha256']))
            active[slot]=dict(proc=proc,folder=folder,job=job,began=time.monotonic(),progress=time.monotonic(),offset=0,buffer=b'',prefix=[],last=None,override=None)
            emit('job_start',job=job['index'],slot=slot,game_seed=job['game_seed'],attempt=str(folder))
        def poll_trace(a):
            path=a['folder']/'trace.jsonl'
            if not path.exists():return
            with path.open('rb') as f:f.seek(a['offset']);data=f.read();a['offset']=f.tell()
            if data:a['progress']=time.monotonic()
            lines=(a['buffer']+data).split(b'\n');a['buffer']=lines.pop()
            for line in lines:
                if not line.strip():continue
                r=json.loads(line);a['last']=r
                if r['evt']=='root':a['prefix']=[r['state']['current_fruit']['type'],r['state']['next_fruit_type']]
                elif r['evt']=='release' and len(a['prefix'])<8:a['prefix'].append(r['state']['next_fruit_type'])
            if len(a['prefix'])>=8 and ','.join(map(str,a['prefix'][:8])) in reserved_prefixes:a['override']='reserved_Test19_quarantine'
        emit('session_start',resume=resume,used_seconds=used,workers=config['workers'],actor_sha256=config['actor_sha256'])
        try:
            while True:
                try:
                    expired=used+time.monotonic()-start>=config['hours']*3600
                    if expired and not deadline_announced:deadline_announced=True;emit('budget_draining',reason='stop new jobs; existing games continue to natural GO or game safety cap')
                    if not expired and not drain:
                        for slot in range(config['workers']):
                            if slot not in active:
                                item=allocate(slot)
                                if item:launch(slot,item)
                    finished_any=False
                    for slot,a in list(active.items()):
                        poll_trace(a)
                        if time.monotonic()-a['progress']>config['stall_seconds']:a['override']='progress_timeout'
                        if time.monotonic()-a['began']>config['game_seconds']+config['stall_seconds']:a['override']='process_timeout'
                        if forced:a['override']='interrupted'
                        if a['override'] and a['proc'].poll() is None:a['proc'].terminate()
                        if a['proc'].poll() is not None:
                            a['proc'].wait();poll_trace(a);r=audit_trace(a['folder'],a['job'],config['actor_sha256'],256,a['proc'].returncode,a['override']);r['wall_seconds']=time.monotonic()-a['began'];atomic(a['folder']/'result.json',r)
                            if not r['valid_for_learning'] and a['last']:atomic(a['folder']/'last_observed_state.json',dict(record=a['last'],exact_native_restore=False,restart_mode='whole game from seed'))
                            emit('job_end',job=a['job']['index'],natural_go=r['natural_go'],score=r['final_score'],status=r['status']);del active[slot];finished_any=True;consecutive=consecutive+1 if r['errors'] else 0;summary(out)
                            if consecutive>=3:drain=True;emit('circuit_breaker',reason='three consecutive technical failures; no new jobs')
                    if time.monotonic()-last_save>5:
                        last_save=time.monotonic();details=[dict(job=a['job']['index'],pid=a['proc'].pid,elapsed_seconds=time.monotonic()-a['began'],score=a['last']['score'] if a['last'] else None,drops=a['last'].get('accepted_drops') if a['last'] else None) for a in active.values()];atomic(out/'runtime.json',dict(used_seconds=used+time.monotonic()-start,active_jobs=[a['job']['index'] for a in active.values()],active_details=details,draining=drain or expired,forced=forced))
                        if time.monotonic()-last_progress>=60:last_progress=time.monotonic();emit('progress',active=details)
                        for a in active.values():
                            with (out/'resources.jsonl').open('a') as f:f.write(json.dumps(dict(unix=time.time(),job=a['job']['index'],pid=a['proc'].pid,memory=process_memory(a['proc'].pid)))+'\n')
                    # A completed/failed last worker must get another allocation pass:
                    # there may be a retry or the next new game waiting.
                    if not active and not (finished_any and not expired and not drain):break
                    time.sleep(.25)
                except KeyboardInterrupt:
                    if interrupted_once:forced=True;emit('interrupt_force',reason='terminate owned Players; preserve partial logs; retry whole jobs on resume')
                    else:interrupted_once=True;drain=True;emit('interrupt_drain',reason='no new jobs; current games continue; Ctrl+C again to stop now')
        finally:
            for a in active.values():
                if a['proc'].poll() is None:a['proc'].terminate();a['proc'].wait(10)
                if not (a['folder']/'result.json').exists():
                    r=audit_trace(a['folder'],a['job'],config['actor_sha256'],256,a['proc'].returncode,'interrupted');atomic(a['folder']/'result.json',r)
            atomic(out/'runtime.json',dict(used_seconds=used+time.monotonic()-start,active_jobs=[],draining=drain,forced=forced))
        value=summary(out);emit('session_end',natural_go=value['natural_go'],invalid=value['invalid_or_censored']);return value
