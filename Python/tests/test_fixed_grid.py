import json,tempfile,unittest,copy
from pathlib import Path
from compare_grid_ai import settings,summarize,validate_geometry
from test_compare_mcts_ai import write_game,save
from suika_ai.unity_env import validate_planning_settings

class FixedGridTests(unittest.TestCase):
    def fixture(self,root,seed,label,score,truncated=False):
        folder,rows=write_game(root,'mcts',seed,score);s=settings(label);n=s['candidate_count']
        manifest=json.loads((folder/'run.json').read_text());manifest['settings']=s;(folder/'run.json').write_text(json.dumps(manifest))
        p=rows[1]['info']['planning'];p.update(settings=s,evaluated_count=n,selected_index=n//2)
        p['candidates']=[dict(index=i,x=i/(n-1),success=True,drop_success=True,predicted_game_over=False,target_x=-2+4*i/(n-1),applied_x=-2+4*i/(n-1)) for i in range(n)]
        actions=[dict(x=i/(n-1),visits=32//n+(i<32%n)) for i in range(n)]
        p['mcts'].update(max_depth=4,candidate_policy='grid',nodes=[dict(actions=actions)])
        if truncated:rows[1]['state']['game_over']=False;rows[-1].update(game_over=False,truncated=True,reason='step_limit',final_score=None)
        save(folder,rows);target=root/f'seed_{seed}'/label;target.parent.mkdir(exist_ok=True);folder.rename(target);return target,rows
    def setup_pair(self,root,purpose='paired_strength_comparison'):
        (root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[1],purpose=purpose)))
        self.fixture(root,1,'grid5',100,purpose!='paired_strength_comparison');return self.fixture(root,1,'grid9',110,purpose!='paired_strength_comparison')
    def test_settings_and_default_retained(self):
        self.assertEqual(validate_planning_settings({})['candidate_count'],5)
        for label,n in [('grid5',5),('grid9',9)]:
            s=validate_planning_settings(settings(label));self.assertEqual((s['candidate_count'],s['mcts_iterations'],s['mcts_max_depth'],s['post_drop_steps']),(n,32,4,25))
    def test_pair_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_pair(root);r=summarize(root);self.assertEqual(r['eligible_pairs'],1);self.assertEqual(r['nine_minus_five']['mean'],10);self.assertIsNone(r['paired_mean_difference_95ci'])
            with self.assertRaises(FileExistsError):summarize(root)
    def test_future_grid_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,rows=self.fixture(root,1,'grid9',110);p=rows[1]['info']['planning'];p['mcts']['nodes'].append(copy.deepcopy(p['mcts']['nodes'][0]));p['mcts']['nodes'][1]['actions'][1]['x']=.25
            with self.assertRaisesRegex(ValueError,'Future node'):validate_geometry(rows,'grid9')
    def test_smoke_not_strength(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_pair(root,'pipeline_smoke_not_strength');r=summarize(root);self.assertEqual(r['status'],'smoke_completed_not_strength');self.assertEqual(r['eligible_pairs'],0)
    def test_real_drop_error_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,rows=self.setup_pair(root);rows[1]['info']['applied_x']=.2;save(folder,rows);self.assertEqual(summarize(root)['eligible_pairs'],0)
