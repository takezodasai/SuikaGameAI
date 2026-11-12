import importlib.util
import json
import re
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'Python/examples/portfolio'


def module(name):
    spec=importlib.util.spec_from_file_location('portfolio_'+name,HERE/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


class PortfolioTests(unittest.TestCase):
    def test_public_demo_is_normalized_and_reproducible(self):
        demo=module('demo');a=demo.run();self.assertEqual(a,demo.run())
        self.assertEqual([c['x'] for c in a['candidates']],[0,.25,.5,.75,1])
        self.assertAlmostEqual(sum(c['probability'] for c in a['candidates']),1)
        self.assertTrue(all(0<=c['probability']<=1 for c in a['candidates']))

    def test_model_has_native_compatible_schema(self):
        m=json.loads((HERE/'policy.json').read_text());self.assertEqual(len(m['weights']),213)
        self.assertEqual(m['version'],'candidate-linear213-v1')

    def test_frozen_collection_aggregate_is_not_a_strength_claim(self):
        r=json.loads((HERE/'results.json').read_text());cs=r['cohorts']
        self.assertEqual(sum(c['games'] for c in cs),530)
        self.assertEqual(sum(c['new_watermelons'] for c in cs),134)
        self.assertEqual(max(c['max_score'] for c in cs),3341)
        self.assertEqual(sum(c['double_watermelons'] for c in cs),0)
        self.assertFalse(r['raw_games_in_repository'])

    def test_documentation_visual_matches_its_source(self):
        self.assertTrue(module('render_overview').check())

    def test_portfolio_document_links_exist(self):
        for name in ['README.md','docs/ENGINEERING.md','docs/REPRODUCIBILITY.md','docs/RESULTS.md','docs/LATEST_CURRICULUM_RESULTS.md','docs/DEMO_VIDEO_PLAN.md']:
            p=ROOT/name
            for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf8')):
                target=target.split('#')[0]
                if target and not target.startswith(('http:','https:','mailto:')):
                    self.assertTrue((p.parent/target).exists(),f'{name}: {target}')


if __name__=='__main__':unittest.main()
