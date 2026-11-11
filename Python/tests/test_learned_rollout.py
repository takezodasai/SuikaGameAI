import copy,json,unittest
import numpy as np
from learned_rollout import features,probabilities,VERSION

class LearnedRolloutTests(unittest.TestCase):
    def sample(self):return dict(geometry=[-3,3,-4,3],state=dict(fruits=[dict(type=2,x=0.,y=-1.,vx=0.,vy=0.)],current_fruit=dict(type=2,present=True),next_fruit_type=3,score=0,game_over=False))
    def test_shape_public_only(self):
        s=self.sample();original=copy.deepcopy(s);a=features(s);self.assertEqual(a.shape,(5,213));self.assertEqual(s,original)
        s.update(final_score=9999,future_seed=5);s['state']['unpublished_sequence']=[10]*40;np.testing.assert_array_equal(features(s),a)
    def test_normalized_uniform(self):
        p=probabilities(dict(version=VERSION,weights=[0.]*213),self.sample());np.testing.assert_allclose(p,[.2]*5)
    def test_candidate_specific(self):
        w=np.zeros(213);w[2*40]=2;p=probabilities(dict(version=VERSION,weights=w),self.sample());self.assertEqual(int(p.argmax()),2)
    def test_invalid_geometry(self):
        s=self.sample();s['geometry'][1]=-3
        with self.assertRaises(ValueError):features(s)
    def test_public_next_changes_input(self):
        s=self.sample();a=features(s);s['state']['next_fruit_type']=-1;self.assertFalse(np.array_equal(a,features(s)))
    def test_original_mcts_untouched_clone_dispatch(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[2];s=(root/'Unity/Assets/Scenes/Script/LearnedRolloutPlanner.cs').read_text();self.assertIn('LearnedRolloutPolicy.Choose(path,rng,actionCount,depth)',s)
        self.assertIn('bool irrelevantChance=network==null && depth+2==s.mcts_max_depth && !(LearnedRolloutPolicy.Active!=null&&LearnedRolloutPolicy.Mixture>0)',s)
        original=(root/'Unity/Assets/Scenes/Script/MctsPlanner.cs').read_text();self.assertNotIn('LearnedRolloutPolicy',original)

if __name__=='__main__':unittest.main()
