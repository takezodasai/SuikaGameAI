import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_mcts_benchmark import summarize

class BenchmarkAuditTests(unittest.TestCase):
    def fixture(self,directory,**change):
        rows=[]
        for variant,t in [('baseline',110),('optimized',55)]:
            row=dict(fixture='dense.json',variant=variant,repeat=0,iterations=32,depth=4,warmup=False,source_unchanged=True,wall_ms=t,gc0=0,report=dict(source_unchanged=True,prefixes_match=True,profile=None))
            row.update(change);rows.append(row)
        rows += [dict(evt='pair',equal=True),dict(variant='cleanup',scenes_after=0,cleanup_window_ms=2)]
        (directory/'game_00.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
        (directory/'resources.json').write_text('[]');(directory/'gpu.json').write_text('[]')
    def test_null_profile_timing_only_and_speedup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);r=summarize(p)
            self.assertEqual(r['comparisons']['dense:32:d4']['speedup'],2)
            self.assertEqual(r['equal_pairs'],1)
    def test_reject_mutated_live_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p,source_unchanged=False)
            with self.assertRaisesRegex(ValueError,'source'):summarize(p)
    def test_reject_physical_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);f=p/'game_00.jsonl';f.write_text(f.read_text().replace('"equal": true','"equal": false'))
            with self.assertRaisesRegex(ValueError,'mismatch'):summarize(p)
    def test_reject_unreleased_scenes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);f=p/'game_00.jsonl';f.write_text(f.read_text().replace('"scenes_after": 0','"scenes_after": 1'))
            with self.assertRaisesRegex(ValueError,'released'):summarize(p)
