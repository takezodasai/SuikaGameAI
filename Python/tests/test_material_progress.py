import copy
import unittest
from material_progress import analyze, future_labels, bonus_points, rates, select_fixture, conditions, VERSION, GOALS


def row(evt,types=(),events=(),tick=0,score=0,drops=0,native=True,**kw):
    raw=dict(source='actual_game',known=True)
    if native:raw['materials']=dict(version=VERSION,known=True,events=list(events))
    return dict(evt=evt,state=dict(fruits=[dict(type=t) for t in types]),raw_events=raw,
                tick=tick,score=score,accepted_drops=drops,**kw)


def event(kind,initial=False,event_id=1):
    return dict(kind=kind,initial=initial,event_id=event_id,tick=10,score=100,drop_count=2)


class MaterialProgressTests(unittest.TestCase):
    def terminal(self,types=(),events=(),native=True):
        return row('end',types,events,tick=20,score=150,drops=5,native=native,natural_go=True,truncated=False,reason='natural_go')

    def test_material_combinations_are_not_a_required_linear_path(self):
        c=conditions(dict(fruits=[dict(type=10),dict(type=9)]))
        self.assertTrue(c['watermelon_melon']);self.assertFalse(c['watermelon_pineapple'])

    def test_imported_material_is_not_new_success(self):
        e=[event('watermelon_one',True),event('watermelon_melon',True,2)]
        p=analyze([row('root',[10,9],e),self.terminal([10,9],e)])
        self.assertTrue(p['goals']['watermelon_melon']['initial'])
        self.assertFalse(p['goals']['watermelon_melon']['new'])

    def test_atomic_transient_pair_retained_after_disappearance(self):
        es=[event('two_watermelons'),event('double_watermelon',False,2)]
        p=analyze([row('root'),self.terminal([],es)])
        self.assertTrue(p['goals']['two_watermelons']['new'])
        self.assertTrue(p['goals']['double_watermelon']['new'])
        self.assertEqual(p['goals']['two_watermelons']['post_attainment_survival_drops'],3)
        self.assertEqual(p['goals']['two_watermelons']['post_attainment_points'],50)

    def test_missing_old_pineapple_observation_is_unknown(self):
        p=analyze([row('root',native=False),self.terminal(native=False)])
        self.assertIsNone(p['goals']['watermelon_pineapple']['new'])

    def test_old_observed_positive_is_evidence_without_exact_negative(self):
        p=analyze([row('root',native=False),row('action',[10,8],native=False),self.terminal(native=False)])
        self.assertTrue(p['goals']['watermelon_pineapple']['new'])
        self.assertEqual(p['goals']['watermelon_pineapple']['first']['evidence'],'sampled_actual_board')
        self.assertFalse(p['atomic_complete'])

    def test_incomplete_atomic_game_not_negative_label(self):
        p=analyze([row('root'),row('end',natural_go=False,truncated=True,reason='drop_limit')])
        self.assertIsNone(p['goals']['two_watermelons']['new'])

    def test_complete_atomic_absence_is_known_negative(self):
        p=analyze([row('root'),self.terminal()])
        self.assertFalse(p['goals']['two_watermelons']['new'])

    def test_prediction_events_rejected(self):
        rows=[row('root',[10]),self.terminal([10],[event('double_watermelon')])]
        for r in rows:r['raw_events']['source']='prediction_scene'
        p=analyze(rows)
        self.assertIsNone(p['goals']['double_watermelon']['new'])
        self.assertIsNone(p['goals']['watermelon_one']['initial'])

    def test_future_targets_only_before_first_achievement(self):
        es=[event('watermelon_one')];a=row('decision');b=row('decision',[10],es)
        rows=[row('root'),a,b,self.terminal([10],es)]
        self.assertTrue(future_labels(rows,a)['watermelon_one'])
        self.assertIsNone(future_labels(rows,b)['watermelon_one'])

    def test_bonus_unknown_and_already_achieved_not_paid(self):
        self.assertEqual(bonus_points(dict(watermelon_pineapple=None,double_watermelon=True),10),200)
        self.assertEqual(bonus_points({},10),0)
        self.assertEqual(bonus_points(dict(double_watermelon=True),0),0)
        with self.assertRaises(ValueError):bonus_points({},101)

    def test_rates_exclude_imported_goal_from_at_risk(self):
        es=[event('watermelon_one',True)]
        a=analyze([row('root',[10],es),self.terminal([10],es)])
        b=analyze([row('root'),self.terminal()])
        r=rates([a,b])['watermelon_one']
        self.assertEqual(r['initial'],1);self.assertEqual(r['at_risk'],1)
        self.assertEqual(r['evaluable'],1);self.assertEqual(r['newly_achieved'],0)

    def test_selection_covers_only_available_progress_phases(self):
        fs=[dict(stage='pre_watermelon',source_seed=1),dict(stage='watermelon_melon',source_seed=2),dict(stage='late',source_seed=3)]
        xs=[select_fixture(fs,i,'progress-balanced')['source_seed'] for i in range(4)]
        self.assertEqual(xs,[1,2,1,2])
        self.assertEqual(select_fixture(fs,2,'legacy')['source_seed'],3)

    def test_one_snapshot_can_represent_multiple_observed_goals(self):
        fs=[dict(stage='watermelon_one',stages=['watermelon_one','watermelon_pineapple'],source_seed=1)]
        self.assertEqual(select_fixture(fs,1,'progress-balanced')['source_seed'],1)

    def test_analysis_does_not_mutate_input(self):
        rs=[row('root'),self.terminal()];before=copy.deepcopy(rs);analyze(rs)
        self.assertEqual(before,rs)

    def test_invalidated_native_observer_does_not_prove_absence(self):
        a=row('root');b=self.terminal();b['raw_events']['materials']['known']=False
        self.assertIsNone(analyze([a,b])['goals']['watermelon_melon']['new'])

    def test_legacy_fixture_zero_counter_is_not_valid_negative(self):
        a=row('root',[10],native=False);b=self.terminal([10],native=False)
        for r in [a,b]:r['raw_events']['learning']=dict(known=True,watermelons_present=0,melons_present=0,events=[])
        self.assertIsNone(analyze([a,b])['goals']['watermelon_melon']['new'])

    def test_trusted_old_normal_callback_can_prove_supported_absence(self):
        a=row('root',native=False);b=self.terminal(native=False)
        for r in [a,b]:r['raw_events']['learning']=dict(known=True,watermelons_present=0,melons_present=0,events=[])
        p=analyze([a,b]);self.assertFalse(p['goals']['watermelon_melon']['new'])
        self.assertIsNone(p['goals']['watermelon_melon_pineapple']['new'])


if __name__=='__main__':unittest.main()
