import json,tempfile,unittest
from pathlib import Path
try:import torch
except ImportError:raise unittest.SkipTest('Use Python/.venv for value model tests')
from suika_ai.value_model import ValueNetwork,batch,encoded_rows,predict
from suika_ai.value_data import prepare
from suika_ai.value_train import train,load_model
from suika_ai.value_checkpoint import load_checkpoint
from test_value_data import state,episode

class ValueModelTests(unittest.TestCase):
 def test_permutation_padding_empty_large_unknown_next(self):
  torch.set_num_threads(1);torch.manual_seed(2);model=ValueNetwork().eval()
  s=state();f=s['fruits'][0];s['fruits']=[dict(f,id=i+1,x=i*.01,type=i%11) for i in range(300)]
  a=dict(state=s,geometry=None);b=dict(state=dict(s,fruits=list(reversed(s['fruits']))),geometry=None)
  empty=dict(state=dict(s,fruits=[],next_fruit_type=-1),geometry=None)
  values=predict(model,[a,b,empty]);self.assertTrue(all(torch.isfinite(torch.tensor(values))));self.assertAlmostEqual(values[0],values[1],places=3)
  single=predict(model,[empty])[0];self.assertAlmostEqual(single,values[2],places=3)
  terminal=dict(state=dict(s,game_over=True),geometry=None);self.assertEqual(predict(model,[terminal])[0],0)
 def test_mid_epoch_resume_and_corruption_fallback(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for i in range(8):
    p=root/f'run{i}';p.mkdir();rows=episode(i%2)
    for row in rows:row['episode_id']=f'e{i}';row['state']['episode_id']=f'e{i}'
    (p/'run.json').write_text(json.dumps(dict(workers=[dict(game_id='game_00',seed=i%2)])))
    (p/'game_00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
   prepare([root],root/'data')
   cfg=dict(epochs=2,batch_size=2,seed=44)
   train(root/'data',root/'continuous',cfg)
   stopped=train(root/'data',root/'resumed',cfg,max_updates=1);self.assertEqual(stopped['updates'],1);self.assertEqual(stopped['epoch'],0)
   train(root/'data',root/'resumed',dict(epochs=2),resume=True)
   a,_=load_checkpoint(root/'continuous/checkpoints');b,path=load_checkpoint(root/'resumed/checkpoints')
   self.assertTrue(torch.equal(a['rng']['torch'],b['rng']['torch']));self.assertEqual(a['rng']['python'],b['rng']['python']);self.assertEqual(a['rng']['numpy'],b['rng']['numpy']);self.assertEqual(a['updates'],b['updates']);self.assertEqual(a['scheduler'],b['scheduler']);self.assertEqual(a['order'],b['order'])
   for key in a['model']:self.assertTrue(torch.equal(a['model'][key],b['model'][key]),key)
   for index,value in a['optimizer']['state'].items():
    for key,item in value.items():
     if torch.is_tensor(item):self.assertTrue(torch.equal(item,b['optimizer']['state'][index][key]))
   path.write_bytes(b'INTENTIONALLY CORRUPTED TEST ARTIFACT')
   restored,other=load_checkpoint(root/'resumed/checkpoints');self.assertNotEqual(path,other);self.assertLessEqual(restored['updates'],b['updates'])
   (root/'resumed/checkpoints/latest.json').write_text('{truncated pointer')
   restored,other=load_checkpoint(root/'resumed/checkpoints');self.assertLessEqual(restored['updates'],b['updates'])
