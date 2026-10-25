using System;
using System.Collections.Generic;
using UnityEngine;

// Opt-in resource/candidate allocation only. No physics, live RNG, or reward mutation.
public static class MctsAdaptiveControl {
    [Serializable] public class Checkpoint {
        public int iterations,winner,previous_winner;public float selected_x;
        public double mean,gap,standard_error,mean_drift,terminal_rate;public bool stable;public string reason;
        public int[] root_visits;public double[] root_means;
    }
    [Serializable] public class Addition {public int iteration,node_id,depth,index,node_visits;public float x,left,right;public string reason;}
    public static void Validate(PlanningSettings s) {
        if(s.mcts_auto_depth&&!s.mcts_extended_budget)throw new ArgumentException("Auto depth requires extended budget");
        if(s.auto_depth_min<2||s.auto_depth_max>8||s.auto_depth_min>s.auto_depth_max)throw new ArgumentException("Auto depth initial range must be 2..8");
        if(s.mcts_extended_budget&&(s.ai_mode!="mcts"||s.execution_mode!="sync"||s.candidate_policy!="grid"||s.tree_policy!="chance"||s.rollout_policy!="random"||s.expansion_policy!="legacy"||s.action_order_policy!="index"||s.pair_coverage_iterations!=0||s.mcts_common_chance||s.planning_budget_ms!=0||s.frame_tick_slicing||s.adaptive_initial_iterations!=32))throw new ArgumentException("Extended budget requires sync legacy MCTS and initial checkpoint 32");
        if(s.mcts_budget_mode!="fixed"&&s.mcts_budget_mode!="time"&&s.mcts_budget_mode!="adaptive")throw new ArgumentException("Invalid MCTS budget mode");
        if(float.IsNaN(s.mcts_time_limit_seconds)||float.IsInfinity(s.mcts_time_limit_seconds)||s.mcts_time_limit_seconds<.000001f||s.mcts_time_limit_seconds>(s.mcts_extended_budget?120:3600)||s.mcts_max_iterations<(s.mcts_extended_budget?32:2)||s.mcts_max_iterations>(s.mcts_extended_budget?32768:4096)||s.adaptive_initial_iterations<2||s.adaptive_initial_iterations>4096||s.adaptive_min_action_visits<1||s.adaptive_min_action_visits>4096)throw new ArgumentException("Invalid adaptive search bounds");
        foreach(float v in new[]{s.adaptive_uncertainty_multiplier,s.adaptive_value_tolerance,s.adaptive_max_terminal_rate,s.widening_min_spacing})if(float.IsNaN(v)||float.IsInfinity(v)||v<0)throw new ArgumentException("Invalid adaptive threshold");
        if(s.adaptive_max_terminal_rate>1||s.widening_max_candidates<5||s.widening_max_candidates>31||s.widening_after_visits<1||s.widening_after_visits>4096||s.widening_min_action_visits<1||s.widening_min_action_visits>4096||s.widening_min_spacing<=0||s.widening_min_spacing>.125f)throw new ArgumentException("Invalid widening bounds");
        if(s.mcts_budget_mode!="fixed"||s.mcts_widening) {
            if(s.ai_mode!="mcts"||s.execution_mode!="sync"||s.frame_tick_slicing||s.candidate_policy!="grid"||s.tree_policy!="chance"||s.rollout_policy!="random"||s.expansion_policy!="legacy"||s.action_order_policy!="index"||s.pair_coverage_iterations!=0||s.mcts_common_chance||s.planning_budget_ms!=0)throw new ArgumentException("Adaptive prototype requires sync legacy chance/grid/random MCTS; no other allocation policies");
        }
        if(s.mcts_budget_mode!="fixed"&&(s.mcts_max_iterations<s.candidate_count||s.adaptive_initial_iterations>s.mcts_max_iterations||s.adaptive_initial_iterations<s.candidate_count))throw new ArgumentException("Invalid adaptive stage/cap");
        if(s.mcts_widening&&(s.candidate_count!=5||s.widening_max_candidates<5))throw new ArgumentException("Widening starts with five anchors");
    }
    public static DropCandidateGenerator.Set InitialPositions(int count) {
        var p=new DropCandidateGenerator.Set {x=new float[count],sources=new string[count]};for(int i=0;i<count;i++){p.x[i]=(float)i/(count-1);p.sources[i]="initial-grid";}return p;
    }
    public static Addition TryWiden(MctsPlanner.Node n,PlanningSettings s,int iteration) {
        if(!s.mcts_widening||n.actions.Length>=s.widening_max_candidates||n.visits<s.widening_after_visits*(n.added_candidates+1)*(n.added_candidates+1))return null;
        foreach(var e in n.actions)if((e.immediate==null||(!e.immediate.predicted_game_over&&e.immediate.drop_success))&&e.visits<s.widening_min_action_visits)return null;
        var order=new List<int>();for(int i=0;i<n.actions.Length;i++)order.Add(i);order.Sort((a,b)=>n.positions.x[a].CompareTo(n.positions.x[b]));
        bool coverage=n.added_candidates%2==1;double best=double.NegativeInfinity;var ties=new List<int>();
        for(int j=0;j<order.Count-1;j++) {
            int l=order[j],r=order[j+1];float width=n.positions.x[r]-n.positions.x[l];if(width*.5f<s.widening_min_spacing)continue;
            // Alternate promising intervals and the widest under-resolved interval.
            double merit=width*(coverage?1:1+Math.Min(1,Math.Max(0,Math.Max(n.actions[l].Mean,n.actions[r].Mean))/s.mcts_point_scale));
            if(merit>best+1e-12){best=merit;ties.Clear();ties.Add(j);}else if(Math.Abs(merit-best)<=1e-12)ties.Add(j);
        }
        if(ties.Count==0)return null;
        int tie=(int)((uint)(s.mcts_seed^n.id*9176^n.added_candidates*31)%(uint)ties.Count),slot=ties[tie];float left=n.positions.x[order[slot]],right=n.positions.x[order[slot+1]],x=(left+right)*.5f;
        foreach(float old in n.positions.x)if(Mathf.Abs(old-x)<s.widening_min_spacing*.999f)return null;
        int index=n.actions.Length;Array.Resize(ref n.actions,index+1);n.actions[index]=new MctsPlanner.Edge();Array.Resize(ref n.positions.x,index+1);Array.Resize(ref n.positions.sources,index+1);n.positions.x[index]=x;n.positions.sources[index]=coverage?"widen-coverage":"widen-promising";n.added_candidates++;
        return new Addition {iteration=iteration,node_id=n.id,depth=n.depth,index=index,node_visits=n.visits,x=x,left=left,right=right,reason=n.positions.sources[index]};
    }
    public static Checkpoint Assess(MctsPlanner.Node root,PlanningSettings s,int iterations,int previousWinner,double previousMean) {
        var c=new Checkpoint {iterations=iterations,winner=-1,previous_winner=previousWinner,reason="no_safe_candidate",root_visits=new int[root.actions.Length],root_means=new double[root.actions.Length]};
        var safe=new List<int>();for(int i=0;i<root.actions.Length;i++) {
            var e=root.actions[i];c.root_visits[i]=e.visits;c.root_means[i]=e.Mean;
            if(e.visits>0&&e.immediate!=null&&e.immediate.drop_success&&!e.immediate.predicted_game_over)safe.Add(i);
        }
        foreach(int i in safe)if(c.winner<0||root.actions[i].visits>root.actions[c.winner].visits||(root.actions[i].visits==root.actions[c.winner].visits&&root.actions[i].Mean>root.actions[c.winner].Mean+.001))c.winner=i;
        if(c.winner<0)return c;
        var winner=root.actions[c.winner];c.selected_x=root.positions==null?(float)c.winner/(root.actions.Length-1):root.positions.x[c.winner];c.mean=winner.Mean;c.mean_drift=Math.Abs(c.mean-previousMean);c.terminal_rate=(double)winner.terminal_returns/winner.visits;
        int competitor=-1;foreach(int i in safe)if(i!=c.winner&&(competitor<0||root.actions[i].Mean>root.actions[competitor].Mean))competitor=i;
        if(competitor>=0){var other=root.actions[competitor];c.gap=c.mean-other.Mean;c.standard_error=Math.Sqrt(Math.Max(0,winner.sumSquares/winner.visits-c.mean*c.mean)/winner.visits+Math.Max(0,other.sumSquares/other.visits-other.Mean*other.Mean)/other.visits);}
        c.reason="stable";
        foreach(int i in safe)if(root.actions[i].visits<s.adaptive_min_action_visits)c.reason="insufficient_action_visits";
        if(previousWinner<0)c.reason="first_checkpoint";
        else if(previousWinner!=c.winner)c.reason="winner_changed";
        else if(c.mean_drift>s.adaptive_value_tolerance)c.reason="value_drift";
        else if(c.terminal_rate>s.adaptive_max_terminal_rate)c.reason="terminal_samples";
        else if(c.gap<s.adaptive_uncertainty_multiplier*c.standard_error)c.reason="overlapping_sample_values";
        c.stable=c.reason=="stable";return c;
    }
}
