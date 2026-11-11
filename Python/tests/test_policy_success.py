import copy,tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from suika_ai.policy_success_data import assign_splits,future_labels
from suika_ai.policy_train import sampling_weights
from suika_ai.policy_model import PolicyBoards
from test_mcts_policy import tiny

def episodes():
    result=[]
    for i in range(24):result.append(dict(id='e'+str(i),seed=i,initial_sequence=str(i),previous_split=None,events=dict(labels=dict(watermelon_one=dict(achieved=i%2==0)))))
    for i,role in [(100,'train'),(101,'validation'),(102,'test')]:result.append(dict(id='e'+str(i),seed=i,initial_sequence=str(i),previous_split=role,events=dict(labels=dict(watermelon_one=dict(achieved=False)))))
    return result

class SuccessSplitTests(unittest.TestCase):
    def test_old_roles_protected_and_success_validation(self):
        es=episodes();info=assign_splits(es);by={e['seed']:e for e in es};self.assertEqual(by[100]['split'],'train');self.assertEqual(by[101]['split'],'validation');self.assertEqual(by[102]['split'],'historical_test');self.assertGreaterEqual(info['validation_success_groups'],3)
    def test_test_selection_is_outcome_blind(self):
        a=episodes();b=copy.deepcopy(a)
        for e in b:e['events']['labels']['watermelon_one']['achieved']=not e['events']['labels']['watermelon_one']['achieved']
        assign_splits(a);assign_splits(b);self.assertEqual({e['id'] for e in a if e['split']=='test'},{e['id'] for e in b if e['split']=='test'})
    def test_same_seed_group_cannot_cross_old_test(self):
        es=episodes();e=copy.deepcopy(es[0]);e.update(id='new_alias',seed=102,initial_sequence='alias');es.append(e);assign_splits(es);self.assertEqual(next(e for e in es if e['id']=='new_alias')['split'],'historical_test')
    def test_same_initial_sequence_groups_together(self):
        es=episodes();es[1]['initial_sequence']=es[0]['initial_sequence'];assign_splits(es);self.assertEqual(es[0]['split'],es[1]['split']);self.assertEqual(es[0]['group'],es[1]['group'])

class SuccessSamplingTests(unittest.TestCase):
    def board(self,path):
        b=tiny(path)
        for r in b.records:r['watermelon_success']=r['episode']=='ep0'
        return b
    def test_baseline_weights_match_original_formula(self):
        with tempfile.TemporaryDirectory() as t:
            b=self.board(Path(t)/'data');ids=list(range(6));w,_,_=sampling_weights(b,ids,1);self.assertTrue(torch.equal(w,torch.tensor([1/3]*6,dtype=torch.float64)))
    def test_multiplier_changes_only_sampling_not_labels_or_quality(self):
        with tempfile.TemporaryDirectory() as t:
            b=self.board(Path(t)/'data');original=copy.deepcopy(b.records);ids=list(range(6));a,_,p=sampling_weights(b,ids,1);c,_,q=sampling_weights(b,ids,4)
            self.assertEqual(float(c[0]/a[0]),4);self.assertEqual(float(c[3]/a[3]),1);self.assertAlmostEqual(p,.5);self.assertAlmostEqual(q,.8);self.assertEqual(b.records,original)
    def test_unknown_outcome_is_not_success(self):
        with tempfile.TemporaryDirectory() as t:
            b=self.board(Path(t)/'data');b.records[0]['watermelon_success']=None;w,s,_=sampling_weights(b,list(range(6)),2);self.assertFalse(s[0]);self.assertEqual(float(w[0]),float(w[3]))
    def test_bad_multiplier_rejected(self):
        with self.assertRaises(ValueError):sampling_weights(None,[],float('nan'))
    def test_success_and_future_labels_never_enter_model_inputs(self):
        with tempfile.TemporaryDirectory() as t:
            b=self.board(Path(t)/'data');a=b.batch([0,1])[0]
            for r in b.records:r['watermelon_success']=True;r['future_targets']={'additional_points':99999,'double':True}
            c=b.batch([0,1])[0];self.assertTrue(all(torch.equal(x,y) for x,y in zip(a,c)))

class FutureLabelTests(unittest.TestCase):
    def record(self):return dict(score=100,action_id=5,source_drop_count=None,reward=10000)
    def ep(self,events=None,known=True):return dict(final_score=500,terminal_events=dict(source='actual_game',known=known,events=events or []))
    def event(self,score=200,drop=8):return dict(kind='watermelon_created',score=score,drop_count=drop)
    def test_additional_points_are_not_double_counted(self):
        r=future_labels(self.record(),self.ep(),{});self.assertEqual(r['additional_points']['value'],400)
    def test_unknown_legacy_event_absence_stays_unknown(self):
        r=future_labels(self.record(),self.ep(known=False),{});self.assertIsNone(r['future_watermelon_created']['value']);self.assertIsNone(r['future_watermelon_melon_two']['value'])
    def test_known_absence_is_failure(self):
        r=future_labels(self.record(),self.ep(),{});self.assertTrue(r['future_double_watermelon']['known']);self.assertFalse(r['future_double_watermelon']['value'])
    def test_future_event_by_score_is_positive(self):
        r=future_labels(self.record(),self.ep([self.event()]),{});self.assertTrue(r['future_watermelon_created']['value'])
    def test_equal_score_without_clock_is_unknown(self):
        r=future_labels(self.record(),self.ep([self.event(100)]),{});self.assertIsNone(r['future_watermelon_created']['value'])
    def test_known_drop_order_resolves_equal_score(self):
        record=self.record();record['source_drop_count']=5;r=future_labels(record,self.ep([self.event(100,8)]),{});self.assertTrue(r['future_watermelon_created']['value'])
    def test_past_event_is_not_new_future_success(self):
        r=future_labels(self.record(),self.ep([self.event(50)]),{});self.assertFalse(r['future_watermelon_created']['value'])
    def test_later_snapshot_is_positive_not_absence_proof(self):
        r=future_labels(self.record(),self.ep(),{'future_watermelon_melon_one':[6]});self.assertTrue(r['future_watermelon_melon_one']['value']);self.assertIsNone(r['future_watermelon_melon_two']['value'])
    def test_past_snapshot_cannot_label_future(self):
        r=future_labels(self.record(),self.ep(),{'future_watermelon_melon_one':[4]});self.assertIsNone(r['future_watermelon_melon_one']['value'])
    def test_terminal_positive_board_is_later_positive_evidence(self):
        ep=self.ep();ep['terminal_coexistence']={'future_watermelon_melon_one':True};r=future_labels(self.record(),ep,{});self.assertTrue(r['future_watermelon_melon_one']['value'])
    def test_terminal_absence_does_not_disprove_transient_success(self):
        ep=self.ep();ep['terminal_coexistence']={'future_watermelon_melon_one':False};r=future_labels(self.record(),ep,{});self.assertIsNone(r['future_watermelon_melon_one']['value'])

if __name__=='__main__':unittest.main()
