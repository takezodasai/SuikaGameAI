"""Export the frozen epoch-3 FP32 model and numerical parity fixtures; never overwrite."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
import torch
from suika_ai.value_checkpoint import load_checkpoint
from suika_ai.value_data import INPUT_SPEC,load_dataset,encode
from suika_ai.value_model import ValueNetwork,predict

def export(checkpoint,output,fixtures,dataset):
    payload,path=load_checkpoint(Path(checkpoint).parent,'best')
    pointer=json.loads(Path(checkpoint).read_text())
    if payload['epoch']!=3 or payload['input_spec']!=INPUT_SPEC or pointer['file']!=path.name:raise ValueError('Expected exact best epoch3/input specification; no checkpoint fallback permitted')
    model=ValueNetwork();model.load_state_dict(payload['model']);model.eval();torch.set_num_threads(1)
    layers=[]
    for prefix in ('phi.0','phi.2','head.0','head.2','head.4'):
        w=payload['model'][prefix+'.weight'];b=payload['model'][prefix+'.bias']
        layers.append(dict(inputs=w.shape[1],outputs=w.shape[0],weights=w.flatten().tolist(),bias=b.tolist()))
    result=dict(version='value-unity-v1',input_version=INPUT_SPEC['version'],epoch=3,parameters=sum(p.numel() for p in model.parameters()),checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),fruit_names=INPUT_SPEC['fruit_names'],global_names=INPUT_SPEC['global_names'],layers=layers)
    raw=json.dumps(result,allow_nan=False,separators=(',',':')).encode()
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as f:f.write(raw)
    _,samples,_=load_dataset(dataset)
    examples=[samples[i] for i in range(0,len(samples),max(1,len(samples)//20))][:20]
    # Real boards plus empty, many fruit, unknown NEXT, and terminal cases.
    import copy
    empty=copy.deepcopy(examples[0]);empty['state']['fruits']=[]
    many=copy.deepcopy(examples[-1]);many['state']['fruits']*=4
    unknown=copy.deepcopy(examples[-1]);unknown['state']['next_fruit_type']=-1
    terminal=copy.deepcopy(unknown);terminal['state']['game_over']=True
    examples += [empty,many,unknown,terminal]
    values=predict(model,examples)
    cases=[]
    for sample,v in zip(examples,values):
        state=dict(sample['state']);state['geometry']=sample['geometry']
        fruits,glob=encode(sample)
        cases.append(dict(state=state,fruits=[dict(values=f) for f in fruits],global_features=glob,expected=v))
    with Path(fixtures).open('x',encoding='utf-8') as f:json.dump(dict(cases=cases),f,allow_nan=False)
    return dict(epoch=3,sha256=hashlib.sha256(raw).hexdigest(),cases=len(cases),model=str(output))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--checkpoint',default='outputs/value_train_100_01/checkpoints/best.json');p.add_argument('--output',default='../Unity/Assets/StreamingAssets/suika_value_epoch3.json');p.add_argument('--fixtures',default='../Unity/Assets/StreamingAssets/suika_value_parity.json');p.add_argument('--dataset',default='outputs/value_data_100_01');a=p.parse_args();print(json.dumps(export(a.checkpoint,a.output,a.fixtures,a.dataset)))
