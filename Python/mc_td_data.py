"""Read-only input audit and Train/Validation-only temporal value dataset."""
import json,hashlib
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
from suika_ai.value_data import INPUT_SPEC
from suika_ai.long_value_data import load
from suika_ai.temporal_value_targets import n_step_pairs

def load_restricted(path):
    path=Path(path);m=json.loads((path/'manifest.json').read_text());records=[json.loads(x) for x in (path/'records.jsonl').read_text().splitlines()]
    if m['input_spec']!=INPUT_SPEC:raise ValueError('Input feature mismatch')
    for name,sha in m['files'].items():
        if hashlib.sha256((path/name).read_bytes()).hexdigest()!=sha:raise ValueError('Restricted dataset changed')
    membership={}
    for r in records:
        if r['split'] not in ('train','validation'):raise ValueError('Test entered restricted data')
        for kind,key in [('episode',r['episode']),('seed',r['seed']),('group',r['group'])]:
            k=(kind,key)
            if k in membership and membership[k]!=r['split']:raise ValueError('Temporal split leakage')
            membership[k]=r['split']
    offsets=np.load(path/'offsets.npy');g=np.load(path/'globals.npy');y=np.load(path/'targets.npy')
    if len(records)!=m['sample_count'] or len(g)!=len(records) or len(y)!=len(records):raise ValueError('Shape mismatch')
    return m,records,offsets,g,y,np.memmap(path/'fruits.f32',dtype=np.float32,mode='r',shape=(int(offsets[-1]),30))

def homogeneous(settings):
    if any(k not in settings for k in ('ai_mode','candidate_count','mcts_iterations','mcts_max_depth')):return False
    required=dict(ai_mode='mcts',candidate_count=5,candidate_policy='grid',mcts_iterations=128,mcts_max_depth=4,mcts_budget_mode='fixed',rollout_policy='random',tree_policy='chance',expansion_policy='legacy',action_order_policy='index',execution_mode='sync')
    if any(settings.get(k,v)!=v for k,v in required.items()):return False
    return not any(settings.get(k,False) for k in ('mcts_collection_budget','mcts_widening','mcts_auto_depth','mcts_common_chance'))

def prepare(output):
    output=Path(output);source=Path('Python/outputs/value_reliability_01/dataset');m,rs,offsets,gs,ys,fs=load(source)
    ids=[i for i,r in enumerate(rs) if r['split'] in ('train','validation')]
    records=[dict(rs[i]) for i in ids];pieces=[np.asarray(fs[offsets[i]:offsets[i+1]]) for i in ids]
    out=output/'dataset';out.mkdir();new_offsets=np.cumsum([0]+[len(x) for x in pieces]);np.save(out/'offsets.npy',new_offsets);np.concatenate(pieces).astype('float32').tofile(out/'fruits.f32');np.save(out/'globals.npy',np.asarray(gs[ids],dtype='float32'));np.save(out/'targets.npy',np.asarray(ys[ids],dtype='float32'))
    groups=defaultdict(list)
    for i,r in enumerate(records):groups[r['episode']].append(i)
    recovered={}
    terminal_file=Path('Python/outputs/replay_value_audit_01/td/observed_terminals.jsonl')
    for line in terminal_file.read_text().splitlines():
        row=json.loads(line)
        if hashlib.sha256(Path(row['source']).read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('Observed terminal source changed')
        recovered[row['episode']]=row
    pairs={};episodes=[];endpoints=[];profiles=Counter();single=[];distances={}
    for ep,at in groups.items():
        meta=next(e for e in m['episodes'] if e['id']==ep);settings=json.loads((Path(meta['source']).parent/'run.json').read_text())['settings'];same=homogeneous(settings)
        profile=tuple(settings.get(k) for k in ('ai_mode','mcts_iterations','mcts_max_depth','candidate_count','mcts_budget_mode','mcts_collection_budget','mcts_widening','rollout_policy'))
        profiles[str(profile)]+=1
        if same:single.extend(at)
        if not records[at[-1]]['game_over']:
            actual=recovered[ep];state=actual['state']
            if not state['game_over'] or state['score']!=records[at[-1]]['score']+records[at[-1]]['target']:raise ValueError('Unverified terminal')
            endpoint=len(records);records.append(dict(records[at[-1]],score=state['score'],target=0,game_over=True,source_event='actual_episode_end'));at.append(endpoint)
            endpoints.append(dict(index=endpoint,episode=ep,score=state['score'],tail_reward=actual['tail_reward'],source_sha256=actual['source_sha256']))
        pp=n_step_pairs(records,at,3,natural_go=True)
        for p in pp:pairs[p['index']]=p
        for pos,i in enumerate(at):distances[i]=len(at)-1-pos
        # Every original terminal also has a zero target, but is not sampled in any method.
        for i in at:
            if records[i]['score']+records[i]['target']!=meta['final_score']:raise ValueError('MC conservation')
        episodes.append(dict(meta,homogeneous128=same))
    original_count=len(ids)
    # External true terminals are never encoded or sent through the network; bootstrap is zero.
    manifest=dict(version='mc-td-actual-post-v1',input_spec=m['input_spec'],environments=m['environments'],episodes=episodes,episode_count=len(episodes),sample_count=original_count,split_groups={s:m['split_groups'][s] for s in ('train','validation')},source_manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),source_terminal_sha256=hashlib.sha256(terminal_file.read_bytes()).hexdigest(),test_excluded_games=sum(e['split']=='test' for e in m['episodes']),external_terminals=endpoints)
    with (out/'records.jsonl').open('x',encoding='utf8') as f:
        for r in records[:original_count]:f.write(json.dumps(r)+'\n')
    single_set=set(single)
    np.savez(out/'temporal.npz',next_index=np.array([pairs[i]['bootstrap_index'] if i in pairs else i for i in range(original_count)]),reward=np.array([pairs[i]['score_delta'] if i in pairs else 0 for i in range(original_count)],dtype='float32'),terminal=np.array([pairs[i]['terminal'] if i in pairs else True for i in range(original_count)],dtype=bool),homogeneous=np.array([i in single_set for i in range(original_count)],dtype=bool),distance=np.array([distances[i] for i in range(original_count)]))
    manifest['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    audit=dict(games=dict(Counter(e['split'] for e in episodes)),groups={s:len(v) for s,v in manifest['split_groups'].items()},states=dict(Counter(r['split'] for r in records[:original_count])),nonterminal=dict(Counter(r['split'] for r in records[:original_count] if not r['game_over'])),homogeneous_games=dict(Counter(e['split'] for e in episodes if e['homogeneous128'])),homogeneous_groups={s:len({e['group'] for e in episodes if e['split']==s and e['homogeneous128']}) for s in ('train','validation')},external_terminals=endpoints,excluded_test_games=manifest['test_excluded_games'],excluded_unverified_games=0,profiles=dict(profiles))
    (output/'data_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8');return audit
