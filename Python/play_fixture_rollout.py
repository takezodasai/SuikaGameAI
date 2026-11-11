"""One bounded learned-rollout continuation of an explicitly approximate fixture."""
import argparse,json,subprocess,time
from pathlib import Path
from watermelon_lab import ROOT,sha,write,summarize,public_difference
from compare_watermelon_dynamic import active_players
from rollout_selfplay import reservations

def run(fixture,out,future,seconds=600,drops=1000,port=44420):
    from suika_ai.parallel_play import check_ports,worker_specs
    if active_players():raise RuntimeError('An existing Player is active; leave collection untouched')
    if not 0<seconds<=600 or not 1<=drops<=1000:raise ValueError('Bounded fixture experiment only')
    fixture=Path(fixture).resolve();f=json.loads(fixture.read_text());reserved,prefixes=reservations()
    if future in reserved or f.get('source_seed') in reserved or f.get('source_initial8') in prefixes:raise ValueError('Protected Test19 group')
    check_ports(worker_specs(1,port));out=Path(out).resolve();out.mkdir(exist_ok=False,parents=True)
    exe=ROOT/'Unity/Builds/PolicySelfPlay_01/SuikaGameAI.exe';model=ROOT/'Python/outputs/learned_rollout_01/training/model.json'
    cfg=dict(fixture=str(fixture),output=str(out/'trace.jsonl'),policy_model=str(model),mode='learned',mixture=.5,normal_start=False,final_selection='legacy',game_seed=future,future_seed=future,search_seed=8191,iterations=256,depth=4,max_drops=drops,max_seconds=seconds,first_x=-1)
    write(out/'config.json',cfg);write(out/'provenance.json',dict(fixture_sha256=sha(fixture),actor_sha256=sha(model),source_seed=f.get('source_seed'),source_initial8=f.get('source_initial8'),exact_historical_restore=False,selection_is_experiment_only=True))
    args=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(future),'--suika-listen-port',str(port),'--suika-python-port',str(port+1),'-suikaRuntimeProbe',str(out/'runtime.jsonl'),'-suikaPolicySelfPlayLab',str(out/'config.json'),'-logFile',str(out/'player.log')]
    write(out/'launch.json',dict(command=args,exe_sha256=sha(exe),assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')))
    proc=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS);began=time.monotonic();error=None
    try:
        while proc.poll() is None:
            if time.monotonic()-began>seconds+25:error='process_timeout';break
            time.sleep(.25)
    except KeyboardInterrupt:error='interrupted'
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
    rows=[]
    if (out/'trace.jsonl').exists():
        for line in (out/'trace.jsonl').read_text().splitlines():
            try:rows.append(json.loads(line))
            except ValueError:error=error or 'partial_trace'
    result=summarize(rows)
    for r in rows:
        if r['evt']=='decision':
            if r['search']['completed_iterations']!=256 or not r['search']['source_unchanged'] or r['rollout']['model_sha256']!=sha(model):error='search_audit'
    result.update(exit_code=proc.returncode,process_error=error,wall_seconds=time.monotonic()-began,future_seed=future,approximate_fixture=True)
    result['natural_go']=bool(result['natural_go'] and not error and not result['errors'] and proc.returncode==0)
    if result['root']:result['initial_public_difference']=public_difference(f['snapshot'],result['root']['state'])
    write(out/'result.json',result);print(json.dumps(dict(output=str(out),natural_go=result['natural_go'],wall_seconds=result['wall_seconds'],error=error,end={k:result['end'].get(k) for k in ['reason','score','additional_score','accepted_drops','new_watermelons','two_watermelons_present','double_watermelons']} if result['end'] else None),indent=2),flush=True)
    if error or result['errors'] or proc.returncode:raise RuntimeError('Technical error saved; no performance label')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--future-seed',type=int,required=True);p.add_argument('--seconds',type=float,default=600);p.add_argument('--drops',type=int,default=1000);p.add_argument('--port',type=int,default=44420);a=p.parse_args();run(a.fixture,a.output,a.future_seed,a.seconds,a.drops,a.port)
