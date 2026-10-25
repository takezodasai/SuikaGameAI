import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import compare_mcts_ai as comparison
from suika_ai.collection_metadata import canonical


def write_game(root,mode,seed,score):
    folder=root/f'{mode}_{seed}';folder.mkdir();(folder/'metadata').mkdir();g='game_00';stream='s';ep=f'{mode}_{seed}'
    env=dict(rules_version=comparison.RULES_VERSION,game_over_screen_ratio=.83,fruit_assets=[dict(type=i,game_object_tag='Fruit') for i in range(11)])
    eid=hashlib.sha256(canonical(env)).hexdigest()
    (folder/'metadata'/f'{g}.json').write_text(json.dumps(dict(environment=env,environment_id=eid)))
    (folder/'run.json').write_text(json.dumps(dict(settings=comparison.settings(mode),headless=True,exe_sha256='binary',workers=[dict(game_id=g,seed=seed)])))
    base=dict(game_id=g,stream_id=stream,episode_id=ep)
    state=dict(**base,score=0,game_over=False,current_fruit=dict(type=0),next_fruit_type=1,fruits=[],worker_seed=seed,has_worker_seed=True)
    after=dict(state,score=score,game_over=True,current_fruit=dict(type=1),next_fruit_type=2,episode_statistics_known=True,episode_merge_count=1,episode_max_fruit_type=2)
    candidates=[dict(index=i,x=i/4,success=True,drop_success=True,predicted_game_over=False,target_x=-2+i,applied_x=-2+i) for i in range(5)]
    plan=dict(ai_mode=mode,candidates=candidates,selected_index=2,selected_x=.5,all_predicted_terminal=False,evaluated_count=5,same_source_verified=True,held_fruit_type=0,next_fruit_type=1,elapsed_ms=10. if mode=='heuristic' else 30.)
    if mode=='mcts':plan['mcts']=dict(completed_iterations=32,max_depth=3,prefixes_match=True,source_unchanged=True,nodes=[dict(actions=[dict(visits=n) for n in (8,6,6,6,6)])])
    info=dict(planning=plan,score_before=0,requested_x=.5,target_x=0.,applied_x=0.,min_x=-2.,max_x=2.,drop_success=True)
    rows=[dict(**base,event='episode_start',seed=seed,state=state,environment_id=eid),
          dict(**base,event='transition',action_id=1,turn=1,state=after,info=info,score=score,reward=score,between_steps_reward=0,selected_x=.5,environment_id=eid),
          dict(**base,event='episode_end',state=after,game_over=True,truncated=False,reason='game_over',final_score=score,last_observed_score=score,tail_between_steps_reward=0,conserved=True,steps=1,wall_seconds=2.)]
    save(folder,rows);return folder,rows

def save(folder,rows):(folder/'game_00.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')

class MctsComparisonTests(unittest.TestCase):
    def test_natural_paired_game_unit_ci_and_actual_counters(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for seed,h,m in [(1,100,110),(2,200,220)]:
                write_game(root,'heuristic',seed,h);write_game(root,'mcts',seed,m)
            r=comparison.summarize(root)
            self.assertEqual(r['eligible_pairs'],2);self.assertEqual(r['mcts_minus_heuristic']['mean'],15)
            self.assertEqual(r['paired_mean_difference_95ci'],[10.,20.]);self.assertEqual(r['wins']['mcts'],2)
            self.assertEqual(r['modes']['mcts']['merges']['mean'],1)
            self.assertEqual(r['modes']['mcts']['go_confusion']['false_negative'],2)
    def test_one_pair_no_fake_confidence_interval(self):
        self.assertIsNone(comparison.paired_ci([10]))
    def test_sequence_mismatch_excludes_both_scores(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_game(root,'heuristic',1,100);folder,rows=write_game(root,'mcts',1,110)
            rows[1]['state']['next_fruit_type']=3;save(folder,rows)
            r=comparison.summarize(root)
            self.assertEqual(r['eligible_pairs'],0);self.assertIn('public_fruit_sequence_mismatch',r['pairs'][0]['exclusion_reasons'])
            self.assertEqual(r['modes']['heuristic']['scores']['n'],0)
    def test_predicted_pre_drop_go_default_applied_zero_is_not_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for mode in comparison.MODES:
                folder,rows=write_game(root,mode,1,100);row=rows[1];plan=row['info']['planning'];plan.update(selected_index=0,selected_x=0.,all_predicted_terminal=True)
                row['selected_x']=0.;row['info'].update(requested_x=0.,target_x=-2.,applied_x=-2.)
                for c in plan['candidates']:c.update(predicted_game_over=True,drop_success=False,applied_x=0.)
                save(folder,rows)
            r=comparison.summarize(root);self.assertEqual(r['eligible_pairs'],1)
    def test_true_coordinate_error_still_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_game(root,'heuristic',1,100);folder,rows=write_game(root,'mcts',1,110)
            rows[1]['info']['applied_x']=.1;save(folder,rows)
            r=comparison.summarize(root);self.assertEqual(r['eligible_pairs'],0)
            self.assertIn('Actual drop/target',r['pairs'][0]['mcts']['selected_action_errors'][0]['error'])
    def test_old_environment_and_actual_seed_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_game(root,'heuristic',1,100);folder,rows=write_game(root,'mcts',1,110)
            rows[0]['state']['worker_seed']=2;save(folder,rows)
            meta=folder/'metadata/game_00.json';data=json.loads(meta.read_text());data['environment']['rules_version']='old';data['environment_id']=hashlib.sha256(canonical(data['environment'])).hexdigest();meta.write_text(json.dumps(data))
            r=comparison.summarize(root);self.assertEqual(r['eligible_pairs'],0)
            errors=r['pairs'][0]['mcts']['errors'];self.assertIn('requested_vs_actual_seed_mismatch',errors);self.assertIn('wrong_or_missing_rules_version',errors)
    def test_wall_limit_not_natural_go(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_game(root,'heuristic',1,100);folder,rows=write_game(root,'mcts',1,110)
            rows[1]['state']['game_over']=False;rows[-1].update(game_over=False,truncated=True,reason='wall_limit',final_score=None);save(folder,rows)
            r=comparison.summarize(root);self.assertEqual(r['eligible_pairs'],0);self.assertIsNone(r['pairs'][0]['mcts']['final_score'])
    def test_scheduled_missing_pair_reported_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'comparison_plan.json').write_text(json.dumps(dict(seeds=[9])))
            r=comparison.summarize(root);self.assertEqual(r['excluded_pairs'],1)
            prior=(root/'comparison.json').read_bytes()
            with self.assertRaises(FileExistsError):comparison.summarize(root)
            self.assertEqual((root/'comparison.json').read_bytes(),prior)


class RulePreflightTests(unittest.TestCase):
    def test_wrong_player_version_refused_before_play(self):
        from suika_ai.collection_metadata import CollectionMetadata
        class OldPlayer:
            def get_environment(self):return dict(game_over_screen_ratio=.83,rules_version='old',physics_profiles=[])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'metadata.json';metadata=CollectionMetadata(OldPlayer(),path,True,.83,True,comparison.RULES_VERSION)
            with self.assertRaisesRegex(ValueError,'rules_version'):metadata.refresh()
            self.assertFalse(path.exists())
