import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from episode_events import audit_events
from suika_ai.parallel_play import player_command,worker_specs
class EventTests(unittest.TestCase):
 def row(self):return dict(state=dict(score=0,fruits=[],episode_events=dict(known=True,source="actual_game",version="step8u-events-v1",drop_count=1,watermelons_created=0,watermelons_present=0,double_watermelons=0,events=[])))
 def test_unknown_not_false(self):self.assertIsNone(audit_events([dict(state={})])["double_watermelon_success"])
 def test_known_zero(self):self.assertFalse(audit_events([self.row()])["double_watermelon_success"])
 def test_prediction_rejected(self):
  r=self.row();r["state"]["episode_events"]["source"]="prediction"
  with self.assertRaises(ValueError):audit_events([r])
 def test_false_counter_rejected(self):
  r=self.row();r["state"]["episode_events"]["double_watermelons"]=1
  with self.assertRaises(ValueError):audit_events([r])
 def test_board_mismatch_rejected(self):
  r=self.row();r["state"]["fruits"]=[dict(type=10)]
  with self.assertRaises(ValueError):audit_events([r])
 def test_regressing_drop_rejected(self):
  r=self.row();s=copy.deepcopy(r);s["state"]["episode_events"]["drop_count"]=0
  with self.assertRaises(ValueError):audit_events([r,s])
 def test_event_opt_in(self):
  s=worker_specs(1)[0];off=player_command("x",s,"log");on=player_command("x",s,"log",episode_events=True)
  self.assertNotIn("--suika-events",off);self.assertEqual(on,off+["--suika-events","1"])

 def test_native_actual_merges_and_double(self):
  import json
  p=Path(__file__).resolve().parents[1]/"outputs/step8u_01/events_test.json"
  if not p.exists():self.skipTest("Native event probe unavailable")
  r=json.loads(p.read_text());self.assertTrue(r["passed"]);s=r["actual_events"]
  self.assertEqual(s["watermelons_created"],2);self.assertEqual(s["double_watermelons"],1)
  row=dict(state=dict(score=110,fruits=[],episode_events=s))
  self.assertTrue(audit_events([row])["double_watermelon_success"])
  bad=copy.deepcopy(row);bad["state"]["episode_events"]["events"][0]["score"]=111
  with self.assertRaises(ValueError):audit_events([bad])
 def test_three_comparison_profiles_are_single_changes(self):
  from adaptive_profiles import profile
  a=profile("legacy",iterations=128);b=profile("grid9",iterations=128);c=profile("widening",iterations=128)
  self.assertEqual({k for k in a if a[k]!=b[k]},{"candidate_count"})
  self.assertEqual({k for k in a if a[k]!=c[k]},{"mcts_widening"})

 def test_interrupted_retry_and_completed_skip(self):
  import tempfile,json
  from unittest.mock import patch
  import compare_placement_mcts as c
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);exe=root/"fake.exe";exe.write_bytes(b"fake")
   job=dict(key="seed_1/legacy",seed=1,iterations="legacy")
   plan=dict(exe=str(exe),exe_sha256=c.sha(exe),assembly_sha256=None,python_sources={},jobs=[job],settings={"legacy":{}},max_steps=8,base_port=39700,step_timeout=120,episode_events=True)
   def launch(exe,folder,**kw):
    folder.mkdir();(folder/"metadata").mkdir()
    for name in ["run.json","game_00.jsonl","metadata/game_00.json"]:(folder/name).write_text("{}\n")
   event=dict(double_watermelon_known=True,double_watermelon_success=False,actual_events=dict(drop_count=1))
   interrupted=dict(termination="stopped",worker_errors=[],successful_drops=1,errors=[])
   done=dict(termination="step_limit",worker_errors=[],successful_drops=1,errors=["not_natural_go:step_limit"])
   with patch.object(c,"run_parallel",side_effect=launch),patch.object(c,"audit_game",return_value=interrupted),patch.object(c,"audit_events",return_value=event),patch.object(c,"summary"):
    with self.assertRaises(RuntimeError):c.run(root,plan)
   base=root/job["key"];self.assertFalse((base/"result.json").exists());self.assertTrue((base/"attempt_000/interrupted_audit.json").exists())
   with patch.object(c,"run_parallel",side_effect=launch),patch.object(c,"audit_game",return_value=done),patch.object(c,"audit_events",return_value=event),patch.object(c,"summary"):c.run(root,plan)
   self.assertTrue((base/"attempt_001/game_00.jsonl").exists())
   with patch.object(c,"run_parallel") as launch_again,patch.object(c,"summary"):c.run(root,plan);launch_again.assert_not_called()
