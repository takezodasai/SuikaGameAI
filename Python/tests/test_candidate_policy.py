import tempfile, unittest
from pathlib import Path
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel

class CandidatePolicyTests(unittest.TestCase):
    def test_legacy_defaults_and_opt_in(self):
        self.assertEqual(validate_planning_settings({})['candidate_policy'],'grid')
        s=validate_planning_settings(dict(ai_mode='mcts',candidate_policy='board-five',mcts_iterations=32,mcts_max_depth=4))
        self.assertEqual((s['candidate_count'],s['mcts_iterations'],s['mcts_max_depth'],s['post_drop_steps']),(5,32,4,25))
    def test_invalid_combinations(self):
        for patch in [dict(candidate_policy='unknown'),dict(ai_mode='heuristic'),dict(candidate_count=7),dict(execution_mode='frames'),dict(frame_tick_slicing=True)]:
            args=dict(ai_mode='mcts',candidate_policy='board-five');args.update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):validate_planning_settings(args)
    def test_multi_game_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'test.exe';exe.write_bytes(b'not executed');out=Path(directory)/'output'
            with self.assertRaises(ValueError):run_parallel(exe,out,games=4,settings=dict(ai_mode='mcts',candidate_policy='board-five'))
            self.assertFalse(out.exists())

class CandidateLogTests(unittest.TestCase):
    def data(self,policy='board-five'):
        xs=[0,.2,.5,.7,1] if policy=='board-five' else [0,.25,.5,.75,1]
        return [dict(event='transition',info=dict(planning=dict(settings=dict(candidate_policy=policy),mcts=dict(candidate_policy=policy,nodes=[dict(actions=[dict(x=x) for x in xs])]),candidates=[dict(x=x) for x in xs])))]
    def test_logged_node_mapping_and_legacy_grid(self):
        from compare_candidate_ai import validate_geometry
        validate_geometry(self.data(),'board-five');validate_geometry(self.data('grid'),'grid')
        bad=self.data();bad[0]['info']['planning']['mcts']['nodes'][0]['actions'][1]['x']=.3
        with self.assertRaises(ValueError):validate_geometry(bad,'board-five')
    def test_old_player_and_illegal_coordinates_rejected(self):
        from compare_candidate_ai import validate_geometry
        bad=self.data();bad[0]['info']['planning']['mcts'].pop('candidate_policy')
        with self.assertRaises(ValueError):validate_geometry(bad,'board-five')
        bad=self.data();bad[0]['info']['planning']['candidates'][3]['x']=1.2
        with self.assertRaises(ValueError):validate_geometry(bad,'board-five')
    def test_runtime_budget_fixed(self):
        from compare_candidate_ai import settings
        for policy in ('grid','board-five'):
            s=settings(policy);self.assertEqual((s['mcts_iterations'],s['mcts_max_depth'],s['candidate_count'],s['post_drop_steps']),(32,4,5,25))

class CandidatePairAuditTests(unittest.TestCase):
    def fixture(self,root,seed,policy,score,truncated=False):
        import json
        from test_compare_mcts_ai import write_game,save
        from compare_candidate_ai import settings
        folder,rows=write_game(root,'mcts',seed,score)
        manifest=json.loads((folder/'run.json').read_text());manifest['settings']=settings(policy)
        (folder/'run.json').write_text(json.dumps(manifest))
        plan=rows[1]['info']['planning'];plan['settings']=settings(policy);plan['mcts'].update(max_depth=4,candidate_policy=policy)
        for i,a in enumerate(plan['mcts']['nodes'][0]['actions']):a['x']=i/4
        if truncated:
            rows[1]['state']['game_over']=False;rows[-1].update(game_over=False,truncated=True,reason='step_limit',final_score=None)
        save(folder,rows)
        target=root/f'seed_{seed}'/policy;target.parent.mkdir(exist_ok=True);folder.rename(target)
        return target,rows
    def test_paired_games_ci_and_no_overwrite(self):
        import json
        from compare_candidate_ai import summarize
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[1,2],purpose='paired_strength_comparison')))
            for seed,a,b in [(1,100,110),(2,200,220)]:
                self.fixture(root,seed,'grid',a);self.fixture(root,seed,'board-five',b)
            r=summarize(root);self.assertEqual(r['eligible_pairs'],2);self.assertEqual(r['board_minus_grid']['mean'],15);self.assertEqual(r['paired_mean_difference_95ci'],[10.,20.])
            before=(root/'candidate_comparison.json').read_bytes()
            with self.assertRaises(FileExistsError):summarize(root)
            self.assertEqual((root/'candidate_comparison.json').read_bytes(),before)
    def test_smoke_truncation_is_not_strength_data(self):
        import json
        from compare_candidate_ai import summarize
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[1],purpose='pipeline_smoke_not_strength')))
            self.fixture(root,1,'grid',100,True);self.fixture(root,1,'board-five',110,True)
            r=summarize(root);self.assertEqual(r['status'],'smoke_completed_not_strength');self.assertEqual(r['eligible_pairs'],0);self.assertIsNone(r['pairs'][0]['difference']);self.assertEqual(r['modes']['grid']['scores']['n'],0)
    def test_real_drop_mismatch_is_excluded(self):
        import json
        from compare_candidate_ai import summarize
        from test_compare_mcts_ai import save
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[1],purpose='paired_strength_comparison')))
            self.fixture(root,1,'grid',100);folder,rows=self.fixture(root,1,'board-five',110)
            rows[1]['info']['applied_x']=.2;save(folder,rows)
            self.assertEqual(summarize(root)['eligible_pairs'],0)
