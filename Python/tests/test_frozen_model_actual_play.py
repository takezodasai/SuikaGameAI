import copy,unittest
from types import SimpleNamespace
import torch
from frozen_model_actual_play import choose,scores

class FrozenModelActualTests(unittest.TestCase):
    def test_safety_filter_does_not_silently_change_q(self):
        c=[dict(drop=True,go=True),dict(drop=True,go=False)]
        self.assertEqual(choose([100,1],c,False),0)
        self.assertEqual(choose([100,1],c,True),1)

    def test_v_marginalizes_unknown_next_and_zeroes_terminal(self):
        class Q(torch.nn.Module):
            def forward(self,f,m,g,geo,x):return x
        class V(torch.nn.Module):
            def forward(self,f,m,g,geo):return (g[:,11:22]*torch.arange(11)).sum(1)/1000
        state=dict(fruits=[],current_fruit=dict(type=1,present=True,x=.5,y=3),next_fruit_type=4,score=0,game_over=False,fixed_delta_time=.02,ai_move_speed=4,geometry=[0,1,0,4],drop_cooldown_remaining=0)
        c=dict(after=state,reward=7,drop=True,go=False,heuristic=0)
        request=dict(state=state,candidates=[copy.deepcopy(c) for _ in range(5)],public_spawn_types=list(range(5)),id=1,physics_ms=1)
        request['candidates'][0]['after']['game_over']=True;request['candidates'][0]['go']=True
        models=SimpleNamespace(q=[Q()],v=[V()]);a=scores(models,request)
        self.assertEqual(a['V'][0],7)
        self.assertAlmostEqual(a['V'][1],9,places=6)
        request['candidates'][1]['after']['next_fruit_type']=0
        b=scores(models,request);self.assertAlmostEqual(a['V'][1],b['V'][1])
        self.assertEqual(a['choices']['B'],1)

if __name__=='__main__':unittest.main()
