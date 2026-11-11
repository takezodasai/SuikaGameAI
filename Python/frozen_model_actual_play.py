"""Bounded, isolated frozen-model actual games. No training or production changes."""
import argparse, hashlib, json, os, statistics, subprocess, time
from collections import Counter
from pathlib import Path
import numpy as np
import torch
from action_decision_models import Models
from qv_branch_assessment import inputs
from compare_candidate_value import predict
from run_fresh_continuation import read_rows
from suika_ai.parallel_play import check_ports, worker_specs

ROOT=Path('Python/outputs/frozen_model_actual_01')
EXE=Path('Unity/Builds/FrozenModels_02/SuikaGameAI.exe')
XS=[0.,.25,.5,.75,1.]

def write(path,obj):
    with Path(path).open('x',encoding='utf8') as f:json.dump(obj,f,indent=2,allow_nan=False)

def choose(values,candidates,safety):
    allowed=[i for i,c in enumerate(candidates) if c['drop'] and not c['go']] if safety else list(range(len(values)))
    if not allowed:allowed=[i for i,c in enumerate(candidates) if c['drop']] or list(range(len(values)))
    return max(allowed,key=lambda i:(values[i],-i))

def scores(models,request):
    """Only public request state. Future seeds/RNG/replay hashes never enter here."""
    start=time.perf_counter();encoded=inputs(request['state'],True)
    with torch.inference_mode():
        batch=[a.expand(5,*a.shape[1:]) for a in encoded]
        qs=[(m(*batch,torch.tensor(XS))*1000).tolist() for m in models.q]
    q=np.mean(qs,axis=0).tolist();qms=(time.perf_counter()-start)*1000
    start=time.perf_counter();v=[];individual=[]
    for c in request['candidates']:
        if c['after']['game_over']:
            predictions=[float(c['reward'])]*len(models.v) # measured GO has zero future value
        else:
            predictions=[]
            for m in models.v:
                types=request['public_spawn_types'] if c['drop'] else [c['after']['next_fruit_type']]
                predictions.append(c['reward']+sum(predict(m,'geometry',dict(c['after'],next_fruit_type=t)) for t in types)/len(types))
        individual.append(predictions);v.append(float(np.mean(predictions)))
    vms=(time.perf_counter()-start)*1000
    heuristic=[c['heuristic'] for c in request['candidates']]
    choices=dict(B=XS[choose(q,request['candidates'],False)],C=XS[choose(v,request['candidates'],True)],D=XS[choose(heuristic,request['candidates'],True)])
    return dict(id=request['id'],choices=choices,Q=q,V=v,Q_seeds=qs,V_seeds=individual,Q_ms=qms,V_ms=vms,heuristic=heuristic,
        predicted_GO=[c['go'] for c in request['candidates']],state=request['state'],physics_ms=request['physics_ms'],
        information='No hidden future. V at 25-post-drop-tick observation; C NEXT marginalized over actual spawn slots; GO future=0. Q exact training pre-input missingness retained.')

def summarize_game(folder,process_seconds,exit_code):
    rows=list(read_rows(folder/'trace.jsonl'));end=next((r for r in reversed(rows) if r['evt']=='end'),None)
    actions=[r for r in rows if r['evt']=='action'];decisions=[r for r in rows if r['evt']=='decision'];errors=[r['error'] for r in rows if r['evt']=='error'];start=next(r for r in rows if r['evt']=='start')
    natural=bool(end and end['game_over'] and not end['truncated'] and end['reason']=='natural_go' and not errors and exit_code==0)
    public=[start['state']['current_fruit']['type'],start['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in actions]
    conserved=bool(end and end['score']==end['state']['score'] and all(b['score']>=a['score'] for a,b in zip([start]+actions,actions+([end] if end else []))))
    ms=[r['actor_ms'] for r in decisions];xs=[r['command']['x'] for r in decisions];preds=[json.loads(p.read_text()) for p in sorted((folder/'bridge').glob('prediction_*.json'))]
    disagreements=[dict(turn=r['id'],choices=r['choices'],score=r['state']['score'],fruits=len(r['state']['fruits'])) for r in preds if len(set(r['choices'].values()))>1]
    result=dict(mode=json.loads((folder/'config.json').read_text())['mode'],natural_go=natural,reason=end['reason'] if end else 'no_end',score=end['score'] if end else None,drops=end['drops'] if end else len(actions),
        wall_seconds=process_seconds,game_wall_seconds=end['wall_ms']/1000 if end else None,mean_actor_ms=statistics.mean(ms) if ms else None,total_actor_ms=sum(ms),
        actual_events=end['actual_events'] if end else None,final_state=end['state'] if end else None,errors=errors,exit_code=exit_code,score_conserved=conserved,
        public_series=public,selected_x_histogram=dict(Counter(map(str,xs))),disagreements=disagreements,
        max_retained_scenes=max((r.get('retained_scenes',0) for r in actions),default=0),final_retained_scenes=end['retained_scenes'] if end else None,
        note='All shadow physics/models are instrumentation; actor_ms excludes other methods/shadow and file IPC. Wall time includes them. No GUI, game paused during decision for every policy.')
    write(folder/'result.json',result);return result

def run_game(folder,cfg,models,port=44600):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);bridge=folder/'bridge';bridge.mkdir();cfg=dict(cfg,output=str((folder/'trace.jsonl').resolve()),bridge=str(bridge.resolve()))
    write(folder/'config.json',cfg);check_ports(worker_specs(1,port))
    command=[str(EXE.resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(cfg['seed']),'--suika-listen-port',str(port),'--suika-python-port',str(port+1),'-suikaFrozenModelPlay',str((folder/'config.json').resolve()),'-logFile',str((folder/'player.log').resolve())]
    write(folder/'launch.json',dict(command=command,seconds_cap=cfg['max_seconds']))
    child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS);started=time.monotonic();seen=set()
    try:
        while child.poll() is None:
            for p in bridge.glob('request_*.json'):
                if p.name in seen:continue
                req=json.loads(p.read_text());prediction=scores(models,req);write(bridge/f"prediction_{req['id']:04d}.json",prediction)
                mode=cfg['mode'];x=req['native_x'] if mode in ['A','D'] else prediction['choices'][mode]
                inference_ms=prediction['Q_ms'] if mode=='B' else prediction['V_ms'] if mode=='C' else 0
                target=bridge/f"answer_{req['id']}.json";write(str(target)+'.tmp',dict(id=req['id'],x=x,inference_ms=inference_ms));os.replace(str(target)+'.tmp',target);seen.add(p.name)
            if time.monotonic()-started>cfg['max_seconds']+35:raise TimeoutError('Own process safety deadline; not natural GO')
            time.sleep(.005)
    finally:
        if child.poll() is None:child.terminate();child.wait(10)
    result=summarize_game(folder,time.monotonic()-started,child.returncode)
    print(json.dumps(dict(folder=str(folder),mode=cfg['mode'],natural_go=result['natural_go'],score=result['score'],drops=result['drops'],seconds=result['wall_seconds'],errors=result['errors'])),flush=True)
    return result

def prepare():
    ROOT.mkdir(exist_ok=False);old=json.loads(Path('Python/outputs/action_decision_validation_01/plan.json').read_text());test=json.loads(Path('Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text());seeds=[882610501,882610502]
    assert not set(seeds)&{e['seed'] for e in test['episodes']}
    models=old['models'];sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for ext in ['*.cs','*.py'] for root in [Path('Unity/Assets/Scenes/Script'),Path('Python/src')] for p in root.rglob(ext)}
    write(ROOT/'plan.json',dict(seeds=seeds,orders=[['B','C','D','A'],['A','D','C','B']],models=models,exe=str(EXE),natural_game_budget_seconds=1800,game_cap_seconds=450,branch_budget_seconds=600,
        candidates=XS,model_ensemble='Three frozen original training seeds arithmetic mean',MCTS=dict(iterations=128,depth=4,seed=8191,rollout='random',chance='legacy'),
        independent_test19_used=False,pause='All actors pause game time while deciding, fixed physics step unchanged',source_hashes=sources))

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','smoke','games']);a=p.parse_args()
    if a.mode=='prepare':prepare();return
    models=Models();plan=json.loads((ROOT/'plan.json').read_text())
    if a.mode=='smoke':
        for mode in ['B','C','D','A']:run_game(ROOT/'smoke_02'/mode,dict(seed=882610500,mode=mode,max_seconds=40,max_drops=3),models)
        return
    started=time.monotonic()
    for seed,order in zip(plan['seeds'],plan['orders']):
        for mode in order:
            left=plan['natural_game_budget_seconds']-(time.monotonic()-started)
            if left<30:return
            folder=ROOT/f'seed_{seed}'/mode
            if folder.exists():continue
            run_game(folder,dict(seed=seed,mode=mode,max_seconds=min(plan['game_cap_seconds'],left),max_drops=600),models)

if __name__=='__main__':main()
