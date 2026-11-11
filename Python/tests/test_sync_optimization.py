import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from benchmark_sync_optimization import run

class SyncOptimizationBenchmarkTests(unittest.TestCase):
 def exercise(self,change=None):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);fixture=root/'fixture.json';fixture.write_text('{}');output=root/'result'
   class Child:
    returncode=0
    def poll(self):return 0
   def launch(command,**kwargs):
    cfg=json.loads((output/'config.json').read_text());rows=[]
    for cache,ms in [(False,100),(True,90)]:rows.append(dict(evt='search',fixture=str(fixture.resolve()),iterations=32,depth=4,repeat=0,warmup=False,cache=cache,elapsed_ms=ms,source_unchanged=True,lifetime=dict(retained_scenes=1,pending_unloads=0)))
    rows.append(dict(evt='pair',equal=True))
    if change:change(rows)
    Path(cfg['output']).write_text(''.join(json.dumps(r)+'\n' for r in rows));return Child()
   with patch('benchmark_sync_optimization.subprocess.Popen',side_effect=launch):return run(root/'player.exe',output,[fixture],[dict(iterations=32,depth=4)],1)
 def test_matching_work_reports_time_reduction(self):
  r=self.exercise();self.assertEqual(r['exact_pairs'],1);self.assertAlmostEqual(r['results'][0]['time_reduction_percent'],10)
 def test_changed_search_rejected(self):
  with self.assertRaisesRegex(ValueError,'search mismatch'):self.exercise(lambda r:r[-1].update(equal=False))
 def test_live_root_mutation_rejected(self):
  with self.assertRaisesRegex(ValueError,'Root mutation'):self.exercise(lambda r:r[0].update(source_unchanged=False))
 def test_extra_scene_rejected(self):
  with self.assertRaisesRegex(ValueError,'lifetime'):self.exercise(lambda r:r[0]['lifetime'].update(retained_scenes=2))
if __name__=='__main__':unittest.main()
