"""Preregistered twelve development-seed pairs; frozen model and legacy heuristic."""
import argparse,hashlib,json,os,random,shutil,subprocess,time
from pathlib import Path
from collections import Counter
import numpy as np
import torch
from action_decision_models import Models
from frozen_model_actual_play import scores,summarize_game,write,XS
from suika_ai.parallel_play import check_ports,worker_specs
from collection_concurrency_probe import active_players

ROOT=Path('Python/outputs/frozen_v_pair_12_01')
EXE=Path('Unity/Builds/FrozenVPair_01/SuikaGameAI.exe')
SCORING_FILES=['Python/frozen_model_actual_play.py','Python/action_decision_models.py','Python/qv_branch_assessment.py','Python/compare_candidate_value.py','Python/src/suika_ai/value_data.py','Python/src/suika_ai/long_value_model.py','Python/qv_experiment.py']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def seed_plan():
    reserved=json.loads(Path('Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
    used={e['seed'] for e in reserved}|{882610501,882610502,882610391,882610392}
    rng=random.Random(2026103101);seeds=[]
    while len(seeds)<12:
        s=rng.randrange(880000000,899000000)
        if s not in used and s not in seeds:seeds.append(s)
    return seeds,reserved

def prepare():
    ROOT.mkdir(exist_ok=False);seeds,reserved=seed_plan();old=json.loads(Path('Python/outputs/frozen_model_actual_01/plan.json').read_text())
    plan=dict(version='frozen-v-paired-12-v1',seeds=seeds,orders=[['D','C'] if i%2==0 else ['C','D'] for i in range(12)],conditions=dict(D='Existing heuristic StepPlanner.Choose, shared five native predictions',C='Frozen three-V arithmetic mean, previous scores/choose unchanged'),
        models=old['models'],scoring_files={p:sha(p) for p in SCORING_FILES},exe=str(EXE),candidates=XS,post_drop_ticks=25,game_cap_seconds=540,total_seconds=10800,max_drops=1000,
        execution='one game at a time; balanced condition order; no MCTS games or new training',reserved_seeds=[e['seed'] for e in reserved],reserved_prefixes=[e['initial_sequence'] for e in reserved],
        reserve_guard='If observed initial8 matches reserved Test19, abort before selecting action7, quarantine entire seed, do not replace it.',
        metrics=['natural-GO score','paired V-minus-H score, wins/ties','mean/median/min/max','actual watermelon rate','actual drops','actor mean/p95 ms','game wall time','Python inference/service and bridge residual','predicted-GO selection','GO state','realized vs predicted remaining return','density and position diagnostics'],
        inference='V/inputs/checkpoints/future NEXT marginalization unchanged. Heuristic uses original Choose including ties. Prior all-GO V fallback remains unchanged and differs from heuristic.',
        statistics='All completed natural games descriptive; primary comparison only complete valid paired seeds, seed-pair bootstrap20000 seed2026103102. Decisions are not independent score trials. Initial8 collisions among development seeds cluster bootstrap together.',
        no_replacements=True,no_score_based_retries=True,early_stop='Only safety, budget, disk<2GiB, active unrelated Player or invariant failure; retain all records. No performance-based stop.')
    write(ROOT/'plan.json',plan);print(json.dumps(dict(seeds=seeds,total_seconds=plan['total_seconds'],game_cap_seconds=540)),flush=True)

def verify(plan):
    for p,h in dict(plan['models'],**plan['scoring_files']).items():
        if sha(p)!=h:raise ValueError('Frozen asset changed: '+p)

def reserve_collision(sequence,plan):return len(sequence)>=8 and ','.join(map(str,sequence[:8])) in plan['reserved_prefixes']

def game(folder,cfg,models,plan):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);bridge=folder/'bridge';bridge.mkdir();cfg=dict(cfg,output=str((folder/'trace.jsonl').resolve()),bridge=str(bridge.resolve()))
    write(folder/'config.json',cfg);check_ports(worker_specs(1,44800));cmd=[str(EXE.resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(cfg['seed']),'--suika-listen-port','44800','--suika-python-port','44801','-suikaFrozenPair',str((folder/'config.json').resolve()),'-logFile',str((folder/'player.log').resolve())]
    write(folder/'launch.json',dict(command=cmd,exe_sha=sha(EXE),assembly_sha=sha(EXE.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')))
    child=subprocess.Popen(cmd,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS);started=time.monotonic();seen=set();sequence=[];failure=None;services=[]
    try:
        while child.poll() is None:
            for p in bridge.glob('request_*.json'):
                if p.name in seen:continue
                begin=time.perf_counter();r=json.loads(p.read_text());s=r['state']
                if not sequence:sequence=[s['current_fruit']['type'],s['next_fruit_type']]
                elif r['id']<=7:sequence.append(s['next_fruit_type'])
                if reserve_collision(sequence,plan):raise RuntimeError('reserved_initial8_quarantine')
                if cfg['mode']=='C':
                    prediction=scores(models,r);prediction['phase']='live_V_actor';write(bridge/f"prediction_{r['id']:04d}.json",prediction);x=prediction['choices']['C'];inference=prediction['V_ms']
                else:x=r['native_x'];inference=0.
                answer=bridge/f"answer_{r['id']}.json";write(str(answer)+'.tmp',dict(id=r['id'],x=x,inference_ms=inference));os.replace(str(answer)+'.tmp',answer);seen.add(p.name)
                timing=dict(id=r['id'],mode=cfg['mode'],service_ms=(time.perf_counter()-begin)*1000,V_inference_ms=inference,source='live_response');services.append(timing);write(bridge/f"service_{r['id']:04d}.json",timing)
            if time.monotonic()-started>cfg['max_seconds']+35:raise TimeoutError('owned_safety_deadline')
            time.sleep(.005)
    except BaseException as e:
        failure=type(e).__name__+': '+str(e)
        write(folder/'failure.json',dict(error=failure,elapsed=time.monotonic()-started,valid_natural_go=False))
    finally:
        if child.poll() is None:child.terminate();child.wait(10)
    elapsed=time.monotonic()-started
    # Counterfactual V scores on heuristic boards are computed AFTER process exit,
    # not on the heuristic's live response path. Raw requests are never rewritten.
    offline=time.monotonic()
    if cfg['mode']=='D' and failure is None:
        for p in sorted(bridge.glob('request_*.json'),key=lambda p:int(p.stem.split('_')[1])):
            r=json.loads(p.read_text());prediction=scores(models,r);prediction['phase']='offline_shadow_after_heuristic_exit';write(bridge/f"prediction_{r['id']:04d}.json",prediction)
    offline_seconds=time.monotonic()-offline
    try:result=summarize_game(folder,elapsed,child.returncode)
    except Exception as e:
        result=dict(natural_go=False,mode=cfg['mode'],score=None,errors=[str(e)],reason=failure or 'incomplete_trace',wall_seconds=elapsed)
        write(folder/'incomplete_result.json',result)
    # Additional immutable metadata avoids changing the previous result schema.
    write(folder/'comparison_metadata.json',dict(seed=cfg['seed'],condition=cfg['mode'],live_services=len(services),failure=failure,quarantined=bool(failure and 'reserved_initial8' in failure),initial8=sequence[:8],offline_shadow_seconds=offline_seconds,
        note='Actor and wall times exclude offline shadow work. D native heuristic and C frozen V share identical five-prediction loop. File IPC residual includes polling, not pure transport latency.'))
    print(json.dumps(dict(event='game_end',seed=cfg['seed'],condition=cfg['mode'],natural_go=result['natural_go'],score=result.get('score'),seconds=elapsed,failure=failure)),flush=True)
    return result

def validation(models,plan):
    for mode in ['D','C']:
        r=game(ROOT/'validation'/mode,dict(seed=882611099,mode=mode,max_seconds=60,max_drops=8,validate_heuristic=True),models,plan)
        rows=[json.loads(l) for l in (ROOT/'validation'/mode/'trace.jsonl').open()];checks=[r for r in rows if r['evt']=='native_plan'];assert len(checks)==8 and all(r['legacy_compatible'] for r in checks) and not r['errors']
    old=Path('Python/outputs/frozen_model_actual_01/seed_882610501/C/bridge')
    for i in [1,50,100]:
        a=scores(models,json.loads((old/f'request_{i}.json').read_text()));b=json.loads((old/f'prediction_{i:04d}.json').read_text());assert a['V']==b['V'] and a['choices']['C']==b['choices']['C']
    write(ROOT/'validation_passed.json',dict(heuristic_boards=16,heuristic_candidate_comparisons=80,exact_previous_V_requests=3,weights_and_input_unchanged=True))

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','validate','run']);a=p.parse_args()
    if a.mode=='prepare':prepare();return
    plan=json.loads((ROOT/'plan.json').read_text());verify(plan)
    if active_players():raise RuntimeError('An unrelated Player is active; no launch')
    models=Models()
    if a.mode=='validate':validation(models,plan);return
    if not (ROOT/'validation_passed.json').exists():raise ValueError('Validation must pass before formal games')
    write(ROOT/'execution_start.json',dict(plan_sha=sha(ROOT/'plan.json'),exe_sha=sha(EXE),assembly_sha=sha(EXE.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll')))
    begin=time.monotonic();completed=[]
    for index,(seed,order) in enumerate(zip(plan['seeds'],plan['orders'])):
        for mode in order:
            left=plan['total_seconds']-(time.monotonic()-begin)
            if left<plan['game_cap_seconds']+35:
                write(ROOT/'budget_stop.json',dict(next_seed=seed,next_mode=mode,remaining_seconds=left,rule='Do not launch a game without its full predeclared guard'));return
            if active_players():write(ROOT/'external_player_stop.json',dict(seed=seed,mode=mode,rule='Do not interfere with newly started collection'));return
            if shutil.disk_usage(ROOT).free<2*1024**3:write(ROOT/'disk_stop.json',dict(seed=seed,mode=mode));return
            verify(plan);folder=ROOT/f'seed_{seed}'/mode;print(json.dumps(dict(event='game_start',pair=index+1,of=12,seed=seed,condition=mode)),flush=True)
            r=game(folder,dict(seed=seed,mode=mode,max_seconds=plan['game_cap_seconds'],max_drops=plan['max_drops'],validate_heuristic=False),models,plan);completed.append(dict(seed=seed,mode=mode,natural_go=r['natural_go'],score=r.get('score')))
            with (ROOT/'progress.jsonl').open('a') as f:f.write(json.dumps(completed[-1])+'\n');f.flush();os.fsync(f.fileno())
            meta=json.loads((folder/'comparison_metadata.json').read_text())
            if meta['quarantined']:break
            if meta['failure'] or r.get('errors') or not r.get('score_conserved'):write(ROOT/'integrity_stop.json',dict(seed=seed,mode=mode,details=r));return
    write(ROOT/'execution_complete.json',dict(games=len(completed),seconds=time.monotonic()-begin))

if __name__=='__main__':main()
