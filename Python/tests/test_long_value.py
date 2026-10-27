import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from suika_ai.long_value_data import slim,tail,load
from suika_ai.value_data import validate_episode,encode,INPUT_SPEC
from suika_ai.long_value_model import GeometryValueNetwork,geometry_features,PackedBoards,forward
from suika_ai.long_value_train import train,load_trained,rank_loss
from suika_ai.long_value_metrics import matched_pairs,ranking_metrics,spearman,near_terminal_ids
from test_value_data import episode,state

class LongValueTests(unittest.TestCase):
 def test_stream_slim_preserves_audit_and_selected_target(self):
  rows=[slim(r) for r in episode()];samples=validate_episode(rows)
  self.assertEqual(samples[0]['target'],3);self.assertNotIn('candidates',rows[1]['info']['planning'])
  for change in ('reward','truncate','reject'):
   x=copy.deepcopy(rows)
   if change=='reward':x[1]['reward']+=1
   elif change=='truncate':x[-1]['truncated']=True
   else:x[1]['action_accepted']=False
   with self.assertRaises(ValueError):validate_episode(x)
 def test_tail_never_treats_partial_record_as_go(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'log';p.write_text(json.dumps(episode()[-1])+'\n');self.assertEqual(tail(p)['reason'],'game_over')
   with p.open('a') as f:f.write('{"event":')
   self.assertEqual(tail(p),{})
 def test_geometry_permutation_and_empty_unknown(self):
  torch.set_num_threads(1);torch.manual_seed(21)
  s=state();s['fruits']=[dict(s['fruits'][0],type=i%11,x=i/70,half_width=.1,half_height=.1,collider_offset_x=.01,collider_offset_y=.02,has_collided=True) for i in range(180)]
  f,g=encode(dict(state=s,geometry=[-2,2,-2,4]));f=np.asarray(f,dtype=np.float32);g=np.asarray(g,dtype=np.float32)
  a=geometry_features(f,g);b=geometry_features(f[::-1],g);np.testing.assert_allclose(a,b,atol=1e-7)
  model=GeometryValueNetwork().eval();mask=torch.ones(1,len(f),dtype=torch.bool)
  with torch.inference_mode():
   va=model(torch.tensor(f[None]),mask,torch.tensor(g[None]),torch.tensor(a[None]));vb=model(torch.tensor(f[::-1].copy()[None]),mask,torch.tensor(g[None]),torch.tensor(b[None]))
  torch.testing.assert_close(va,vb,atol=1e-6,rtol=1e-6)
  self.assertTrue(np.isfinite(a).all());self.assertEqual(len(a),57)
  g[36]=0;np.testing.assert_array_equal(geometry_features(f,g),np.zeros(57));g[36]=1
  self.assertEqual(geometry_features(np.zeros((0,30)),g)[-1],1)
  g[35]=1;g[11:22]=0;g[23]=0
  self.assertEqual(float(model(torch.zeros(1,1,30),torch.zeros(1,1,dtype=torch.bool),torch.tensor(g[None]),torch.zeros(1,57))[0]),0)
 def test_targets_ids_policy_not_inputs(self):
  a=dict(state=state(),geometry=[-2,2,-2,4],target=7);b=dict(a,target=9000,seed=77,policy='future',final_score=100000)
  self.assertEqual(encode(a),encode(b))
 def test_ranking_mask_and_nontrivial_pairs(self):
  p=torch.tensor([.2,.9],requires_grad=True);y=torch.tensor([.1,.8]);groups=torch.tensor([1,2])
  loss,n=rank_loss(p,y,torch.tensor([.2,.21]),groups);self.assertEqual(n,1);loss.backward();self.assertTrue(torch.isfinite(p.grad).all())
  self.assertEqual(rank_loss(p,y,torch.tensor([.2,.8]),groups)[1],0)
  self.assertEqual(rank_loss(p,y,torch.tensor([.2,.21]),torch.tensor([1,1]))[1],0)
  records=[dict(group=str(i),episode=str(i),game_over=False,score=200,policy='p',held_type=1,next_type=2,target=i*200) for i in range(4)]
  pairs=matched_pairs(records,list(range(4)),count=6);self.assertEqual(len(pairs),6)
  pred=np.array([r['target'] for r in records]);self.assertEqual(ranking_metrics(records,pred,pairs)['accuracy'],1)
  self.assertEqual(ranking_metrics(records,-pred,pairs)['accuracy'],0)
  self.assertEqual(ranking_metrics(records,np.zeros(4),pairs)['accuracy'],.5)
  self.assertEqual(spearman([1,2,2],[1,3,3]),1)
 def test_near_go_excludes_terminal_and_handles_between_action_go(self):
  records=[dict(episode='a',game_over=i==7) for i in range(8)]+[dict(episode='b',game_over=False) for i in range(8)]
  self.assertEqual(near_terminal_ids(records,list(range(16))),set(range(2,7))|set(range(11,16)))
 def test_checkpoint_epoch_resume_exact_and_schema_guard(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);d=root/'data';d.mkdir();records=[];fruits=[];globs=[];offset=[0]
   for split in ('train','validation','test'):
    for j in range(4):
     f,g=encode(dict(state=state(7+j),geometry=[-2,2,-2,4]));fruits.extend(f);globs.append(g);offset.append(len(fruits));i=len(records)
     records.append(dict(episode=str(i),group=split+str(j%2),seed=i,split=split,target=200+j*20))
   manifest=dict(sample_count=len(records),input_spec=INPUT_SPEC,split_seed=1,split_games={},split_groups={})
   (d/'manifest.json').write_text(json.dumps(manifest));(d/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
   np.array(fruits,dtype=np.float32).tofile(d/'fruits.f32');np.save(d/'offsets.npy',offset);np.save(d/'globals.npy',np.array(globs,dtype=np.float32));np.save(d/'targets.npy',np.array([r['target']/1000 for r in records],dtype=np.float32))
   boards=PackedBoards(load(d));cfg=dict(epochs=2,batch_size=4,width=8,head_width=16)
   train(boards,d,root/'full','geometry',cfg)
   train(boards,d,root/'resumed','geometry',dict(cfg,epochs=1));train(boards,d,root/'resumed','geometry',cfg,True)
   a,_,pa,_=load_trained(root/'full','latest');b,_,pb,_=load_trained(root/'resumed','latest')
   for key,value in a.state_dict().items():torch.testing.assert_close(value,b.state_dict()[key],rtol=0,atol=0)
   self.assertEqual(pa['updates'],pb['updates'])
   with self.assertRaises(ValueError):train(boards,d,root/'resumed','geometry',dict(cfg,lr=.02),True)
   boards.fruits._mmap.close()
   records[4]['seed']=records[0]['seed'];(d/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
   with self.assertRaisesRegex(ValueError,'Split leakage'):load(d)
if __name__=='__main__':unittest.main()
