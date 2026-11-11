"""Frozen public-state candidate scoring. Never accepts future stream or returns."""
import hashlib,json,subprocess,time
from pathlib import Path
import numpy as np
import torch
from action_decision_plan import ROOT,write
from qv_experiment import ActionValue
from qv_branch_assessment import inputs
from suika_ai.long_value_model import GeometryValueNetwork
from suika_ai.long_value_train import load_trained
from compare_candidate_value import expected_q,heuristic
from run_fresh_continuation import read_rows

class Models:
    def __init__(self):
        torch.set_num_threads(1);self.plan=json.loads((ROOT/'plan.json').read_text());self.q=[];self.v=[]
        for p,h in self.plan['models'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:raise ValueError('Frozen model changed')
        for kind,dest in [('Q',self.q),('V',self.v)]:
            for seed in [20261101,20261102,20261103]:
                p=Path(f'Python/outputs/qv_compare_01/latest_models/{kind}_{seed}/best.pt');r=torch.load(p,weights_only=True);m=ActionValue() if kind=='Q' else GeometryValueNetwork();m.load_state_dict(r['model']);m.eval();dest.append(m)
        self.ac,self.ac_kind,_,_=load_trained(Path('Python/outputs/step8ac_01/geometry'))

    def evaluate(self,folder,root):
        folder=Path(folder);folder.mkdir(exist_ok=False);s=root['state'];start=time.perf_counter();pre=inputs(s,True);pre_ms=(time.perf_counter()-start)*1000
        xs=self.plan['prediction_candidates'];q=[];start=time.perf_counter()
        with torch.inference_mode():
            for x in xs:q.append([float(m(*pre,torch.tensor([x]))*1000) for m in self.q])
        q_ms=(time.perf_counter()-start)*1000
        scan=np.linspace(0,1,201);start=time.perf_counter();curves=[]
        with torch.inference_mode():
            for m in self.q:
                repeat=[a.expand(201,*a.shape[1:]) for a in pre];curves.append((m(*repeat,torch.tensor(scan,dtype=torch.float32))*1000).tolist())
        scan_ms=(time.perf_counter()-start)*1000;mean=np.mean(curves,axis=0);overshoots=[]
        for a,b in zip(np.arange(0,1,.125),np.arange(.125,1.001,.125)):
            i,j=round(a*200),round(b*200);overshoots.append(float(max(0,mean[i:j+1].max()-max(mean[i],mean[j]))))
        fixture=folder/'fixture.json';snapshot=dict(s,current_fruit=dict(s['current_fruit'],y_known=False))
        write(fixture,dict(fruits=s['fruits'],score=s['score'],current_fruit_type=s['current_fruit']['type'],next_fruit_type=s['next_fruit_type'],held_x=s['current_fruit']['x'],drop_cooldown_remaining=s['drop_cooldown_remaining'],game_over_y=s['geometry'][3],snapshot=snapshot,limitation='Cold recreation, no native contact cache; default held y measured below. Not an actual restored root.'))
        cfg=folder/'config.json';raw=folder/'cold.jsonl';write(cfg,dict(fixtures=[str(fixture.resolve())],output=str(raw.resolve()),positions=xs,seeds=[314159],horizon=1,repeats=1,live=False))
        exe=Path(self.plan['Player']).resolve();start=time.perf_counter();error=None
        try:
            r=subprocess.run([str(exe),'-batchmode','-nographics','--suika-listen-port','44360','--suika-python-port','44361','-suikaRuntimeProbe',str((folder/'runtime.jsonl').resolve()),'-suikaCounterfactualProbe',str(cfg.resolve()),'-logFile',str((folder/'player.log').resolve())],timeout=20,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            if r.returncode:error='cold process exit '+str(r.returncode)
        except subprocess.TimeoutExpired:error='cold process 20s limit'
        wall_ms=(time.perf_counter()-start)*1000;pred=list(read_rows(raw)) if raw.exists() else [];rows=[];v_ms=ac_ms=heur_ms=0
        for i,x in enumerate(xs):
            p=next((r for r in pred if abs(r.get('x',-9)-x)<1e-5 and not r.get('error')),None)
            row=dict(x=x,D=float(np.mean(q[i])),D_seeds=q[i],A=None,B=None,C=None,C_seeds=[],predicted_GO=None)
            if p:
                start=time.perf_counter();row['A']=heuristic(p['first']);heur_ms+=(time.perf_counter()-start)*1000
                start=time.perf_counter();row['B']=expected_q(self.ac,self.ac_kind,p)[0];ac_ms+=(time.perf_counter()-start)*1000
                start=time.perf_counter();row['C_seeds']=[expected_q(m,'geometry',p)[0] for m in self.v];row['C']=float(np.mean(row['C_seeds']));v_ms+=(time.perf_counter()-start)*1000
                row.update(predicted_GO=p['first']['game_over'],predicted_reward=p['first']['reward'],physics_ms=p['elapsed_ms'],held_y_error=abs(p['actual_initial']['current_fruit']['y']-s['current_fruit']['y']))
            rows.append(row)
        def choose(key,observed=False,seed=None):
            eligible=[r for r in rows if r[key] is not None and (not observed or any(abs(r['x']-x)<1e-5 for x in self.plan['actual_candidates']))]
            if key!='D' and any(not r['predicted_GO'] for r in eligible):eligible=[r for r in eligible if not r['predicted_GO']]
            if not eligible:return None
            return max(eligible,key=lambda r:r[key+'_seeds'][seed] if seed is not None else r[key])['x']
        result=dict(root_tick=root['tick'],root_score=root['score'],root_signature=hashlib.sha256(json.dumps({k:root[k] for k in ['tick','state','bodies','rng']},sort_keys=True).encode()).hexdigest(),rows=rows,
          selected_full={k:choose(k) for k in 'ABCD'},selected_observed_pair={k:choose(k,True) for k in 'ABCD'},
          seed_choices={k:[choose(k,True,j) for j in range(3)] for k in ['C','D']},
          q_scan=dict(x=scan.tolist(),individual=curves,mean=mean.tolist(),maximum_interval_overshoot_points=max(overshoots),interval_overshoots=overshoots,maximum_position=float(scan[int(np.argmax(mean))])),
          timing=dict(preprocess_ms=pre_ms,Q_six_inference_ms=q_ms,Q_scan_201_ms=scan_ms,heuristic_ms=heur_ms,AC_model_ms=ac_ms,V_ensemble_ms=v_ms,shared_physics_path_ms=sum(r.get('physics_ms',0) for r in rows),cold_process_wall_ms=wall_ms),
          cold_error=error,models=self.plan['models'],information='Only root public state. Unknown C marginalized over public spawn slots. D has no predicted-GO veto; A/B/C use their one-step predicted-GO filter. Full-six best return is unobserved.')
        write(folder/'predictions.json',result);return result
