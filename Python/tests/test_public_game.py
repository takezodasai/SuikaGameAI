import importlib.util
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('public_game', ROOT / 'Python/play_public_model.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class PublicGameTests(unittest.TestCase):
    def test_public_checkpoint_and_config(self):
        demo.read_model(demo.MODEL)
        provenance = json.loads(demo.MODEL.with_name('latest_policy_provenance.json').read_text())
        normalized = demo.MODEL.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(normalized).hexdigest(), provenance['published_sha256'])
        cfg = demo.config(Path('demo'), demo.MODEL, 1234, 3, 120)
        self.assertTrue(cfg['normal_start'])
        self.assertEqual((cfg['iterations'], cfg['depth'], cfg['mixture']), (256, 4, .5))
        self.assertEqual(cfg['final_selection'], 'legacy')
        self.assertNotIn('fixture', cfg)

    def test_real_gui_flags(self):
        cmd = demo.command(Path('game.exe'), Path('demo'), 1234, 45900)
        self.assertNotIn('-nographics', cmd)
        self.assertNotIn('-batchmode', cmd)
        self.assertIn('-suikaPolicySelfPlayLab', cmd)

    def test_termination_is_not_fabricated(self):
        end = dict(evt='end', reason='natural_go', natural_go=True, truncated=False, score=100)
        self.assertTrue(demo.summarize([end], 0)['natural_go'])
        self.assertFalse(demo.summarize([end], 1)['natural_go'])
        self.assertFalse(demo.summarize([end], 0, True)['natural_go'])
        self.assertFalse(demo.summarize([], 0)['natural_go'])
        self.assertFalse(demo.summarize([dict(end, reason='drop_limit', truncated=True)], 0)['natural_go'])
        self.assertFalse(demo.summarize([dict(evt='error', error='failure'), end], 0)['natural_go'])

    def test_limits(self):
        with self.assertRaises(ValueError):
            demo.config(Path('demo'), demo.MODEL, 1, 0, 120)


if __name__ == '__main__':
    unittest.main()
