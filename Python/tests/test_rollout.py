import unittest,tempfile,json
from pathlib import Path
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
import test_fixed_grid
from test_compare_mcts_ai import save
import compare_rollout_ai as comparison

class RolloutTests(unittest.TestCase):
    def test_default_legacy_and_opt_in(self):
        s=validate_planning_settings({});self.assertEqual(s['rollout_policy'],'random');self.assertFalse(s['mcts_common_chance'])
        for e in [.1,.5]:self.assertEqual(validate_planning_settings(dict(ai_mode='mcts',rollout_policy='guided',rollout_random_probability=e,mcts_common_chance=True))['rollout_random_probability'],e)
    def test_invalid_modes_and_probabilities(self):
        for patch in [dict(rollout_policy='wrong'),dict(rollout_random_probability=-.1),dict(rollout_random_probability=1.1),dict(rollout_random_probability=float('nan')),dict(mcts_common_chance=1),dict(execution_mode='frames'),dict(ai_mode='value')]:
            s=dict(ai_mode='mcts',rollout_policy='guided');s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_guard_before_creation(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'fake.exe';exe.write_bytes(b'fake');out=Path(d)/'out'
            with self.assertRaises(ValueError):run_parallel(exe,out,games=4,settings=dict(ai_mode='mcts',rollout_policy='guided'))
            self.assertFalse(out.exists())
    def fixture(self,root,policy,score,truncated=False):
        folder,rows=test_fixed_grid.FixedGridTests().fixture(root,1,'grid5',score,truncated);s=comparison.settings(policy)
        manifest=json.loads((folder/'run.json').read_text());manifest['settings']=s;(folder/'run.json').write_text(json.dumps(manifest))
        p=rows[1]['info']['planning'];p['settings']=s;p['mcts'].update(rollout_policy=s['rollout_policy'],common_chance=True,common_chance_samples=[0]*128,iterations=[dict(iteration=0,chance_slots=[0,0,-2,-1])])
        save(folder,rows);target=folder.parent/policy;folder.rename(target);return target,rows
    def pair(self,root,truncated=False):
        (root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[1],purpose='pipeline_smoke_not_strength' if truncated else 'paired_strength_comparison')))
        self.fixture(root,'random',100,truncated);return self.fixture(root,'guided90',110,truncated)
    def test_natural_pair_and_maximum_fruit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.pair(root);r=comparison.summarize(root);self.assertEqual(r['eligible_pairs'],1);self.assertEqual(r['guided_minus_random']['mean'],10);self.assertEqual(r['modes']['guided90']['maximum_fruit_type']['mean'],2)
    def test_truncated_not_go(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.pair(root,True);r=comparison.summarize(root);self.assertEqual(r['status'],'smoke_completed_not_strength');self.assertEqual(r['eligible_pairs'],0)
    def test_wrong_chance_or_executed_settings_excluded(self):
        for kind in ['chance','settings','paired_table']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                root=Path(d);folder,rows=self.pair(root);p=rows[1]['info']['planning']
                if kind=='chance':p['mcts']['iterations'][0]['chance_slots'][0]=1
                elif kind=='settings':p['settings']['rollout_random_probability']=.5
                else:p['mcts']['common_chance_samples'][100]=1
                save(folder,rows);self.assertEqual(comparison.summarize(root)['eligible_pairs'],0)
