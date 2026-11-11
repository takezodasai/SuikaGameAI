"""Save model-actuation and timing evidence, without training or game launches."""
import argparse
import collections
import json
import statistics
import time
from pathlib import Path

import numpy as np
from candidate_ridge import features,predict,infer_public
from watermelon_lab import write,sha


def percentile(xs,q):
    return float(np.quantile(xs,q)) if xs else None


def analyze(study,out):
    study,out=Path(study),Path(out);out.mkdir(parents=True,exist_ok=False)
    model_path=study/'training/model.json';model=json.loads(model_path.read_text(encoding='utf8'));model_sha=sha(model_path)
    games=[];example=None
    for folder in sorted(study.glob('normal_*')):
        if not (folder/'result.json').exists():continue
        result=json.loads((folder/'result.json').read_text(encoding='utf8'));rs=[json.loads(l) for l in (folder/'trace.jsonl').open(encoding='utf8')]
        ds=[r for r in rs if r['evt']=='decision'];releases=[r for r in rs if r['evt']=='release'];end=result['end']
        valid=[r for r in ds if r.get('ridge',{}).get('model_sha256')==model_sha]
        for r in valid:
            c=r['final_selection'];stats=r['search']['root'];a=next(s for s in stats if s['index']==c['recommended_index']);b=next(s for s in stats if s['index']==c['alternative_index'])
            x=features(r['state'],[c['recommended_x'],c['alternative_x']],[a,b]);p=predict(model,x)
            assert abs(p['predicted_delta']-r['ridge']['predicted_delta'])<1e-3 and p['choose_B']==r['ridge']['choose_B']
            if p['choose_B']:assert b['drop_success'] and not b['immediate_go']
            if example is None and p['choose_B']:example=dict(state=r['state'],coordinates_A_B=[c['recommended_x'],c['alternative_x']],mcts_statistics_A_B=[a,b])
        changed=sum(r['final_selection']['actual_x']!=r['final_selection']['recommended_x'] for r in releases)
        decisions_changed=sum(r['final_selection']['actual_x']!=r['final_selection']['recommended_x'] for r in ds)
        reasons=dict(collections.Counter(r['final_selection']['reason'] for r in ds))
        for r in rs:
            assert r['score']-r['initial_score']==r['additional_score']
        if result['natural_go']:assert end['state']['game_over'] and not end['truncated'] and result['exit_code']==0 and not result['errors']
        planning=[r['planning_ms'] for r in ds];inference=[r['ridge']['inference_ms'] for r in valid];feature_ms=[r['ridge']['feature_ms'] for r in valid]
        games.append(dict(folder=str(folder.resolve()),seed=result['game_seed'],natural_go=result['natural_go'],
            final_score=end['score'] if result['natural_go'] else None,observed_score=end['score'] if end else None,
            drops=end['accepted_drops'] if end else None,decisions=len(ds),model_inferences=len(valid),
            B_selected_decisions=decisions_changed,MCTS_changes_executed_drops=changed,reasons=reasons,
            new_watermelons=end['new_watermelons'] if end else None,coexist=end['two_watermelons_present'] if end else None,
            doubles=end['double_watermelons'] if end else None,wall_seconds=result['wall_seconds'],
            mean_mcts_ms=statistics.mean(planning),p95_mcts_ms=percentile(planning,.95),
            mean_features_ms=statistics.mean(feature_ms) if feature_ms else None,
            mean_ridge_ms=statistics.mean(inference) if inference else None,p95_ridge_ms=percentile(inference,.95),
            max_retained_scenes=max(r['retained_scenes'] for r in rs),max_pending_unloads=max(r['pending_unloads'] for r in rs),
            score_conserved=True,predictions_and_choices_rechecked=True))
    if example:
        write(out/'public_inference_example.json',example);pred=infer_public(model,example);write(out/'public_inference_result.json',pred)
        x=features(example['state'],example['coordinates_A_B'],example['mcts_statistics_A_B']);timings=[]
        for _ in range(1000):
            start=time.perf_counter();predict(model,x);timings.append((time.perf_counter()-start)*1000)
        write(out/'python_inference_benchmark.json',dict(samples=1000,mean_ms=statistics.mean(timings),p95_ms=percentile(timings,.95),feature_extraction_included=False))
    summary=dict(games=games,model_sha256=model_sha,model_bytes=model_path.stat().st_size,
        training=json.loads((study/'training/training_manifest.json').read_text(encoding='utf8')),
        cv=json.loads((study/'training/evaluation.json').read_text(encoding='utf8')),
        note='Functional implementation verified, not evidence of improved playing strength. Normal result summary counters are recomputed from trace, not initial eligible_B_decisions alias.')
    write(out/'summary.json',summary);print(json.dumps(games,indent=2));return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();analyze(a.study,a.output)
