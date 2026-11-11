"""STEP8-AE independent, resumable actual-game collection. Never trains models."""
import contextlib,csv,hashlib,json,math,os,random,threading,time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
from .parallel_play import run_parallel,DurableLog
from .unity_env import validate_planning_settings
from .collection_metadata import atomic_metadata as atomic_json
from .long_value_data import slim,tail
from .value_data import validate_episode
from .collection_audit import load_environment

DEFAULT_PROFILES=[dict(depth=d,iterations=n,weight=w) for ds,w in [([(4,1024),(4,8192),(6,2048),(6,16384),(8,4096),(8,32768)],.6/6), ([(10,8192),(10,16384),(12,8192),(12,32768)],.3/4), ([(14,16384),(16,32768)],.1/2)] for d,n in ds]
RULES='step8e-all-fruit-go-v2'

def player_identity(exe):
    exe=Path(exe);data=exe.parent/(exe.stem+'_Data')
    files=[exe]+([exe.parent/'UnityPlayer.dll'] if (exe.parent/'UnityPlayer.dll').exists() else [])
    if data.exists():files+=list(data.rglob('Assembly-CSharp.dll'))+list(data.glob('globalgamemanagers*'))+list(data.glob('level*'))+list(data.glob('*.assets'))
    return {str(p.relative_to(exe.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files)) if p.is_file()}

def settings(profile,search_seed,seconds=240):
    if type(profile['depth']) is not int or not 2<=profile['depth']<=16 or type(profile['iterations']) is not int or not 32<=profile['iterations']<=32768:raise ValueError('Invalid collection profile')
    return validate_planning_settings(dict(ai_mode='mcts',mcts_extended_budget=True,mcts_collection_budget=True,mcts_budget_mode='fixed',mcts_iterations=profile['iterations'],mcts_max_iterations=profile['iterations'],mcts_max_depth=profile['depth'],mcts_time_limit_seconds=seconds,mcts_seed=search_seed,candidate_count=5,post_drop_steps=25,execution_mode='sync',mcts_auto_depth=False,mcts_widening=False,mcts_full_trace=False))

def choose_job(config,index):
    rng=random.Random(config['schedule_seed']+index*1000003);p=rng.choices(config['profiles'],weights=[x['weight'] for x in config['profiles']])[0]
    search_seed=random.Random(config['schedule_seed']+index*1000033+9176).randrange(2147483647)
    return dict(index=index,game_seed=config['game_seed']+index,search_seed=search_seed,profile=p,settings=settings(p,search_seed,config['think_seconds']))

@contextlib.contextmanager
def exclusive_lock(path):
    import msvcrt
    with Path(path).open('a+b') as f:
        f.seek(0);f.write(b'0');f.flush();f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('Another collector owns this output directory')
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def process_memory(pid):
    """Windows process counters, read-only; None means unavailable, not zero."""
    import ctypes
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True);kernel.OpenProcess.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE];psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    handle=kernel.OpenProcess(0x410,False,int(pid))
    if not handle:return None
    try:
        value=Memory();value.cb=ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(value),value.cb):return None
        return dict(pid=pid,working_set_bytes=value.WorkingSetSize,private_bytes=value.PrivateUsage)
    finally:kernel.CloseHandle(handle)

def event_geometry(event,environment):
    value=dict(event);location=event.get('location')or{};value['geometry_known']=False
    if not location.get('position_known'):return value
    value['creation_position']=dict(x=location['x'],y=location['y'])
    walls=[x for x in environment.get('boundaries',[]) if x['role']=='wall'];floors=[x for x in environment.get('boundaries',[]) if x['role']=='floor' and x.get('colliders')]
    left=[x['bounds_max']['x'] for x in walls if x['bounds_max']['x']<location['x']];right=[x['bounds_min']['x'] for x in walls if x['bounds_min']['x']>location['x']]
    if not(left and right and floors and location.get('collider_known')):return value
    x,y,hw,hh=map(location.get,('x','y','half_width','half_height'));floor=max(f['bounds_max']['y'] for f in floors)
    dl=x-hw-max(left);dr=min(right)-x-hw;db=y-hh-floor
    value.update(geometry_known=True,left_aabb_gap=dl,right_aabb_gap=dr,bottom_aabb_gap=db,corner_threshold_x=hw,corner_threshold_y=hh,corner=(min(dl,dr)<=hw and db<=hh),corner_side='left' if dl<=dr else 'right',geometry_definition='Signed AABB gap to boundary AABBs; corner means wall gap<=half_width AND floor gap<=half_height. Analysis label only, not a contact test or reward.')
    return value

def audit_attempt(folder,job):
    folder=Path(folder);path=folder/'game_00.jsonl';rows=[];steps=[];events=[];seen=set();last={};errors=[];metadata=load_environment(folder,'game_00') if (folder/'metadata/game_00.json').exists() else None
    if path.exists():
        with path.open(encoding='utf-8') as f:
            for line in f:
                try:row=json.loads(line)
                except ValueError:errors.append('partial/corrupt JSONL record; not usable as natural GO');break
                last=row;small=slim(row)
                if row.get('state'):small['state']['episode_events']=row['state'].get('episode_events')
                rows.append(small)
                if row.get('event')=='worker_error':errors.append(row.get('error','worker error'))
                state=row.get('state')or row.get('last_observed_state')or{};snap=state.get('episode_events')or{}
                if snap.get('source')=='actual_game' and snap.get('known'):
                    for event in snap['events']:
                        key=(row.get('episode_id'),event['event_id'])
                        if key not in seen:
                            seen.add(key);events.append(dict(episode_id=row.get('episode_id'),source='actual_game',action_trace='game_00.jsonl',**event_geometry(event,metadata['environment'] if metadata else {})))
                if row.get('event')!='transition':continue
                info=row['info'];p=info.get('planning')or{};m=p.get('mcts')or{};root=next((n for n in m.get('nodes',[]) if n['depth']==0),{})
                success=bool(info.get('drop_success'));selected=p.get('selected_x')
                if success and (selected is None or abs(info.get('applied_normalized_x',-99)-selected)>1e-4):errors.append('Selected drop coordinate mismatch')
                if not m or m.get('requested_iterations')!=job['settings']['mcts_iterations'] or m.get('max_depth')!=job['profile']['depth']:errors.append('Search settings/report mismatch')
                step=dict(action_id=row['action_id'],turn=row.get('turn'),score=state.get('score'),reward=row['reward'],between_steps_reward=row.get('between_steps_reward'),selected_x=selected,applied_x=info.get('applied_x'),drop_success=success,requested_iterations=job['profile']['iterations'],actual_iterations=m.get('completed_iterations'),depth=m.get('max_depth'),elapsed_ms=m.get('elapsed_ms'),stop_reason=m.get('budget_stop_reason'),time_limit_reached=(m.get('budget_stop_reason')=='time_limit' or (m.get('time_limit_ms',0)>0 and m.get('elapsed_ms',0)>=m['time_limit_ms'])),time_overrun_ms=m.get('time_overrun_ms'),physics_ticks=m.get('total_physics_ticks'),root_actions=root.get('actions'),depth_metrics=m.get('depth_metrics'),prediction_scenes=state.get('prediction_scenes'),prediction_pending_unloads=state.get('prediction_pending_unloads'),lifetime=m.get('lifetime_end'))
                steps.append(step)
    natural=last.get('event')=='episode_end' and last.get('reason')=='game_over' and last.get('game_over') is True and last.get('truncated') is False
    if natural and metadata is None:errors.append('Missing environment catalog')
    if metadata and (metadata['environment'].get('rules_version')!=RULES or abs(metadata['environment'].get('game_over_screen_ratio',0)-.83)>1e-5):errors.append('Wrong physical environment')
    if natural and not errors:
        try:validate_episode(rows)
        except (ValueError,KeyError,TypeError) as e:errors.append(str(e))
    if rows:
        from episode_events import audit_events
        try:audit_events(rows)
        except (ValueError,KeyError,TypeError) as e:errors.append('Event audit: '+str(e))
    result=dict(job=job['index'],game_seed=job['game_seed'],search_seed=job['search_seed'],profile=job['profile'],natural_go=natural,valid_for_return_learning=natural and not errors,final_score=last.get('final_score') if natural else None,last_observed_score=last.get('last_observed_score',((last.get('state')or{}).get('score'))),steps=len(steps),drops=sum(s['drop_success'] for s in steps),wall_seconds=last.get('wall_seconds'),end_reason=last.get('reason',last.get('event','missing_log')),errors=errors,environment_id=metadata['environment_id'] if metadata else None,player_sha256=None,mean_thinking_ms=sum(s['elapsed_ms']or 0 for s in steps)/max(1,len(steps)),total_thinking_ms=sum(s['elapsed_ms']or 0 for s in steps),watermelon_events=sum(e['kind']=='watermelon_created' for e in events),double_events=sum(e['kind']=='double_watermelon' for e in events),events_known=any((r.get('state',{}).get('episode_events')or{}).get('known') for r in rows))
    run=folder/'run.json'
    if run.exists():result['player_sha256']=json.loads(run.read_text())['exe_sha256']
    for name,values in [('decisions.jsonl',steps),('actual_events.jsonl',events)]:
        target=folder/name
        if not target.exists():
            pending=target.with_suffix(target.suffix+'.pending')
            with pending.open('w',encoding='utf-8') as f:
                for value in values:f.write(json.dumps(value,allow_nan=False)+'\n')
                f.flush();os.fsync(f.fileno())
            os.replace(pending,target)
    return result

def run_job(config,job,slot,folder,stop):
    began=time.monotonic()
    try:
        run_parallel(config['exe'],folder,games=1,episodes=1,max_steps=config['max_steps'],base_port=config['base_port']+slot*2,seed=job['game_seed'],headless=True,settings=job['settings'],main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version=RULES,step_timeout=config['communication_timeout'],episode_events=True,external_stop=stop)
        result=audit_attempt(folder,job)
    except Exception as e:result=dict(job=job['index'],game_seed=job['game_seed'],search_seed=job['search_seed'],profile=job['profile'],natural_go=False,valid_for_return_learning=False,final_score=None,steps=0,errors=[type(e).__name__+': '+str(e)],end_reason='collector_error')
    result.update(attempt=str(Path(folder).resolve()),elapsed_seconds=time.monotonic()-began);atomic_json(Path(folder).parent/(Path(folder).name+'_result.json'),result);return result

def summarize(output):
    out=Path(output);results=[]
    for job in sorted((out/'jobs').glob('job_*')):
        attempts=sorted(job.glob('attempt_*_result.json'))
        if attempts:results.append(json.loads(attempts[-1].read_text()))
    good=[r for r in results if r.get('valid_for_return_learning')];scores=[r['final_score'] for r in good];seeds=[r['game_seed'] for r in results]
    unfinalized=[str(a.resolve()) for d in (out/'jobs').glob('job_*') for a in d.glob('attempt_*') if a.is_dir() and not (d/(a.name+'_result.json')).exists()]
    summary=dict(unfinalized_attempts=unfinalized,jobs=len(results),natural_go=sum(r['natural_go'] for r in results),usable_games=len(good),incomplete_or_error=len(results)-len(good),mean_score=sum(scores)/len(scores) if scores else None,max_score=max(scores) if scores else None,total_steps=sum(r.get('steps',0) for r in results),seed_duplicates=len(seeds)-len(set(seeds)),games=results)
    atomic_json(out/'collection_summary.json',summary)
    with (out/'games.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['job','game_seed','search_seed','natural_go','valid_for_return_learning','final_score','steps','end_reason','elapsed_seconds','attempt','depth','requested_iterations','mean_thinking_ms','watermelon_events','double_events','environment_id'];w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(dict(r,depth=r.get('profile',{}).get('depth'),requested_iterations=r.get('profile',{}).get('iterations')) for r in results)
    return summary

def collect(config,output,resume=False,runner=run_job):
    out=Path(output)
    if not resume:out.mkdir(parents=True,exist_ok=False)
    with exclusive_lock(out/'collector.lock'):
        if resume:
            saved=json.loads((out/'collection.json').read_text());config=saved
            if player_identity(config['exe'])!=config.get('player_files',player_identity(config['exe'])) or hashlib.sha256(Path(config['exe']).read_bytes()).hexdigest()!=config['exe_sha256']:raise ValueError('Player changed; cannot resume the same collection')
        else:
            if type(config['workers']) is not int or not 1<=config['workers']<=4:raise ValueError('Collection supports 1..4 independent Players')
            if not 0<config['think_seconds']<=240 or not config['think_seconds']+60<=config['communication_timeout']<=720:raise ValueError('Invalid thinking/step timeout')
            if type(config['max_steps']) is not int or config['max_steps']<1:raise ValueError('Invalid max steps')
            if not config['profiles']:raise ValueError('Empty collection profiles')
            if not 0<config['hours']<=168 or config['max_jobs']<1 or not 0<=config['game_seed']<=2147483646-config['max_jobs']:raise ValueError('Invalid collection duration/seed range')
            from .parallel_play import check_ports,worker_specs
            check_ports(worker_specs(config['workers'],config['base_port'],config['game_seed']))
            for p in config['profiles']:
                settings(p,0,config['think_seconds'])
                if not isinstance(p['weight'],(int,float)) or not math.isfinite(p['weight']) or p['weight']<=0:raise ValueError('Invalid profile weight')
            config=dict(config,exe=str(Path(config['exe']).resolve()),exe_sha256=hashlib.sha256(Path(config['exe']).read_bytes()).hexdigest(),rules_version=RULES,player_files=player_identity(config['exe']),version='step8ae-collector-v1',allocation='Per-game weighted profile, independent game/search seeds; no selection by final score',stop_policy=config['shutdown'])
            atomic_json(out/'collection.json',config)
        (out/'jobs').mkdir(exist_ok=True);runtime=out/'runtime.json';used=json.loads(runtime.read_text()).get('used_seconds',0) if runtime.exists() else 0;start=time.monotonic();deadline=start+max(0,config['hours']*3600-used);stop=threading.Event();active={};consecutive=0;next_index=0;completed=0;interrupted=False;last_sample=0
        # Already-started jobs without a durable result are retried into a NEW attempt. Old raw partial logs remain intact.
        def allocate(slot):
            nonlocal next_index
            while next_index<config['max_jobs']:
                index=next_index;next_index+=1;d=out/'jobs'/f'job_{index:06d}';d.mkdir(exist_ok=True);job_path=d/'job.json'
                if job_path.exists():job=json.loads(job_path.read_text())
                else:job=choose_job(config,index);atomic_json(job_path,job)
                if list(d.glob('attempt_*_result.json')):continue
                previous=sorted(p for p in d.glob('attempt_*') if p.is_dir())
                if previous and (previous[-1]/'game_00.jsonl').exists() and tail(previous[-1]/'game_00.jsonl').get('event') in ('episode_end','worker_error'):
                    recovered=audit_attempt(previous[-1],job);recovered.update(attempt=str(previous[-1].resolve()),elapsed_seconds=None,recovered_after_interruption=True);atomic_json(d/(previous[-1].name+'_result.json'),recovered)
                    continue
                number=max([int(p.name.split('_')[1]) for p in previous]+[-1])+1
                return job,d/f'attempt_{number:03d}'
            return None
        with (out/'collector_events.jsonl').open('a',encoding='utf-8') as event_log,ThreadPoolExecutor(max_workers=config['workers']) as pool:
            def emit(event):event_log.write(json.dumps(dict(utc=time.time(),**event))+'\n');event_log.flush();os.fsync(event_log.fileno());print(json.dumps(event),flush=True)
            emit(dict(event='session_start',resume=resume,used_seconds=used))
            try:
                while True:
                    expired=time.monotonic()>=deadline
                    if expired and config['shutdown']=='boundary':stop.set()
                    if not expired and not stop.is_set():
                        occupied={v[0] for v in active.values()}
                        for slot in range(config['workers']):
                            if slot in occupied:continue
                            item=allocate(slot)
                            if item:
                                job,folder=item;emit(dict(event='job_start',job=job['index'],slot=slot,game_seed=job['game_seed'],search_seed=job['search_seed'],profile=job['profile'],attempt=str(folder)));active[pool.submit(runner,config,job,slot,folder,stop)]=(slot,job,folder)
                    if not active:break
                    done,_=wait(active,timeout=.25,return_when=FIRST_COMPLETED)
                    for future in done:
                        slot,job,folder=active.pop(future);result=future.result();completed+=1;consecutive=consecutive+1 if result.get('errors') else 0;emit(dict(event='job_end',job=job['index'],natural_go=result['natural_go'],valid_for_return_learning=result['valid_for_return_learning'],score=result.get('final_score'),errors=result.get('errors',[])));summarize(out)
                        if consecutive>=config.get('max_consecutive_errors',3):stop.set();emit(dict(event='circuit_breaker',reason='consecutive errors'))
                    if time.monotonic()-last_sample>=5:
                        last_sample=time.monotonic()
                        with (out/'resources.jsonl').open('a',encoding='utf-8') as resource:
                            for slot,job,folder in active.values():
                                try:
                                    run=json.loads((folder/'run.json').read_text());memory=process_memory(run['workers'][0]['pid']);resource.write(json.dumps(dict(utc=time.time(),job=job['index'],slot=slot,memory=memory))+'\n')
                                except (OSError,ValueError,KeyError):pass
                    atomic_json(runtime,dict(used_seconds=used+time.monotonic()-start,active_jobs=[j['index'] for _,j,_ in active.values()],budget_expired=expired))
            except KeyboardInterrupt:
                interrupted=True;stop.set();emit(dict(event='interrupt',reason='stop new actions after current step; wait for pending response up to configured step timeout'))
                for future in active:
                    future.result()
            finally:
                stop.set();atomic_json(runtime,dict(used_seconds=used+time.monotonic()-start,budget_expired=time.monotonic()>=deadline,interrupted=interrupted))
        return summarize(out)
