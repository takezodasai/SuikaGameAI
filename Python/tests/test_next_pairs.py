import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_next_pairs import validate_pairs,best_pair

class NextPairTests(unittest.TestCase):
    def fixture(self):
        def candidate():return dict(reward=0,physics_steps=25,merges=0,predicted_game_over=False,drop_success=True)
        pairs=[dict(first_index=i,second_index=j,first=candidate(),second=candidate(),prefix_match=True,total_reward=0,merges=0,ticks=50,game_over=False,final_evaluation=dict(value=0.,roughness=0.)) for i in range(5) for j in range(5)]
        return dict(source_unchanged=True,root_unchanged=True,random_unchanged=True,unknown_next_invariant=True,one=[candidate() for i in range(5)],pairs=pairs,pair_ticks=1250,one_ticks=125)
    def test_complete_grid(self):self.assertTrue(validate_pairs(self.fixture()))
    def test_missing_or_duplicate_pair(self):
        for mode in ['missing','duplicate']:
            r=self.fixture()
            if mode=='missing':r['pairs'].pop()
            else:r['pairs'][-1]=copy.deepcopy(r['pairs'][0])
            with self.assertRaisesRegex(ValueError,'25-path'):validate_pairs(r)
    def test_reward_tick_or_merge_double_count_rejected(self):
        for key in ['total_reward','ticks','merges']:
            r=self.fixture();r['pairs'][0][key]+=1
            with self.assertRaisesRegex(ValueError,'conservation'):validate_pairs(r)
    def test_second_drop_after_go_rejected(self):
        r=self.fixture();r['one'][0]['predicted_game_over']=True
        for p in r['pairs'][:5]:p['first']['predicted_game_over']=True
        with self.assertRaisesRegex(ValueError,'after GO'):validate_pairs(r)
    def test_hidden_or_source_mutation_rejected(self):
        for key in ['source_unchanged','random_unchanged','unknown_next_invariant','root_unchanged']:
            r=self.fixture();r[key]=False
            with self.assertRaisesRegex(ValueError,'invariance'):validate_pairs(r)
    def test_first_replay_mismatch_rejected(self):
        r=self.fixture();r['pairs'][0]['first']['predicted_game_over']=True;r['pairs'][0]['second']['drop_success']=False;r['pairs'][0]['second']['physics_steps']=0;r['pairs'][0]['ticks']=25
        with self.assertRaisesRegex(ValueError,'first move'):validate_pairs(r)
    def test_safe_path_beats_high_terminal_reward(self):
        ps=self.fixture()['pairs'];ps[0]['game_over']=True;ps[0]['final_evaluation']['value']=100;ps[1]['final_evaluation']['value']=1
        self.assertEqual(best_pair(ps)['second_index'],1)
    def test_no_safe_path_not_fabricated(self):
        ps=self.fixture()['pairs']
        for p in ps:p['game_over']=True
        self.assertIsNone(best_pair(ps))
