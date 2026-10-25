using System;
// Diagnostics/next-decision policy only. Never changes an in-flight tree's horizon.
public static class MctsDepthControl {
    [Serializable] public class Level {public int depth,nodes;public long action_visits,revisits,tree_actions,rollout_actions;}
    [Serializable] public class Choice {public string reason;public int requested_depth,chosen_depth,previous_depth;public double prior_tree_fraction;public long prior_revisits;public bool experimental_depth;}
    public sealed class History {public string episode,configuration;public int depth,iterations;public bool stable;public Level[] levels;}
    static string Key(PlanningSettings s){return s.candidate_count+":"+s.mcts_widening+":"+s.mcts_seed+":"+s.post_drop_steps+":"+s.auto_depth_min+":"+s.auto_depth_max+":"+s.mcts_max_depth;}
    public static PlanningSettings Resolve(PlanningSettings requested,History previous,string episode,out Choice choice){
        var s=requested.Freeze();choice=null;if(!s.mcts_extended_budget)return s;
        choice=new Choice {requested_depth=s.mcts_max_depth,chosen_depth=s.mcts_max_depth,reason="manual_before_search",experimental_depth=s.mcts_max_depth>=16};
        if(!s.mcts_auto_depth)return s;
        int depth=Math.Max(s.auto_depth_min,Math.Min(s.auto_depth_max,s.mcts_max_depth));choice.reason="initial_depth_no_history";
        if(previous!=null&&previous.episode==episode&&previous.configuration==Key(s)){
            depth=previous.depth;var tail=previous.levels[depth-1];double count=tail.tree_actions+tail.rollout_actions;
            choice.previous_depth=depth;choice.prior_tree_fraction=count==0?0:tail.tree_actions/count;choice.prior_revisits=tail.revisits;choice.reason="hold_insufficient_evidence";
            // Initial research thresholds, not calibrated strength guarantees. No iteration/depth ratio.
            if(previous.iterations>=128&&choice.prior_tree_fraction<.05&&tail.revisits<8){depth=Math.Max(s.auto_depth_min,depth-1);choice.reason="rollout_dominated_reduce_next_horizon";}
            else if(previous.stable&&choice.prior_tree_fraction>=.25&&tail.revisits>=8){depth=Math.Min(s.auto_depth_max,depth+1);choice.reason="stable_revisited_frontier_try_next_horizon";}
        }
        s.mcts_max_depth=depth;choice.chosen_depth=depth;choice.experimental_depth=depth>=16;return s;
    }
    public static Level[] Levels(MctsPlanner.Report report){var a=new Level[report.max_depth];for(int d=0;d<a.Length;d++)a[d]=new Level {depth=d+1};
        foreach(var n in report.nodes){if(n.depth>=a.Length)continue;var l=a[n.depth];l.nodes++;foreach(var e in n.actions){l.action_visits+=e.visits;l.revisits+=Math.Max(0,e.visits-1);}}
        foreach(var it in report.iterations)for(int d=0;d<it.rollout_steps.Length;d++){if(it.rollout_steps[d])a[d].rollout_actions++;else a[d].tree_actions++;}return a;
    }
    public static History Capture(StepPlanner.Decision d,PlanningSettings requested,string episode){if(d==null||d.mcts==null||!requested.mcts_extended_budget)return null;var m=d.mcts;bool stable=m.budget_checkpoints!=null&&m.budget_checkpoints.Length>0&&m.budget_checkpoints[m.budget_checkpoints.Length-1].stable;
        return new History {episode=episode,configuration=Key(requested),depth=m.max_depth,iterations=m.completed_iterations,stable=stable,levels=m.depth_metrics??Levels(m)};
    }

    public static void SelfTests(){
        var s=new PlanningSettings {ai_mode="mcts",mcts_extended_budget=true,mcts_auto_depth=true,mcts_max_depth=4};Choice c;
        var initial=Resolve(s,null,"episode",out c);if(initial.mcts_max_depth!=4)throw new Exception("Initial depth changed");
        var levels=new Level[4];for(int d=0;d<4;d++)levels[d]=new Level {depth=d+1};levels[3].rollout_actions=128;
        var h=new History {episode="episode",configuration=Key(s),depth=4,iterations=128,levels=levels};
        if(Resolve(s,h,"episode",out c).mcts_max_depth!=3)throw new Exception("Rollout frontier not reduced");
        h.stable=true;levels[3].tree_actions=128;levels[3].revisits=8;
        if(Resolve(s,h,"episode",out c).mcts_max_depth!=5)throw new Exception("Visited stable frontier not extended");
        if(Resolve(s,h,"reset_episode",out c).mcts_max_depth!=4)throw new Exception("Reset mixed prior episode");
        s.mcts_auto_depth=false;s.mcts_max_depth=256;s.mcts_iterations=32768;s.mcts_max_iterations=32768;s.mcts_time_limit_seconds=120;
        if(Resolve(s,h,"episode",out c).mcts_max_depth!=256||!c.experimental_depth)throw new Exception("Manual experimental depth not preserved");
        s.mcts_time_limit_seconds=121;bool rejected=false;try{s.Validate();}catch(ArgumentException){rejected=true;}if(!rejected)throw new Exception("120 second cap not enforced");
        UnityEngine.Debug.Log("EXTENDED BUDGET AND PRE-SEARCH DEPTH SELFTESTS OK");
    }
}
