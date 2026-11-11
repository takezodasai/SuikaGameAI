"""Independent final-action adapter; runs the original MCTS unchanged every turn."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from watermelon_lab import ROOT,sha,write,summarize
from compare_watermelon_dynamic import active_players
from staged_action_experiment import choose_alternative


def validate_decision(row,selector):
    choice=row['final_selection'];expected=None
    try:expected=choose_alternative(row)
    except ValueError:pass
    assert row['search']['completed_iterations']==128
    assert sum(c['visits'] for c in row['search']['root'])==128
    assert row['search']['source_unchanged']
    if expected is not None and expected['alternative_x']!=expected['recommended_x']:
        assert choice['has_alternative'] and choice['alternative_index']==expected['alternative_index']
        x=expected['alternative_x'] if selector=='alternative' else expected['recommended_x']
    else:
        assert not choice['has_alternative'];x=row['planning']['selected_x']
    assert choice['actual_x']==x and row['command']['x']==x
    return choice['has_alternative']


def run_game(out,selector,seed,seconds=600,drops=1000,view=False):
    from suika_ai.parallel_play import check_ports,worker_specs
    if active_players():raise RuntimeError('Existing Player active; leave collection untouched')
    if selector not in ['legacy','alternative']:raise ValueError(selector)
    if not 0<seconds<=600 or not 1<=drops<=1000:raise ValueError('Bounded experiment: <=600 seconds and <=1000 drops')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    reserved=json.loads((ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    if seed in {r['seed'] for r in reserved}:raise ValueError('Reserved Test19 seed')
    check_ports(worker_specs(1,43640))
    exe=ROOT/'Unity/Builds/AlternativeCandidate_01/SuikaGameAI.exe'
    config=dict(output=str((out/'trace.jsonl').resolve()),mode='baseline',final_selection=selector,normal_start=True,
        game_seed=seed,future_seed=seed,search_seed=8191,iterations=128,depth=4,max_drops=drops,max_seconds=seconds,first_x=-1)
    write(out/'config.json',config)
    args=[str(exe)]+([] if view else ['-batchmode','-nographics'])+['--suika-audio','0','--suika-events','1',
        '--suika-seed',str(seed),'--suika-listen-port','43640','--suika-python-port','43641',
        '-suikaRuntimeProbe',str((out/'runtime.jsonl').resolve()),'-suikaAlternativeActionLab',str((out/'config.json').resolve()),
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
        choices=[validate_decision(r,selector) for r in ds]
    except (AssertionError,KeyError):error=error or 'selection_audit_failed'
    result.update(selector=selector,game_seed=seed,search_seed=8191,wall_seconds=time.monotonic()-start,
        exit_code=proc.returncode,process_error=error,decisions=len(ds),eligible_B_decisions=sum(choices),
        fallback_decisions=len(ds)-sum(choices),policy_scope='every decision, not first-action-only branch')
    result['natural_go']=bool(result['natural_go'] and not error and not result['errors'] and proc.returncode==0)
    write(out/'result.json',result)
    print(json.dumps(dict(output=str(out),selector=selector,natural_go=result['natural_go'],
        score=result['end']['score'] if result['end'] else None,drops=result['end']['accepted_drops'] if result['end'] else None,
        seconds=result['wall_seconds'],error=error)),flush=True)
    if error or result['errors'] or proc.returncode:raise RuntimeError('Technical error saved; do not substitute seed')
    return result,rs


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--selector',choices=['legacy','alternative'],default='legacy');p.add_argument('--seed',type=int,required=True)
    p.add_argument('--seconds',type=float,default=600);p.add_argument('--max-drops',type=int,default=1000);p.add_argument('--view',action='store_true')
    a=p.parse_args();run_game(a.output,a.selector,a.seed,a.seconds,a.max_drops,a.view)
