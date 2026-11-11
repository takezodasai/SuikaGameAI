"""Audit frozen checkpoints and existing Test errors; never selects or trains models."""
import argparse,json,hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np
import torch
from suika_ai.long_value_data import load
from suika_ai.long_value_model import PackedBoards,infer
from suika_ai.long_value_train import load_trained
from suika_ai.collection_audit import initial_sequence

def prefix(source):
    rows=[]
    with Path(source).open(encoding='utf-8-sig') as f:
        for line in f:
            row=json.loads(line)
            if row.get('event')=='transition':rows.append(row)
            if len(rows)>=8:break
    return initial_sequence(rows)

def audit(root):
    root=Path(root);root.mkdir(exist_ok=False);torch.set_num_threads(1)
    previous=Path('Python/outputs/value_reliability_01');old_path=Path('Python/outputs/step8ac_01/dataset/manifest.json');old=json.loads(old_path.read_text())
    boards=PackedBoards(load(previous/'dataset'));records=boards.records;m=boards.manifest
    test=[e for e in m['episodes'] if e['split']=='test'];collisions=[];inventory=[]
    for e in test:
        seq=prefix(e['source']);matches=[dict(id=a['id'],split=a['split'],seed=a['seed'],same_seed=e['seed']==a['seed'],same_initial8=seq==a.get('initial_sequence')) for a in old['episodes'] if e['seed']==a['seed'] or seq==a.get('initial_sequence')]
        inventory.append(dict(seed=e['seed'],episode=e['id'],initial_sequence=seq,source=e['source'],old_matches=matches));collisions+=matches
    models={};predictions={};checkpoints={}
    for name,path in [('old_AC',Path('Python/outputs/step8ac_01/geometry')),('A_retrain',previous/'A')]:
        if name=='old_AC':model,kind,payload,cp=load_trained(path)
        else:
            from suika_ai.value_checkpoint import load_checkpoint
            from suika_ai.long_value_model import GeometryValueNetwork
            payload,cp=load_checkpoint(path/'checkpoints','best');model=GeometryValueNetwork();model.load_state_dict(payload['model']);kind='geometry'
        ids=[i for i,r in enumerate(records) if r['split'] in ('test','validation')];pred=infer(model,kind,boards,ids);predictions[name]=dict(zip(ids,pred))
        checkpoints[name]=dict(checkpoint=str(cp),sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),epoch=payload['epoch'],checkpoint_fields=sorted(payload.keys()))
    def metric(ids,name):
        if not ids:return dict(states=0,groups=0)
        err=np.array([predictions[name][i]-records[i]['target'] for i in ids]);return dict(states=len(ids),groups=len({records[i]['group'] for i in ids}),mae=float(abs(err).mean()),rmse=float(np.sqrt(np.mean(err**2))),bias=float(err.mean()),overprediction=float(np.maximum(err,0).mean()))
    results={}
    for split in ['validation','test']:
        ids=[i for i,r in enumerate(records) if r['split']==split and not r['game_over']];groups=defaultdict(list)
        for i in ids:groups[records[i]['episode']].append(i)
        rows=[]
        for ep,at in groups.items():
            metadata=next(e for e in m['episodes'] if e['id']==ep);segments={}
            for phase,keep in [('all',lambda r:True),('near_go',lambda r:r['near_go']),('score_ge_2000',lambda r:r['score']>=2000),('score_ge_3000',lambda r:r['score']>=3000),('return_ge_1000',lambda r:r['target']>=1000),('wm_pre_observed',lambda r:r['wm_window']=='pre_observed'),('wm_post_observed',lambda r:r['wm_window']=='post_observed')]:
                subset=[i for i in at if keep(records[i])];segments[phase]={n:metric(subset,n) for n in predictions}
            extra=sum(abs(predictions['A_retrain'][i]-records[i]['target'])-abs(predictions['old_AC'][i]-records[i]['target']) for i in at)
            worst=sorted(at,key=lambda i:abs(predictions['A_retrain'][i]-records[i]['target'])-abs(predictions['old_AC'][i]-records[i]['target']),reverse=True)[:5]
            rows.append(dict(seed=metadata['seed'],episode=ep,final_score=metadata['final_score'],states=len(at),extra_absolute_error_sum=extra,contribution_to_all_mae_difference=extra/len(ids),segments=segments,worst_states=[dict(index=i,action_id=records[i]['action_id'],score=records[i]['score'],target=records[i]['target'],old=float(predictions['old_AC'][i]),new=float(predictions['A_retrain'][i]),remaining_actions=records[i]['remaining_actions']) for i in worst]))
        results[split]=dict(states=len(ids),groups=len({records[i]['group'] for i in ids}),metrics={n:metric(ids,n) for n in predictions},games=rows)
    output=dict(old_manifest_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),checkpoints=checkpoints,test_inventory=inventory,overlaps=collisions,unknown_old_prefixes=sum(not e.get('initial_sequence') for e in old['episodes']),evaluation=results,
        limitation='Existing Test is inspected for error attribution only. No model/hyperparameter selection or training. Shared short opening states alone are not episode leakage.')
    with (root/'audit.json').open('x',encoding='utf8') as f:json.dump(output,f,indent=2)
    print(json.dumps(dict(overlaps=len(collisions),test=results['test']['metrics'],per_seed=[dict(seed=g['seed'],old=g['segments']['all']['old_AC']['mae'],new=g['segments']['all']['A_retrain']['mae'],contribution=g['contribution_to_all_mae_difference']) for g in results['test']['games']]),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.output)
