import unittest
import torch
from qv_experiment import ActionValue
from qv_branch_assessment import inputs

class QValueTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1);torch.manual_seed(2);self.model=ActionValue().eval()
        self.f=torch.randn(2,3,30);self.m=torch.ones(2,3,dtype=torch.bool);self.g=torch.zeros(2,37);self.geo=torch.zeros(2,57);self.x=torch.tensor([0.,.37])
    def test_permutation_invariant(self):
        with torch.inference_mode():
            a=self.model(self.f,self.m,self.g,self.geo,self.x);b=self.model(self.f[:,[2,0,1]],self.m,self.g,self.geo,self.x)
        self.assertTrue(torch.allclose(a,b,atol=1e-7))
    def test_known_terminal_zero(self):
        self.g[:,35]=1
        with torch.inference_mode():a=self.model(self.f,self.m,self.g,self.geo,self.x)
        self.assertEqual(a.tolist(),[0.,0.])
    def test_empty_board_and_continuous_coordinate(self):
        self.m[:]=False
        with torch.inference_mode():a=self.model(self.f,self.m,self.g,self.geo,self.x)
        self.assertTrue(torch.isfinite(a).all());self.assertTrue((a>=0).all())
        self.assertLess(sum(p.numel() for p in self.model.parameters()),45000)
    def test_inference_cannot_take_label_or_future_seed(self):
        s=dict(fruits=[],current_fruit=dict(type=1,present=True,x=.5,y=3),next_fruit_type=2,score=5,game_over=False,fixed_delta_time=.02,ai_move_speed=4,geometry=[0,1,0,4],drop_cooldown_remaining=0)
        a=inputs(s,True);b=inputs(dict(s,final_score=9999,future_seed=3),True)
        self.assertTrue(all(torch.equal(x,y) for x,y in zip(a,b)))
        self.assertEqual(a[2][0,26],0) # Held y is unknown in training capsules.
        self.assertEqual(a[2][0,29],0) # Cooldown is unknown in training capsules.

if __name__=='__main__':unittest.main()
