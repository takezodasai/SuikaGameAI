import unittest
import json
import tempfile
from pathlib import Path
from compare_watermelon_dynamic import sequence
from analyze_watermelon_dynamic import analyze

class DynamicWatermelonTests(unittest.TestCase):
    def test_exactly_nine_pairs_and_eighteen_games(self):
        jobs=sequence(dict(future_seeds=[1,2,3]));self.assertEqual(len(jobs),9);self.assertEqual(len({(x['root'],x['future']) for x in jobs}),9)
        self.assertEqual(sum(len(x['modes']) for x in jobs),18)
        for j in jobs:self.assertEqual(set(j['modes']),{'baseline','refined'})

    def test_condition_order_alternates_and_roots_rotate(self):
        jobs=sequence(dict(future_seeds=[1,2,3]));self.assertEqual([x['root'] for x in jobs],[0,1,2,1,2,0,2,0,1])
        self.assertEqual([x['modes'][0] for x in jobs],['baseline','refined']*4+['baseline'])

    def test_schedule_does_not_use_results(self):
        a=sequence(dict(future_seeds=[1,2,3]));b=sequence(dict(future_seeds=[1,2,3]));self.assertEqual(a,b)

    def test_unstarted_and_unfinished_are_not_natural_games(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'plan.json').write_text(json.dumps(dict(future_seeds=[1,2,3],protected={})))
            (root/'root0_f1/baseline').mkdir(parents=True)
            r=analyze(root)
            self.assertEqual(len(r['unstarted']),17);self.assertEqual(len(r['unfinished']),1)
            self.assertEqual(r['paired']['n'],0);self.assertEqual(r['summary']['baseline']['natural_games'],0)

    def test_fork_core_only_has_declared_opt_in_candidate_changes(self):
        folder=Path(__file__).resolve().parents[2]/'Unity/Assets/Scenes/Script'
        original=(folder/'MctsPlanner.cs').read_text(encoding='utf-8-sig');fork=(folder/'RootRefinedMctsPlanner.cs').read_text()
        marker='    // Values are points.';a=original[original.index(marker):];b=fork[fork.index(marker):]
        changes=[
            ('PlanningSettings settings,bool refine=true)','PlanningSettings settings)'),
            ('        if(refine&&(settings.mcts_iterations!=128||settings.mcts_max_depth!=4||settings.candidate_count!=5||settings.mcts_widening||settings.mcts_budget_mode!="fixed"||settings.tree_policy!="chance"||settings.rollout_policy!="random"))throw new ArgumentException("Isolated root refinement requires fixed128/depth4/grid5/random/chance");\n',''),
            ('PlanFrames(player,manager,floor,settings,null,refine))','PlanFrames(player,manager,floor,settings))'),
            ('SuikaPhysicsSimulator.PathSession frozenRoot=null,bool refine=true)','SuikaPhysicsSimulator.PathSession frozenRoot=null)'),
            ('if(refine)root.positions=MctsAdaptiveControl.InitialPositions(5);',''),
            ('            if(refine&&iteration==32){additions.AddRange(RootCandidateRefinement.Add(root,s,iteration));Array.Resize(ref d.candidates,root.actions.Length);}\n',''),
            ('var actionXs=!refine&&s.candidate_policy=="grid"','var actionXs=s.candidate_policy=="grid"'),
            ('int actionCount=refine&&!rollout&&depth==0?root.actions.Length:s.mcts_widening','int actionCount=s.mcts_widening'),
            ('DropCandidateGenerator.Set positions=refine&&!rollout&&depth==0?root.positions:s.mcts_widening','DropCandidateGenerator.Set positions=s.mcts_widening')]
        for old,new in changes:
            self.assertEqual(b.count(old),1,old);b=b.replace(old,new)
        self.assertEqual(a,b,'UCT, expansion, chance, rollout, backup and selection must be copied unchanged')

if __name__=='__main__':unittest.main()
