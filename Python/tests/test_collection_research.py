import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('collection_research',Path(__file__).parents[1]/'analyze_collection_research.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CollectionResearchTests(unittest.TestCase):
    def fixture(self,root,natural=True):
        session=root/'overnight_fixture';job=session/'jobs'/'job_000000';attempt=job/'attempt_000';attempt.mkdir(parents=True)
        (session/'collection.json').write_text(json.dumps(dict(think_seconds=30,workers=2)),encoding='utf8')
        row=dict(natural_go=natural,valid_for_return_learning=natural,errors=[],end_reason='game_over' if natural else 'stopped',attempt=str(attempt),
                 profile=dict(depth=4,iterations=128),player_sha256='example',elapsed_seconds=3600,final_score=100,events_known=False)
        (job/'attempt_000_result.json').write_text(json.dumps(row),encoding='utf8')
        decision=dict(elapsed_ms=1000,actual_iterations=128,root_actions=[dict(visits=64),dict(visits=64)],depth_metrics=[])
        (attempt/'decisions.jsonl').write_text(json.dumps(decision)+'\n',encoding='utf8')
        return session

    def test_quantiles(self):
        self.assertEqual(module.quantile([0,10],.5),5);self.assertIsNone(module.quantile([],.95))

    def test_completed_only_and_worker_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);r=module.analyze(root);s=r['summaries'][0]
            self.assertEqual(r['completed_games'],1);self.assertEqual(s['games_per_worker_hour'],1)
            self.assertEqual(s['events_known_games'],0);self.assertEqual(s['root_normalized_entropy'],1)

    def test_stopped_is_not_natural_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,False);r=module.analyze(root)
            self.assertEqual(r['completed_games'],0);self.assertEqual(len(r['excluded']),1)

    def test_ongoing_has_no_completion_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'overnight_active'/'jobs'/'job_1'/'attempt_000';p.mkdir(parents=True)
            (p/'decisions.jsonl').write_text('{partial')
            self.assertEqual(module.analyze(root)['inventory_files'],0)

    def test_inputs_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            module.analyze(root)
            self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_malformed_result_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=self.fixture(root);p=next(session.glob('jobs/*/*_result.json'));p.write_text('{')
            r=module.analyze(root);self.assertEqual(r['completed_games'],0);self.assertEqual(len(r['excluded']),1)


if __name__=='__main__':unittest.main()
