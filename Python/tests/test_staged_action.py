import unittest
from pathlib import Path
from staged_action_experiment import choose_alternative

class StagedActionTests(unittest.TestCase):
    def row(self):
        return dict(planning=dict(selected_index=0,selected_x=0),search=dict(root=[dict(index=i,x=i/4,visits=10+i,mean_points=i,drop_success=True,immediate_go=False) for i in range(5)]))
    def test_alternative_is_distinct_highest_mean_eligible(self):
        r=self.row();r['search']['root'][4]['immediate_go']=True;r['search']['root'][2]['mean_points']=99
        s=choose_alternative(r);self.assertEqual(s['recommended_x'],0);self.assertEqual(s['alternative_x'],.5)
    def test_no_safe_alternative_is_not_replaced_using_returns(self):
        r=self.row()
        for e in r['search']['root'][1:]:e['immediate_go']=True
        with self.assertRaises(ValueError):choose_alternative(r)
    def test_fork_changes_only_root_allocation_and_final_selection(self):
        folder=Path(__file__).resolve().parents[2]/'Unity/Assets/Scenes/Script';o=(folder/'MctsPlanner.cs').read_text(encoding='utf-8-sig');f=(folder/'StagedRootMctsPlanner.cs').read_text()
        marker='    // Values are points.';o=o[o.index(marker):];f=f[f.index(marker):]
        changes=[
            ('PlanningSettings settings,bool staged=true)','PlanningSettings settings)'),
            ('        if(staged&&(settings.mcts_iterations!=128||settings.mcts_max_depth!=4||settings.candidate_count!=5||settings.candidate_policy!="grid"||settings.mcts_widening||settings.mcts_budget_mode!="fixed"||settings.tree_policy!="chance"||settings.rollout_policy!="random"))throw new ArgumentException("Staged mode requires fixed128/depth4/grid5/random/chance");\n',''),
            ('        Last=null;var previous=','        var previous='),
            ('PlanFrames(player,manager,floor,settings,null,staged))','PlanFrames(player,manager,floor,settings))'),
            ('SuikaPhysicsSimulator.PathSession frozenRoot=null,bool staged=true)','SuikaPhysicsSimulator.PathSession frozenRoot=null)'),
            ('var allocation=staged?new RootBudgetAllocation():null;',''),
            ('} else action=staged&&depth==0?allocation.Select(root,iteration):Select(node,s.mcts_exploration,s.mcts_point_scale);','} else action=Select(node,s.mcts_exploration,s.mcts_point_scale);'),
            ('            if(staged){int chosen=allocation.Final(root);if(chosen>=0)best=chosen;}\n',''),
            ('        if(staged){Last=allocation.Finish(root,d.selected_index);report.selection_rule="experimental root40 balanced, top3 equal extra88, final max mean; existing all-GO fallback";}\n','')]
        for a,b in changes:self.assertEqual(f.count(a),1,a);f=f.replace(a,b)
        self.assertEqual(o,f)

if __name__=='__main__':unittest.main()
