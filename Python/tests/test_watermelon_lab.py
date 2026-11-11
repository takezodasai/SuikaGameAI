import unittest
from watermelon_lab import choose_stages, summarize, public_difference


class WatermelonLabTests(unittest.TestCase):
    def row(self, wm, y=1, go=False):
        fruit=dict(type=10 if wm else 1,x=0,y=y,vx=0,vy=0,angle=0,has_collided=True)
        return dict(state=dict(fruits=[fruit],game_over=go,score=100,current_fruit=dict(type=0),next_fruit_type=1))

    def test_stages_only_use_observed_nonterminal_watermelon(self):
        rows=[self.row(False),self.row(True,1),self.row(True,2),self.row(True,9,True)]
        stages=dict(choose_stages(rows))
        self.assertIs(stages['before'],rows[0]);self.assertIs(stages['after'],rows[1]);self.assertIs(stages['danger'],rows[2])

    def test_missing_success_is_not_synthesized(self):
        with self.assertRaises(StopIteration):choose_stages([self.row(False)])

    def test_truncation_is_not_natural_go_or_historical_teacher(self):
        r=summarize([dict(evt='root'),dict(evt='end',natural_go=False,truncated=True)])
        self.assertFalse(r['natural_go']);self.assertFalse(r['valid_historical_return'])

    def test_native_natural_go_remains_approximate_origin(self):
        r=summarize([dict(evt='root'),dict(evt='end',natural_go=True)])
        self.assertTrue(r['natural_go']);self.assertFalse(r['valid_historical_return'])

    def test_public_difference_detects_velocity_even_if_score_same(self):
        a=self.row(True)['state'];b=self.row(True)['state'];b['fruits'][0]['vx']=.01
        r=public_difference(a,b)
        self.assertTrue(r['score_equal']);self.assertFalse(r['all_compared_fields_equal'])


if __name__=='__main__':unittest.main()
