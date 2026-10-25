"""STEP7-A offline value pipeline. Does not control Unity or change the live evaluator."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--input',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--split-seed',type=int,default=2026);p.add_argument('--validation-fraction',type=float,default=.15);p.add_argument('--test-fraction',type=float,default=.15);p.add_argument('--policy');p.add_argument('--go-ratio',type=float)
    p=sub.add_parser('train');p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path);p.add_argument('--epochs',type=int);p.add_argument('--resume',action='store_true');p.add_argument('--max-updates',type=int);p.add_argument('--max-seconds',type=float)
    for command in ('evaluate','infer','benchmark'):
        p=sub.add_parser(command);p.add_argument('--model',type=Path,required=True);p.add_argument('--checkpoint',default='best');p.add_argument('--data',type=Path,required=True)
        if command=='infer':p.add_argument('--index',type=int,default=0);p.add_argument('--unknown-next',action='store_true')
        if command=='evaluate':
            p.add_argument('--output',type=Path,required=True);p.add_argument('--split',choices=('validation','test','all'),default='validation',help='Test only after model/settings are frozen');p.add_argument('--external-test',action='store_true',help='Explicit final-test-only old/new model comparison; requires original dataset and no seed overlap')
    args=parser.parse_args()
    from suika_ai.value_data import prepare,load_dataset
    if args.command=='prepare':
        result=prepare(args.input,args.output,args.split_seed,args.validation_fraction,args.test_fraction,args.policy,args.go_ratio)
        print(json.dumps({k:result[k] for k in ('episode_count','sample_count','split_counts','train_groups','validation_groups','test_groups','excluded')},indent=2));return
    from suika_ai.value_train import train,load_model,evaluate,write_reports,benchmark
    if args.command=='train':
        cfg=json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
        if args.epochs is not None:cfg['epochs']=args.epochs
        result=train(args.data,args.output,cfg,args.resume,args.max_updates,args.max_seconds)
        print(json.dumps({k:result[k] for k in ('splits','epoch','updates','stopped','latest')},indent=2));return
    manifest,samples,fingerprint=load_dataset(args.data);model,payload,path=load_model(args.model,args.checkpoint)
    if args.command=='evaluate':
        baseline=None;context=None
        if args.external_test:
            if args.split!='test':raise ValueError('--external-test requires --split test; never use it for model selection')
            from suika_ai.value_train import external_test_context
            baseline,context=external_test_context(args.model,manifest,samples,payload)
        elif fingerprint!=payload['dataset_fingerprint']:raise ValueError('Dataset differs from frozen training split; use explicit --external-test --split test only for final evaluation')
        args.output.mkdir(parents=True,exist_ok=False)
        result,rows=evaluate(model,samples,splits=('train','validation','test') if args.split=='all' else (args.split,),baseline_override=baseline)
        if context:result['external_test']=context
        write_reports(args.output,result,rows,payload['history']);print(json.dumps(result['splits'],indent=2))
    elif args.command=='infer':
        from suika_ai.value_model import predict
        if not 0<=args.index<len(samples):raise ValueError('sample index out of range')
        sample=samples[args.index]
        if args.unknown_next:sample=dict(sample,state=dict(sample['state'],next_fruit_type=-1))
        print(json.dumps(dict(checkpoint=str(path),index=args.index,fruit_count=len(sample['state']['fruits']),next_fruit_type=sample['state'].get('next_fruit_type'),prediction_points=predict(model,[sample])[0],target_points=sample['target'],split=sample['split'])))
    else:print(json.dumps(benchmark(model,samples),indent=2))

if __name__=='__main__':main()
