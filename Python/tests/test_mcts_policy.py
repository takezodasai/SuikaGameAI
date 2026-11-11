import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from suika_ai.policy_data import teacher,load,VERSION
from suika_ai.policy_model import PolicyNetwork,PolicyBoards
from suika_ai.policy_train import train,load_model
from suika_ai.value_data import INPUT_SPEC
from suika_ai.learning_events import extract,rewards

def transition():
    actions=[dict(index=i,x=x,visits=v,mean_points=float(i),immediate_go=False) for i,(x,v) in enumerate(zip([0.,.5,1.],[1,30,1]))]
    p=dict(ai_mode='mcts',status='selected',same_source_verified=True,partial_plan=False,source_state_id=2,held_fruit_type=0,next_fruit_type=1,selected_index=1,selected_x=.5,drop_range=dict(left_wall_inner=-3,right_wall_inner=3),floor_y=-4,game_over_y=3.3,
           candidates=[dict(x=a['x']) for a in actions],mcts=dict(nodes=[dict(depth=0,actions=actions)],completed_iterations=32,requested_iterations=128,max_depth=4,seed=8191,budget_stop_reason='time_limit',elapsed_ms=120000,time_limit_ms=120000))
    return dict(episode_id='ep',decision_source=dict(episode_id='ep',state_id=2,score=5,fruits=[],current_fruit=dict(type=0,x=0.),next_fruit_type=1,fixed_delta_time=.02,move_speed=3.75),info=dict(planning=p,score_before=5,drop_success=True,applied_normalized_x=.5),state=dict(score=999999),reward=0)

def tiny(path):
    path.mkdir();rows=[]
    for i in range(18):
        split=['train','validation','test'][i//6]
        rows.append(dict(episode='ep'+str(i//3),group='g'+str(i//3),seed=i//3,split=split,candidate_x=[0.,.5,1.],visits=[1,30,1],mean_points=[0.,10.,0.],selected_index=1,selected_x=.5,quality_weight=1.,actual_iterations=32,depth=4,score=0,final_score=10))
    g=np.zeros((18,37),dtype=np.float32);g[:,24]=.5;g[:,0]=1;g[:,22]=1
    np.savez(path/'features.npz',fruits=np.zeros((18,30),dtype=np.float32),offsets=np.arange(19),globals=g)
    (path/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    m=dict(version=VERSION,input_spec=INPUT_SPEC,sample_count=18,split_seed=1,split_groups=dict(train=2,validation=2,test=2),split_games=dict(train=2,validation=2,test=2),files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()})
    (path/'manifest.json').write_text(json.dumps(m));return PolicyBoards(load(path))

class PolicyDataTests(unittest.TestCase):
    def test_input_is_decision_source_not_post_state(self):
        row=transition();sample,t=teacher(row);self.assertEqual(sample['state']['score'],5);self.assertEqual(sample['state']['next_fruit_type'],1);self.assertNotIn('visits',sample['state']);self.assertTrue(t['time_limit_reached']);self.assertEqual(t['requested_iterations'],128)
    def test_stale_source_rejected(self):
        row=transition();row['decision_source']['state_id']=1
        with self.assertRaisesRegex(ValueError,'identity'):teacher(row)
    def test_public_next_mismatch_rejected(self):
        row=transition();row['decision_source']['next_fruit_type']=4
        with self.assertRaisesRegex(ValueError,'public fruit'):teacher(row)
    def test_visit_conservation(self):
        row=transition();row['info']['planning']['mcts']['completed_iterations']=33
        with self.assertRaisesRegex(ValueError,'root visits'):teacher(row)
    def test_actual_drop_mismatch_rejected(self):
        row=transition();row['info']['applied_normalized_x']=.75
        with self.assertRaisesRegex(ValueError,'actual drop'):teacher(row)
    def test_corrupt_dataset_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'data';tiny(p);(p/'records.jsonl').write_text('broken')
            with self.assertRaisesRegex(ValueError,'hash'):load(p)
    def test_seed_split_leak_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'data';tiny(p);rows=[json.loads(l) for l in (p/'records.jsonl').read_text().splitlines()];rows[-1]['seed']=0
            (p/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));m=json.loads((p/'manifest.json').read_text());m['files']['records.jsonl']=hashlib.sha256((p/'records.jsonl').read_bytes()).hexdigest();(p/'manifest.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'leakage'):load(p)

class PolicyNetworkTests(unittest.TestCase):
    def test_permutation_and_padding_invariance(self):
        torch.manual_seed(1);m=PolicyNetwork(width=16).eval();f=torch.randn(1,8,30);mask=torch.tensor([[True]*5+[False]*3]);g=torch.randn(1,37);xs=torch.tensor([[0.,.5,1.]]);cm=torch.ones(1,3,dtype=torch.bool);order=[3,1,0,4,2,7,5,6]
        with torch.inference_mode():a=m(f,mask,g,xs,cm);b=m(f[:,order],mask[:,order],g,xs,cm)
        self.assertTrue(torch.allclose(a,b,atol=1e-6));f[:,5:]=1e4
        with torch.inference_mode():self.assertTrue(torch.allclose(a,m(f,mask,g,xs,cm),atol=1e-6))
    def test_empty_many_unknown_next_and_variable_candidates(self):
        m=PolicyNetwork(width=16);f=torch.zeros(2,200,30);mask=torch.zeros(2,200,dtype=torch.bool);mask[1]=True;g=torch.zeros(2,37);xs=torch.linspace(0,1,9)[None].repeat(2,1);cm=torch.ones(2,9,dtype=torch.bool);cm[0,5:]=False
        out=m(f,mask,g,xs,cm);self.assertTrue(torch.isfinite(out).all());self.assertTrue((torch.softmax(out,-1)[0,5:]==0).all())
    def test_candidate_permutation_equivariance(self):
        m=PolicyNetwork(width=8).eval();f=torch.randn(1,2,30);mask=torch.ones(1,2,dtype=torch.bool);g=torch.randn(1,37);xs=torch.tensor([[0.,.5,1.]]);cm=torch.ones(1,3,dtype=torch.bool);order=[2,0,1]
        with torch.inference_mode():self.assertTrue(torch.allclose(m(f,mask,g,xs,cm)[:,order],m(f,mask,g,xs[:,order],cm[:,order]),atol=1e-6))
    def test_save_restart_resume_matches_continuous(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);data=p/'data';b=tiny(data);cfg=dict(width=8,epochs=2,batch_size=4)
            train(b,data,p/'continuous','deepsets',cfg);train(b,data,p/'resumed','deepsets',dict(cfg,epochs=1));train(b,data,p/'resumed','deepsets',cfg,True)
            a,pa,_=load_model(p/'continuous','latest');b,pb,_=load_model(p/'resumed','latest')
            self.assertEqual(pa['updates'],pb['updates']);self.assertTrue(all(torch.equal(v,b.state_dict()[k]) for k,v in a.state_dict().items()))

class LearningEventTests(unittest.TestCase):
    def rows(self):return [dict(state=dict(score=100,fruits=[],episode_events=dict(known=True,source='actual_game',events=[dict(event_id=1,kind='first_watermelon',score=100,drop_count=5,fixed_time=10)])))]
    def test_missing_transient_event_is_unknown(self):
        a=extract(self.rows());self.assertIsNone(a['labels']['watermelon_melon_two']['achieved']);self.assertTrue(a['labels']['watermelon_one']['achieved'])
    def test_known_watermelon_events_can_confirm_failure(self):
        a=extract(self.rows());self.assertTrue(a['labels']['watermelon_two']['known']);self.assertFalse(a['labels']['watermelon_two']['achieved']);self.assertFalse(a['labels']['double_watermelon']['achieved'])
    def test_snapshot_evidence_is_not_exact_reward_time(self):
        rows=self.rows();rows[0]['state']['fruits']=[dict(type=10),dict(type=9),dict(type=9)];a=extract(rows);self.assertTrue(a['labels']['watermelon_melon_two']['achieved']);self.assertFalse(a['labels']['watermelon_melon_two']['exact_timing']);self.assertIn('watermelon_melon_two',rewards(a,dict(watermelon_melon_two=1,double_watermelon=10))['snapshot_only_not_rewarded'])
    def test_reward_once_and_game_score_separate(self):
        a=extract(self.rows()*3);r=rewards(a,dict(watermelon_one=1,double_watermelon=10));self.assertEqual(r['total_learning_reward'],1);self.assertTrue(r['game_score_unchanged'])
    def test_corrupt_event_history_rejected(self):
        rows=self.rows();b=copy.deepcopy(rows[0]);b['state']['episode_events']['events'][0]['score']=200;rows.append(b)
        with self.assertRaisesRegex(ValueError,'Rewritten'):extract(rows)
    def test_unknown_extended_event_rejected(self):
        rows=self.rows();rows[0]['state']['episode_events']['learning']=dict(version='learning-milestones-v1',known=True,events=[dict(kind='corner')])
        with self.assertRaisesRegex(ValueError,'Unknown'):extract(rows)
    def test_double_reward_priority(self):
        with self.assertRaisesRegex(ValueError,'largest'):rewards(extract(self.rows()),dict(watermelon_one=10,double_watermelon=1))
    def extended(self):
        rows=self.rows();rows[0]['state']['fruits']=[dict(type=10)];rows[0]['state']['episode_events']['learning']=dict(version='learning-milestones-v1',known=True,melons_present=0,watermelons_present=1,events=[dict(kind='watermelon_one',score=100,drop_count=5,fixed_time=10,melons_present=0,watermelons_present=1)]);return rows
    def test_extended_absence_is_known(self):
        a=extract(self.extended());self.assertTrue(a['labels']['watermelon_melon_two']['known']);self.assertFalse(a['labels']['watermelon_melon_two']['achieved'])
    def test_duplicate_extended_goal_rejected(self):
        rows=self.extended();v=rows[0]['state']['episode_events']['learning']['events'];v.append(dict(v[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):extract(rows)
    def test_extended_board_count_mismatch_rejected(self):
        rows=self.extended();rows[0]['state']['fruits']=[]
        with self.assertRaisesRegex(ValueError,'board/count'):extract(rows)

if __name__=='__main__':unittest.main()
