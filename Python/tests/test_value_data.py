import copy,json,tempfile,unittest
from pathlib import Path
from suika_ai.value_data import validate_episode,encode,prepare,load_dataset,FRUIT_NAMES,GLOBAL_NAMES

def state(score=7,go=False):
 return dict(game_id='game_00',stream_id='s',episode_id='e',state_id=2,score=score,game_over=go,
  fruits=[dict(id=1,type=0,x=1.,y=2.,vx=0.,vy=-1.,angle=30.,angular_velocity=2.)],
  current_fruit=dict(present=True,type=1,x=0.),next_fruit_type=2)

def episode(seed=1):
 before=state(0);after=state();end=state(10,True)
 return [dict(event='episode_start',game_id='game_00',stream_id='s',episode_id='e',seed=seed,state=before),
  dict(event='transition',game_id='game_00',stream_id='s',episode_id='e',action_id=1,state=after,observed_before=before,
   between_steps_reward=2,reward=5,score=7,info=dict(status='completed',score_before=2,planning=dict(candidates=[dict(predicted_score=99999)]))),
  dict(event='episode_end',game_id='game_00',stream_id='s',episode_id='e',game_over=True,truncated=False,reason='game_over',
   final_score=10,last_observed_score=10,tail_between_steps_reward=3,conserved=True,steps=1,state=end)]

class ValueDataTests(unittest.TestCase):
 def test_no_double_count_and_actual_state(self):
  samples=validate_episode(episode());self.assertEqual(len(samples),1);self.assertEqual(samples[0]['target'],3);self.assertEqual(samples[0]['state']['score'],7)
 def test_truncation_error_duplicate_rejected(self):
  for change in ('truncated','noterminal','badreward','badaccept','badend','duplicate'):
   rows=episode()
   if change=='truncated':rows[-1].update(truncated=True,final_score=None,reason='step_limit')
   if change=='noterminal':rows.pop()
   if change=='badreward':rows[1]['reward']+=1
   if change=='badaccept':rows[1]['action_accepted']=False
   if change=='badend':rows[-1]['final_score']+=1
   if change=='duplicate':rows.insert(2,copy.deepcopy(rows[1]))
   with self.assertRaises(ValueError,msg=change):validate_episode(rows)
 def test_missing_flags_unknown_next_and_no_label_features(self):
  sample=dict(state=state(),geometry=None,target=3);f,g=encode(sample)
  self.assertEqual(len(f[0]),len(FRUIT_NAMES));self.assertEqual(len(g),len(GLOBAL_NAMES));self.assertEqual(f[0][19],0);self.assertEqual(f[0][22],0);self.assertEqual(g[26],0);self.assertEqual(g[36],0)
  other=copy.deepcopy(sample);other['target']=999;other['seed']=123;other['state']['next_fruit_type']=-1
  _,unknown=encode(other);self.assertEqual(unknown[23],0);self.assertEqual(sum(unknown[11:22]),0)
  self.assertEqual(encode(sample),encode(dict(sample,target=99999,seed=77)))
 def test_group_split_and_strip(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for i in range(4):
    p=root/f'run{i}';p.mkdir();rows=episode(i//2)
    for row in rows:row['episode_id']=f'e{i}';row['state']['episode_id']=f'e{i}'
    rows[1]['observed_before']['episode_id']=f'e{i}'
    (p/'run.json').write_text(json.dumps(dict(workers=[dict(game_id='game_00',seed=i//2)])))
    (p/'game_00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows)+('{\"event\":' if i==0 else ''))
   report=prepare([root],root/'prepared');self.assertEqual(report['episode_count'],4);self.assertEqual(report['excluded']['partial final line ignored'],1)
   _,samples,_=load_dataset(root/'prepared');self.assertEqual(len(samples),4)
   split_by_seed={}
   for sample in samples:split_by_seed.setdefault(sample['seed'],set()).add(sample['split']);self.assertNotIn('planning',sample['state']);self.assertNotIn('final_score',sample['state'])
   self.assertTrue(all(len(v)==1 for v in split_by_seed.values()));self.assertEqual(len(set(s['split'] for s in samples)),2)
 def test_seed_modes(self):
  from suika_ai.parallel_play import resolve_collection_seed
  self.assertEqual(resolve_collection_seed('12345',4,5,True),12345)
  for _ in range(3):self.assertTrue(0<=resolve_collection_seed('auto',4,5,True)<=2147483628)
  with self.assertRaises(ValueError):resolve_collection_seed('2147483647',4,5,True)
