"""Post-training Validation analysis only. No fitting and no Test data."""
import argparse,csv,json
from pathlib import Path
from collections import defaultdict
import numpy as np
from compare_mc_td_learning import CONFIG,metrics

def analyze(root):
    root=Path(root);records=[json.loads(x) for x in (root/'dataset/records.jsonl').read_text().splitlines()];temporal=np.load(root/'dataset/temporal.npz');results=[];curves=[];common_subset={};frozen={}
    for case in CONFIG['cases']:
        common_subset[case]={};frozen[case]={}
        for variant in CONFIG['td_weights']:
            subset=[];frozen[case][variant]=[]
            for seed in CONFIG['seeds']:
                p=root/case/variant/str(seed);r=json.loads((p/'result.json').read_text());results.append(r);frozen[case][variant].append({k:r[k] for k in ('seed','checkpoint','checkpoint_sha256','epoch')})
                rows=[json.loads(x) for x in (p/'validation_predictions.jsonl').read_text().splitlines()];chosen=[x for x in rows if temporal['homogeneous'][x['index']]];ids=[x['index'] for x in chosen];pred=[x['prediction'] for x in chosen];subset.append(metrics(records,ids,pred,temporal))
                for h in json.loads((p/'history.json').read_text()):curves.append(dict(case=case,variant=variant,seed=seed,epoch=h['epoch'],val_mae=h['validation']['all']['mae'],val_bias=h['validation']['all']['bias'],near_go_overprediction=h['validation']['near_go']['overprediction'],macro_mse=h['validation']['group_macro_mse'],lr=h['lr'],train_td_target_bias=h.get('train_td_target_bias_vs_MC')))
            common_subset[case][variant]=dict(mae_mean=float(np.mean([r['all']['mae'] for r in subset])),mae_sd=float(np.std([r['all']['mae'] for r in subset],ddof=1)),macro_mse_mean=float(np.mean([r['group_macro_mse'] for r in subset])),counts={k:subset[0]['all'][k] for k in ('states','games','groups')})
    differences={}
    for case in CONFIG['cases']:
        differences[case]={}
        for variant in ['TD','mix25','mix50']:
            by_group=defaultdict(list);all_diff=[]
            for seed in CONFIG['seeds']:
                base=next(r for r in results if (r['case'],r['variant'],r['seed'])==(case,'MC',seed));current=next(r for r in results if (r['case'],r['variant'],r['seed'])==(case,variant,seed));all_diff.append(current['validation']['all']['mae']-base['validation']['all']['mae'])
                for g,x in current['validation']['groups'].items():by_group[g].append(x['mae']-base['validation']['groups'][g]['mae'])
            means={g:float(np.mean(v)) for g,v in by_group.items()};differences[case][variant]=dict(initialization_seed_mae_differences=all_diff,mean_group_mae_difference=float(np.mean(list(means.values()))),groups_improved=sum(v<0 for v in means.values()),groups_worse=sum(v>0 for v in means.values()),group_differences=means)
    group_rows=[]
    for case in CONFIG['cases']:
        first=next(r for r in results if r['case']==case)
        for group in first['validation']['groups']:
            seeds=sorted({r['seed'] for r in records if r['group']==group});row=dict(case=case,group=group,game_seeds=','.join(map(str,seeds)),games=first['validation']['groups'][group]['games'])
            for variant in CONFIG['td_weights']:
                values=[r['validation']['groups'][group]['mae'] for r in results if r['case']==case and r['variant']==variant];row[variant+'_mean_mae']=float(np.mean(values));row[variant+'_sd_mae']=float(np.std(values,ddof=1))
            group_rows.append(row)
    with (root/'validation_group_metrics.csv').open('x',encoding='utf8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(group_rows[0]));w.writeheader();w.writerows(group_rows)
    with (root/'learning_curves.csv').open('x',encoding='utf8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(curves[0]));w.writeheader();w.writerows(curves)
    result=dict(common_homogeneous_validation=common_subset,paired_group_differences=differences,test_evaluated=False,limitation='Validation-only, repeated model selection. Common-subset comparison fixes evaluation groups, not training size or data coverage.')
    with (root/'validation_analysis.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    with (root/'frozen_checkpoints.json').open('x',encoding='utf8') as f:json.dump(dict(models=frozen,test_policy='No Test was evaluated. Future evaluation must keep all 3 seeds and never pick a seed using Test.'),f,indent=2)
    print(json.dumps(common_subset,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();analyze(a.root)
