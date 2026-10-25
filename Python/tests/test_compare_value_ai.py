"""Regressions for pre-drop predicted GO versus actual drop coordinates."""
import copy,sys,tempfile,unittest,importlib.util,json
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('comparison_under_test',ROOT/'compare_value_ai.py')
comparison=importlib.util.module_from_spec(spec);spec.loader.exec_module(comparison)

def fixture(prediction_dropped=True,actual_dropped=True):
    c=dict(index=0,success=True,x=0.,target_x=-2.7,applied_x=-2.7 if prediction_dropped else 0.,
        drop_success=prediction_dropped,predicted_game_over=not prediction_dropped)
    d=dict(selected_index=0,selected_x=0.,all_predicted_terminal=not prediction_dropped,candidates=[c])
    r=dict(selected_x=0.,state=dict(game_over=not actual_dropped),info=dict(planning=d,drop_success=actual_dropped,
        requested_x=0.,target_x=-2.7,applied_x=-2.7 if actual_dropped else 0.,min_x=-2.7,max_x=2.7))
    return c,r

class ComparisonCoordinateTests(unittest.TestCase):
    def test_both_dropped_and_float_rounding(self):
        c,r=fixture();r['info']['applied_x']+=2.4e-7
        self.assertEqual(comparison.validate_selected_action(c,r)['classification'],'both_dropped')
    def test_predicted_go_before_drop_does_not_compare_default_zero(self):
        c,r=fixture(False,True)
        result=comparison.validate_selected_action(c,r)
        self.assertIsNone(result['predicted_applied_x']);self.assertEqual(result['actual_applied_x'],-2.7)
        self.assertEqual(result['classification'],'prediction_no_drop')
    def test_actual_target_error_still_rejected_without_prediction_drop(self):
        c,r=fixture(False,True);r['info']['applied_x']=-2.6
        with self.assertRaisesRegex(ValueError,'Actual drop/target'):comparison.validate_selected_action(c,r)
    def test_real_prediction_drop_mismatch_not_hidden(self):
        c,r=fixture();c['applied_x']=-2.6
        with self.assertRaisesRegex(ValueError,'Selected drop X mismatch'):comparison.validate_selected_action(c,r)
    def test_wrong_action_rejected(self):
        c,r=fixture(False,True);r['info']['requested_x']=.5
        with self.assertRaisesRegex(ValueError,'Selected/requested'):comparison.validate_selected_action(c,r)
    def test_mismatching_movement_target_rejected(self):
        c,r=fixture(False,True);c['target_x']=-2.5
        with self.assertRaisesRegex(ValueError,'Movement target'):comparison.validate_selected_action(c,r)
    def test_actual_go_before_drop_and_known_predicted_drop(self):
        c,r=fixture(True,False)
        self.assertEqual(comparison.validate_selected_action(c,r)['classification'],'actual_no_drop')
    def test_nonterminal_failed_drop_rejected(self):
        c,r=fixture(True,False);r['state']['game_over']=False
        with self.assertRaisesRegex(ValueError,'no drop without GO'):comparison.validate_selected_action(c,r)
    def test_terminal_candidate_requires_fallback(self):
        c,r=fixture(False,True);r['info']['planning']['all_predicted_terminal']=False
        with self.assertRaisesRegex(ValueError,'Excluded GO'):comparison.validate_selected_action(c,r)
    def test_nonfinite_coordinate_rejected(self):
        c,r=fixture();r['info']['applied_x']=float('nan')
        with self.assertRaises(ValueError):comparison.validate_selected_action(c,r)
    def test_existing_analysis_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'comparison.json';target.write_text('original')
            with self.assertRaises(FileExistsError):comparison.summarize(folder)
            self.assertEqual(target.read_text(),'original')
    def test_report_dir_keeps_source_directory_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'raw';source.mkdir();report=Path(folder)/'report'
            result=comparison.summarize(source,report)
            self.assertEqual(result['eligible_pairs'],0);self.assertEqual(list(source.iterdir()),[])
            self.assertTrue((report/'comparison.json').exists())

    def test_true_mismatch_excludes_pair_and_both_mode_score_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for mode in ('heuristic','value'):
                run=root/mode;run.mkdir()
                (run/'run.json').write_text(json.dumps(dict(settings=dict(ai_mode=mode),workers=[dict(game_id='game_00',seed=1)])))
                c,r=fixture();r['state'].update(game_over=True,score=100)
                r.update(event='transition',turn=1,action_id=1,episode_id='e'+mode)
                d=r['info']['planning'];d.update(held_fruit_type=0,elapsed_ms=1.,evaluated_count=1,same_source_verified=True)
                c['future_value']=10.
                if mode=='heuristic':r['info']['applied_x']=-2.6
                end=dict(event='episode_end',game_over=True,truncated=False,final_score=100,conserved=True)
                (run/'game_00.jsonl').write_text(json.dumps(r)+'\n'+json.dumps(end)+'\n')
            with patch.object(comparison,'validate_run',return_value=[]):result=comparison.summarize(root)
            self.assertEqual(result['eligible_pairs'],0);self.assertEqual(result['excluded_pairs'],1)
            self.assertEqual(len(result['action_errors']),1)
            self.assertEqual(result['modes']['heuristic']['scores']['n'],0)
            self.assertEqual(result['modes']['value']['scores']['n'],0)
