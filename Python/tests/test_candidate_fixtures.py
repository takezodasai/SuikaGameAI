import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('candidate_fixtures',Path(__file__).parents[1]/'prepare_candidate_fixtures.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CandidateFixturesTests(unittest.TestCase):
    def row(self):
        state=dict(fruits=[],current_fruit=dict(type=0,x=0,y=5,y_known=True),next_fruit_type=1,score=0,game_over=False,drop_cooldown_remaining=0,game_tick=25)
        return dict(action_id=1,state=state,decision_source=state,info=dict(planning=dict(drop_range=dict(left_wall_inner=-3,right_wall_inner=3),floor_y=-4,game_over_y=3)))

    def test_complete_visible_state_is_still_not_native_checkpoint(self):
        f=module.fixture(self.row(),'post_state');self.assertFalse(f['unknown_fields']);self.assertIn('solver_contact_cache',f['missing_native'])

    def test_missing_cooldown_rejected(self):
        r=self.row();del r['state']['drop_cooldown_remaining']
        with self.assertRaises(ValueError):module.fixture(r,'post_state')

    def test_cold_assumption_explicit(self):
        r=self.row();del r['state']['drop_cooldown_remaining'];f=module.fixture(r,'post_state',True)
        self.assertEqual(f['explicit_assumptions']['drop_cooldown_remaining'],0)

    def test_no_geometry_imputation(self):
        r=self.row();r['info']={}
        with self.assertRaises(ValueError):module.fixture(r,'post_state',True)

    def test_no_future_outcome_in_snapshot(self):
        r=self.row();r['final_score']=99999;r['future_series']=[1,2,3]
        f=module.fixture(r,'post_state');self.assertNotIn('final_score',f['snapshot']);self.assertNotIn('future_series',f['snapshot'])

    def test_terminal_rejected(self):
        r=self.row();r['state']['game_over']=True
        with self.assertRaises(ValueError):module.fixture(r,'post_state',True)


if __name__=='__main__':unittest.main()
