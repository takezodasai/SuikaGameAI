import json,struct,tempfile,unittest
from pathlib import Path
from suika_ai.unity_env import validate_planning_settings,UnityEnv
from suika_ai.parallel_play import player_command,worker_specs
from suika_ai.presentation import write_control,PresentationControls
from suika_ai.video_viewer import read_frame,ppm,CAPACITY,HEADER,WIDTH,HEIGHT
class PresentationTests(unittest.TestCase):
 def test_legacy_weights(self):
  s=validate_planning_settings(dict(weight_height=100,weight_danger=100));self.assertEqual((s['weight_height'],s['weight_danger']),(0,0))
 def test_audio_defaults(self):
  for i,s in enumerate(worker_specs(4)):
   c=player_command('x',s,'log');self.assertEqual(c[c.index('--suika-audio')+1],'1' if i==0 else '0')
   c=player_command('x',s,'log',True);self.assertEqual(c[c.index('--suika-audio')+1],'0');self.assertNotIn('--suika-video-map',c)
 def test_no_action_or_receiver_change(self):
  e=UnityEnv.__new__(UnityEnv);e.last_state=dict(stream_id='s',game_id='g');e._action_id=9;sent=[];e._send=sent.append
  self.assertTrue(e.request_presentation('audio',False,3));self.assertEqual(e._action_id,9);self.assertEqual(sent[0]['control_revision'],3)
  with self.assertRaises(ValueError):e.request_presentation('audio',1,3)
 def test_control_ack(self):
  class Env:
   last_state={}
   def request_presentation(self,*args):self.sent=args;return True
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'run.json').write_text(json.dumps(dict(run_id='r',workers=[dict(game_id='game_00')],video_game='game_00')))
   row=write_control(p,['game_00'],audio=False);e=Env();ctl=PresentationControls(p,'r',{'game_00':e},'game_00');ctl.poll()
   self.assertEqual(e.sent,('audio',False,row['revision']));e.last_state=dict(audio_revision=row['revision'],audio_enabled=False);ctl.poll()
   self.assertEqual([json.loads(x)['event'] for x in (p/'controls.jsonl').read_text().splitlines()],['requested','acknowledged'])
   bad=dict(row,run_id='wrong');(p/'controls/bad.json').write_text(json.dumps(bad));ctl.poll();self.assertIn('rejected',(p/'controls.jsonl').read_text())
 def test_latest_frame(self):
  a=bytearray(CAPACITY);struct.pack_into('<q',a,0,2);struct.pack_into('<iii',a,8,1,WIDTH,HEIGHT)
  struct.pack_into('<qq',a,24,10,11);struct.pack_into('<iiii',a,40,7,1,3,1);a[HEADER:HEADER+4]=bytes((255,1,2,255))
  f=read_frame(a);self.assertEqual(f['score'],7);self.assertTrue(f['game_over']);self.assertIsNone(read_frame(a,2))
  struct.pack_into('<q',a,0,3);self.assertIsNone(read_frame(a));self.assertIn(b'255\n\xff\x01\x02',ppm(f['rgba'])[:30])


class MultiViewerTests(unittest.TestCase):
 def test_layouts(self):
  from suika_ai.video_viewer import tile_positions
  self.assertEqual(tile_positions(1),[(0,0)])
  self.assertEqual(tile_positions(2),[(0,0),(0,1)])
  self.assertEqual(tile_positions(3),[(0,0),(0,1),(1,0)])
  self.assertEqual(tile_positions(4),[(0,0),(0,1),(1,0),(1,1)])
  with self.assertRaises(ValueError):tile_positions(5)
 def test_display_selection_and_headless(self):
  from suika_ai.parallel_play import selected_video_games
  self.assertEqual(selected_video_games(4,True),[])
  self.assertEqual(selected_video_games(4,view_games=2),['game_00','game_01'])
  self.assertEqual(selected_video_games(4,view_game=3),['game_03'])
  for kwargs in [dict(view_games=5),dict(view_games=-1),dict(view_game=0,view_games=1),dict(headless=True,view_games=1)]:
   with self.assertRaises(ValueError):selected_video_games(4,**kwargs)
 def test_sources(self):
  from suika_ai.video_viewer import viewer_sources
  m=dict(workers=[dict(game_id='game_00'),dict(game_id='game_01')],video_maps={'game_00':'a','game_01':'b'})
  self.assertEqual(viewer_sources(m),[('game_00','a'),('game_01','b')])
  m['video_maps']['game_01']='a'
  with self.assertRaises(ValueError):viewer_sources(m)
  self.assertEqual(viewer_sources(dict(workers=[dict(game_id='game_00')],video_game='game_00',video_map='legacy')),[('game_00','legacy')])
 def test_metrics_bounded(self):
  from suika_ai.video_viewer import FrameMetrics
  m=FrameMetrics()
  for i in range(10000):m.add(i+1,40,7,i/15)
  r=m.result(10000/15);self.assertEqual(r['displayed'],10000);self.assertEqual(r['distribution_samples'],4096)
  self.assertAlmostEqual(r['active_display_fps'],15)
 def test_multi_controls_atomic_and_independent(self):
  class Env:
   last_state={}
   def request_presentation(self,*args):self.sent=args;return True
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);m=dict(run_id='r',workers=[dict(game_id='game_00'),dict(game_id='game_01')],video_maps={'game_00':'a','game_01':'b'})
   (p/'run.json').write_text(json.dumps(m));a,b=Env(),Env();ctl=PresentationControls(p,'r',{'game_00':a,'game_01':b},list(m['video_maps']))
   row=write_control(p,['game_01'],video=False);ctl.poll();self.assertFalse(hasattr(a,'sent'));self.assertEqual(b.sent,('video',False,row['revision']))
   row=write_control(p,['game_00','game_01'],audio=True);ctl.poll();self.assertEqual(a.sent,('audio',True,row['revision']))
   before=dict(ctl.desired)
   bad=dict(run_id='r',revision=row['revision']+1,games=['game_00','game_01'],audio=False,video=1)
   (p/'controls/bad.json').write_text(json.dumps(bad));ctl.poll();self.assertEqual(ctl.desired,before)
