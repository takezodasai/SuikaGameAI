"""Independent learned-rollout experiment; original MCTS remains available."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from watermelon_lab import ROOT,sha,write,summarize
from compare_watermelon_dynamic import active_players


def validate_decision(row,selector,model,model_sha):
    search=row['search'];assert search['completed_iterations']==128
    assert sum(c['visits'] for c in search['root'])==128 and search['source_unchanged']
    assert row['command']['x']==row['planning']['selected_x']
    if selector!='legacy':
        a=row['rollout'];m=row['search'];assert a['model_sha256']==model_sha
        assert a['rollout_calls']==a['learned_calls']+a['random_calls']+a['fallback_calls']==m['rollout_calls']
        assert a['learned_calls']==m['guided_calls']==sum(a['learned_by_depth'])
        assert sum(a['actions'])==a['learned_calls']
    return False


def run_game(out,model_path,seed,seconds=1200,drops=1000,view=False,fixture=None,selector="mixed",mixture=.5):
    from suika_ai.parallel_play import check_ports,worker_specs
    if active_players():raise RuntimeError('Existing Player active; leave collection untouched')
    if selector not in ['legacy','mixed']:raise ValueError(selector)
    if not 0<=mixture<=1:raise ValueError('Mixture must be between zero and one')
    model_path=Path(model_path).resolve();model=json.loads(model_path.read_text(encoding='utf8'));model_sha=sha(model_path)
    if not 0<seconds<=1800 or not 1<=drops<=1000:raise ValueError('Bounded experiment: <=1800 seconds and <=1000 drops')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    reserved=json.loads((ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    if seed in {r['seed'] for r in reserved}:raise ValueError('Reserved Test19 seed')
    check_ports(worker_specs(1,43740))
    exe=ROOT/'Unity/Builds/LearnedRollout_03/SuikaGameAI.exe'
    config=dict(output=str((out/'trace.jsonl').resolve()),mode='baseline' if selector=='legacy' else 'learned',policy_model=str(model_path),mixture=mixture,fixture=str(Path(fixture).resolve()) if fixture else '',final_selection="legacy",normal_start=fixture is None,
        game_seed=seed,future_seed=seed,search_seed=8191,iterations=128,depth=4,max_drops=drops,max_seconds=seconds,first_x=-1)
    write(out/'config.json',config)
    args=[str(exe)]+([] if view else ['-batchmode','-nographics'])+['--suika-audio','0','--suika-events','1',
        '--suika-seed',str(seed),'--suika-listen-port','43740','--suika-python-port','43741',
        '-suikaRuntimeProbe',str((out/'runtime.jsonl').resolve()),'-suikaLearnedRolloutLab',str((out/'config.json').resolve()),
        '-logFile',str((out/'player.log').resolve())]
    write(out/'launch.json',dict(command=args,exe_sha256=sha(exe),assembly_sha256=sha(exe.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')))
    proc=subprocess.Popen(args,creationflags=(0 if view else subprocess.CREATE_NO_WINDOW)|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    start=time.monotonic();error=None;checked=False
    try:
        while proc.poll() is None:
            if time.monotonic()-start>seconds+25:error='process_timeout';break
            path=out/'trace.jsonl'
            if not checked and path.exists():
                rs=[]
                for line in path.read_text(encoding='utf8').splitlines():
                    try:rs.append(json.loads(line))
                    except ValueError:pass
                if rs and rs[0].get('evt')=='root':
                    seq=[rs[0]['state']['current_fruit']['type'],rs[0]['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in rs if r['evt']=='release']
                    if len(seq)>=8:
                        checked=True
                        if ','.join(map(str,seq[:8])) in {r['initial_sequence'] for r in reserved}:error='reserved_initial8_quarantine';break
            time.sleep(.25)
    except KeyboardInterrupt:error='interrupted'
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
    rs=[]
    if (out/'trace.jsonl').exists():
        for line in (out/'trace.jsonl').read_text(encoding='utf8').splitlines():
            try:rs.append(json.loads(line))
            except ValueError:error=error or 'partial_trace'
    result=summarize(rs);ds=[r for r in rs if r['evt']=='decision'];choices=[]
    try:
        choices=[validate_decision(r,selector,model,model_sha) for r in ds]
    except (AssertionError,KeyError):error=error or 'selection_audit_failed'
    result.update(selector=selector,game_seed=seed,search_seed=8191,wall_seconds=time.monotonic()-start,
        exit_code=proc.returncode,process_error=error,decisions=len(ds),model_sha256=model_sha,
        final_selection_rule='original MCTS root selection unchanged',policy_scope='learned stochastic rollout mixture; final root selection unchanged')
    result['natural_go']=bool(result['natural_go'] and not error and not result['errors'] and proc.returncode==0)
    audits=[r['rollout'] for r in ds if r.get('rollout')]
    result['rollout_totals']={k:sum(a[k] for a in audits) for k in ['rollout_calls','learned_calls','random_calls','fallback_calls','inference_ms']}
    if selector=='legacy':
        calls=sum(r['search']['rollout_calls'] for r in ds)
        result['rollout_totals'].update(rollout_calls=calls,random_calls=calls)
    result['total_physics_ticks']=sum(r['search']['physics_ticks'] for r in ds)
    result['total_planning_ms']=sum(r['planning_ms'] for r in ds)
    write(out/'result.json',result)
    print(json.dumps(dict(output=str(out),selector=selector,natural_go=result['natural_go'],
        score=result['end']['score'] if result['end'] else None,drops=result['end']['accepted_drops'] if result['end'] else None,
        seconds=result['wall_seconds'],error=error)),flush=True)
    if error or result['errors'] or proc.returncode:raise RuntimeError('Technical error saved; do not substitute seed')
    return result,rs


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--selector',choices=['legacy','mixed'],default='mixed');p.add_argument('--seed',type=int,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--fixture',type=Path);p.add_argument('--seconds',type=float,default=1200);p.add_argument('--max-drops',type=int,default=1000);p.add_argument('--view',action='store_true');p.add_argument('--mixture',type=float,default=.5)
    a=p.parse_args();run_game(a.output,a.model,a.seed,a.seconds,a.max_drops,a.view,a.fixture,a.selector,a.mixture)
