import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from candidate_ridge import features,fit,predict,load_teachers,infer_public


def row(i,seed=None):
    seed=100+i if seed is None else seed
    s=dict(fruits=[dict(id=i,type=i%4,x=i/10,y=i/20,vx=.1,vy=0,half_width=.3,half_height=.3)],geometry=[-3,3,-4,3],current_fruit=dict(present=True,type=1),next_fruit_type=2,score=1000+100*i)
    cs=[dict(visits=100,mean_points=30+i,sd_points=10,terminal_returns=0),dict(visits=28,mean_points=25,sd_points=5,terminal_returns=0)]
    return dict(input=dict(state=s,coordinates_A_B=[.25,.75],mcts_statistics_A_B=cs),target=dict(mean_return_A=500,mean_return_B=500+i*10,mean_delta_B_minus_A=i*10),provenance=dict(source_seed=seed,source_initial_sequence='p'+str(i),split_keys=['game_seed:'+str(seed),'initial8:p'+str(i)],policy_id='legacy'),ridge_group=seed)


class RidgeTests(unittest.TestCase):
    def test_features_ignore_future_labels_and_ids_and_do_not_mutate_input(self):
        r=row(1);original=copy.deepcopy(r);i=r['input'];a=features(i['state'],i['coordinates_A_B'],i['mcts_statistics_A_B'])
        self.assertEqual(r,original);r['target']['mean_return_B']=99999;i['state']['final_score']=99999;i['state']['future_seed']=7;i['state']['fruits'][0]['id']=999
        np.testing.assert_array_equal(a,features(i['state'],i['coordinates_A_B'],i['mcts_statistics_A_B']));self.assertEqual(a.shape,(20,))
    def test_load_deduplicates_and_unions_original_seed(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.jsonl';p.write_text('\n'.join(json.dumps(row(i,seed=1 if i<2 else None)) for i in range(4)))
            rs=load_teachers([p,p],dict(episodes=[]));self.assertEqual(len(rs),4)
            self.assertEqual(rs[0]['ridge_group'],rs[1]['ridge_group']);self.assertEqual(len({r['ridge_group'] for r in rs}),3)
    def test_conflicting_duplicate_and_policy_mix_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.jsonl';a=row(1);b=copy.deepcopy(a);b['target']['mean_return_B']+=1
            p.write_text(json.dumps(a)+'\n'+json.dumps(b))
            with self.assertRaises(ValueError):load_teachers([p],dict(episodes=[]))
            b=row(2);b['provenance']['policy_id']='other';p.write_text(json.dumps(a)+'\n'+json.dumps(b))
            with self.assertRaises(ValueError):load_teachers([p],dict(episodes=[]))
    def test_reserved_group_rejected_by_seed_or_prefix(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.jsonl';p.write_text(json.dumps(row(1)))
            for seed,prefix in [(101,'else'),(999,'p1')]:
                with self.assertRaises(ValueError):load_teachers([p],dict(episodes=[dict(seed=seed,initial_sequence=prefix)]))
    def test_training_normalization_and_deterministic_save_reload(self):
        rs=[row(i) for i in range(5)];m=fit(rs);self.assertAlmostEqual(m['mean'][9],np.mean([(1000+i*100)/3000 for i in range(5)]))
        np.testing.assert_allclose(m['coef'],fit(rs)['coef']);r=row(6);i=r['input'];x=features(i['state'],i['coordinates_A_B'],i['mcts_statistics_A_B'])
        self.assertEqual(predict(m,x),predict(json.loads(json.dumps(m)),x))
    def test_uncertain_and_ood_predictions_keep_A(self):
        m=fit([row(i) for i in range(5)]);m['intercept']=100;m['coef']=[0.0]*20;m['residual_scale']=1000
        self.assertFalse(predict(m,m['mean'])['choose_B'])
        m['intercept']=10000;x=np.array(m['mean']);x[0]+=100*m['scale'][0]
        self.assertTrue(predict(m,x)['ood']);self.assertFalse(predict(m,x)['choose_B']);self.assertTrue(predict(m,x,guard=False)['choose_B'])
    def test_launch_flag_matches_native_installer(self):
        root=Path(__file__).resolve().parents[2]
        native=(root/'Unity/Assets/Scenes/Script/SuikaCandidateRidgeLab.cs').read_text(encoding='utf8')
        runner=(root/'Python/play_candidate_ridge.py').read_text(encoding='utf8')
        self.assertIn('Array.IndexOf(a,"-suikaCandidateRidgeLab")',native);self.assertIn("'-suikaCandidateRidgeLab'",runner)
        self.assertNotIn('Array.IndexOf(a,"-suikaAlternativeActionLab")',native)
    def test_public_decision_rejects_known_GO_B_even_for_large_positive_prediction(self):
        rs=[row(i) for i in range(5)];m=fit(rs);m['intercept']=10000;m['coef']=[0.0]*20;m['max_abs_z']=1000
        inp=row(2)['input'];inp['mcts_statistics_A_B'][1]['immediate_go']=True
        self.assertFalse(infer_public(m,inp)['choose_B']);self.assertEqual(infer_public(m,inp)['selected_x'],.25)
    def test_public_inference_saved_model_matches_low_level(self):
        m=json.loads(json.dumps(fit([row(i) for i in range(5)])));inp=row(2)['input']
        for s in inp['mcts_statistics_A_B']:s['immediate_go']=False
        raw=predict(m,features(inp['state'],inp['coordinates_A_B'],inp['mcts_statistics_A_B']));public=infer_public(m,inp)
        self.assertEqual(raw['predicted_delta'],public['predicted_delta']);self.assertEqual(raw['choose_B'],public['choose_B'])


if __name__=='__main__':unittest.main()
