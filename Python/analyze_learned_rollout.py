"""Audit completed new-rollout games; never runs a simulation or edits source logs."""
import hashlib,json,statistics
from pathlib import Path
import numpy as np

def main():
    p=Path(__file__).resolve().parent/'outputs/learned_rollout_01';out=p/'analysis';out.mkdir(exist_ok=False)
    results=[];sequences={};roots={}
    for mode in ['mixed','legacy']:
        folder=p/('normal_'+mode+'_03')
        if not (folder/'result.json').exists():continue
        result=json.loads((folder/'result.json').read_text());rows=[json.loads(l) for l in (folder/'trace.jsonl').read_text().splitlines()];ds=[r for r in rows if r['evt']=='decision'];actions=[r for r in rows if r['evt']=='action'];end=next((r for r in reversed(rows) if r['evt']=='end'),None);root=rows[0];roots[mode]=root['state']
        seq=[root['state']['current_fruit']['type'],root['state']['next_fruit_type']]+[r['state']['next_fruit_type'] for r in rows if r['evt']=='release'];sequences[mode]=seq
        audit=result.get('rollout_totals',{});learned=sum(r['search']['guided_calls'] for r in ds);rollouts=sum(r['search']['rollout_calls'] for r in ds);tree=sum(r['search']['tree_actions'] for r in ds);depth=np.sum([r['search']['rollout_by_depth'] for r in ds],axis=0).tolist() if ds else []
        unsafe=0
        for r in ds:
            search=r['search'];assert search['completed_iterations']==128 and sum(a['visits'] for a in search['root'])==128 and search['source_unchanged']
            assert r['command']['x']==r['planning']['selected_x']
            chosen=next(a for a in search['root'] if a['index']==r['planning']['selected_index'])
            if chosen['immediate_go'] and any(a['drop_success'] and not a['immediate_go'] for a in search['root']):unsafe+=1
        if mode=='mixed':assert audit['learned_calls']==learned and audit['rollout_calls']==rollouts and audit['random_calls']+audit['learned_calls']+audit['fallback_calls']==rollouts
        # Action completion can lag release/GO; conserve scores over ALL recorded score observations.
        scores=[r['score'] for r in rows];assert all(b>=a for a,b in zip(scores,scores[1:]));assert sum(b-a for a,b in zip(scores,scores[1:]))==scores[-1]-scores[0]
        row=dict(mode=mode,natural_go=result['natural_go'],score=end['score'] if end and result['natural_go'] else None,observed_score=scores[-1],drops=end['accepted_drops'] if end else None,new_watermelons=end['new_watermelons'] if end else None,doubles=end['double_watermelons'] if end else None,wall_seconds=result['wall_seconds'],mean_planning_ms=statistics.mean(r['planning_ms'] for r in ds),p95_planning_ms=float(np.percentile([r['planning_ms'] for r in ds],95)),total_planning_ms=sum(r['planning_ms'] for r in ds),physics_ticks=result['total_physics_ticks'],rollout_calls=rollouts,learned_calls=learned,learned_fraction=learned/max(rollouts,1),tree_actions=tree,rollout_fraction=rollouts/max(rollouts+tree,1),rollout_by_depth=depth,policy_inference_total_ms=audit.get('inference_ms',0),fallback_calls=audit.get('fallback_calls',0),unsafe_despite_safe_alternative=unsafe,max_allocated_bytes=max(r['allocated_bytes'] for r in rows),max_retained_scenes=max(r['retained_scenes'] for r in rows),max_pending_unloads=max(r['pending_unloads'] for r in rows),errors=result['errors'],score_conserved=True)
        results.append(row)
    comparison={}
    if len(results)==2:
        a,b=results;n=min(len(sequences['mixed']),len(sequences['legacy']));comparison=dict(common_fruit_prefix_count=n,common_fruit_prefix_equal=sequences['mixed'][:n]==sequences['legacy'][:n],initial_public_states_equal=roots['mixed']==roots['legacy'],score_difference_mixed_minus_legacy=a['score']-b['score'] if a['natural_go'] and b['natural_go'] else None,mean_planning_time_ratio=a['mean_planning_ms']/b['mean_planning_ms'],scope='One development seed pair; distinct later boards; not population performance or causal inference-overhead benchmark')
    cfg=json.loads((p/'protocol.json').read_text());sha=lambda f:hashlib.sha256(Path(f).read_bytes()).hexdigest();verification=dict(protected_files=len(cfg['protected']),changed_protected=[f for f,h in cfg['protected'].items() if sha(f)!=h],changed_datasets=[f for f,h in cfg['data'].items() if sha(Path(__file__).parent/'outputs/policy_success_01/dataset'/f)!=h],model_sha256=sha(p/'training/model.json'))
    summary=dict(games=results,comparison=comparison,verification=verification);(out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
