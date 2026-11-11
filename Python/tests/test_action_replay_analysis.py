import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_action_replay import compare_ticks
import copy

class ReplayAnalysisTests(unittest.TestCase):
    def row(self):return dict(state=dict(score=0,game_over=False,current_fruit=dict(type=0),next_fruit_type=1),bodies=dict(fruits=[],events=[]),rng='same',relative_fixed_time=.02)
    def test_equal_score_alone_does_not_verify(self):
        a=self.row();b=copy.deepcopy(a);b['state']['next_fruit_type']=2
        self.assertFalse(compare_ticks(a,b)['within_tolerance'])
    def test_same_public_board_different_rng_is_detected(self):
        a=self.row();b=copy.deepcopy(a);b['rng']='different'
        self.assertFalse(compare_ticks(a,b)['within_tolerance'])
    def test_merge_timing_is_required(self):
        a=self.row();b=copy.deepcopy(a);b['bodies']['events']=['merge:a:b']
        self.assertFalse(compare_ticks(a,b)['within_tolerance'])
    def test_match(self):self.assertTrue(compare_ticks(self.row(),self.row())['within_tolerance'])
    def test_tick_time_mismatch_is_detected(self):
        a=self.row();b=self.row();b['relative_fixed_time']=.04
        self.assertFalse(compare_ticks(a,b)['within_tolerance'])

if __name__=='__main__':unittest.main()
