"""Compare actual Unity candidate snapshots to the frozen Python model."""
import argparse,json,sys,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
import torch
from suika_ai.value_checkpoint import load_checkpoint
from suika_ai.value_data import encode,INPUT_SPEC
from suika_ai.value_model import ValueNetwork,predict

def check(root,checkpoint):
    payload,path=load_checkpoint(Path(checkpoint).parent,'best')
    if payload['epoch']!=3 or payload['input_spec']!=INPUT_SPEC:raise ValueError('Unexpected checkpoint')
    model=ValueNetwork();model.load_state_dict(payload['model']);torch.set_num_threads(1)
    samples=[];expected=[];timings=[];missing=[]
    for log in Path(root).rglob('game_*.jsonl'):
        for line in log.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);decision=row.get('info',{}).get('planning') or {}
            for c in decision.get('candidates',[]):
                if not c.get('value_evaluated'):continue
                state=c['value_state'];samples.append(dict(state=state,geometry=state['geometry']));expected.append(c['future_value']);timings.append(c['inference_ms'])
                if state['next_fruit_type']!=-1 and c['drop_success']:raise ValueError('Hidden NEXT leaked')
                for f in state['fruits']:
                    if not f['observation_metadata_known'] or not f['collider_measurement_known']:missing.append(f['id'])
                if c['drop_success'] and (not state['current_fruit']['y_known'] or state['current_fruit']['type']!=decision['next_fruit_type']):raise ValueError('Held fruit differs from visible source NEXT / missing Y')
                if abs(c['q_points']-c['reward']-c['future_value'])>.001:raise ValueError('Q double counted/missing reward')
    if not samples:raise ValueError('No evaluated snapshots')
    actual=predict(model,samples);errors=[abs(a-b) for a,b in zip(actual,expected)]
    result=dict(candidates=len(samples),max_points_error=max(errors),mean_points_error=statistics.mean(errors),
        inference_ms_median=statistics.median(timings),inference_ms_max=max(timings),missing_fruit_measurements=len(missing))
    if max(errors)>.02 or missing:raise ValueError(result)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--checkpoint',default='outputs/value_train_100_01/checkpoints/best.json');a=p.parse_args();r=check(a.root,a.checkpoint);print(json.dumps(r));(a.root/'live_parity.json').write_text(json.dumps(r,indent=2))
