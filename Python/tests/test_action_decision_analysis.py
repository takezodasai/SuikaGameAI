import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import torch
import action_decision_analysis as analysis
from compare_candidate_value import expected_q

class DecisionValidationTests(unittest.TestCase):
    def test_censored_bound_does_not_become_exact_return(self):
        a=dict(lower=100,upper=None);b=dict(lower=80,upper=80)
        lo,hi=analysis.difference_interval(a,b)
        self.assertIsNone(lo);self.assertEqual(hi,-20);self.assertEqual(analysis.certified_winner(lo,hi),0.)
    def test_two_censored_returns_have_no_known_order(self):
        lo,hi=analysis.difference_interval(dict(lower=300,upper=None),dict(lower=100,upper=None))
        self.assertIsNone(analysis.certified_winner(lo,hi))
    def test_unknown_next_is_marginalized_not_used_as_actual_future(self):
        class Toy(torch.nn.Module):
            def forward(self,f,m,g,geo):return (g[:,11:22]*torch.arange(11)).sum(1)/1000
        s=dict(fruits=[],current_fruit=dict(type=1,present=True,x=.5,y=3),next_fruit_type=0,score=0,game_over=False,geometry=[0,1,0,4])
        r=dict(after_first=s,first=dict(reward=0,drop_success=True),public_spawn_types=list(range(5)))
        a=expected_q(Toy(),'geometry',r)[0];r=copy.deepcopy(r);r['after_first']['next_fruit_type']=4
        self.assertAlmostEqual(a,2,places=6);self.assertAlmostEqual(a,expected_q(Toy(),'geometry',r)[0])
    def test_certified_regret_is_only_a_lower_bound_and_full_choice_unobserved(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);folder=base/'branches/r';folder.mkdir(parents=True)
            root=dict(tick=1,score=0,drops=24,state=dict(current_fruit=dict(type=1),next_fruit_type=2),bodies={},rng='r')
            pred=dict(root_signature=analysis.signature(root),selected_observed_pair={m:.37 for m in 'ABCD'},selected_full={m:1. for m in 'ABCD'},seed_choices={},q_scan=dict(maximum_interval_overshoot_points=0),timing={},rows=[])
            p=folder/'predictions.json';p.write_text(json.dumps(pred))
            for x,value,natural in [(0.,100,False),(.37,80,True)]:
                f=folder/f'f1_x{x}';f.mkdir();end=dict(score=value,game_over=natural,mc_return_known=natural,prefix_verified=True,reason='natural_go' if natural else 'wall_limit',drops=25)
                r=dict(end=end,root=root,exit_code=0,errors=[],first_mismatch=None,wall_seconds=10)
                (f/'result.json').write_text(json.dumps(r));(f/'config.json').write_text(json.dumps(dict(candidate_x=x,future_seed=1)))
                rows=[dict(evt='start',score=0),dict(evt='action',score=value,drops=25,state=dict(current_fruit=dict(type=2),next_fruit_type=3),commands=[dict(x=x)]),dict(evt='end',score=value)]
                (f/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with patch.object(analysis,'ROOT',base):r=analysis.analyze_root(dict(name='r',role='development',seed=1,predictions=str(p)))
            self.assertFalse(r['fully_natural']);self.assertEqual(r['methods']['D']['regret_lower_bound'],20)
            self.assertIsNone(r['methods']['D']['exact_regret']);self.assertFalse(r['methods']['D']['full_choice_observed'])
            self.assertIsNone(r['observations'][0]['mc_target'])

if __name__=='__main__':unittest.main()
