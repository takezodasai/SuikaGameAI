using System;
using System.Collections.Generic;
using UnityEngine;

// Opt-in stopping/resource policy. Never changes UCT, returns, RNG or physics.
public static class MctsImportanceControl
{
    [Serializable] public class Context {
        public int score,board_fruits,near_line_contacted,actual_drop_count=-1;public string source="actual_live_root";
        public bool actual_drop_count_known;
        public string risk_limit="Geometry/GO samples are indicators; solver/model bias is not sampling uncertainty.";
    }
    [Serializable] public class Audit {
        public MctsAdaptiveControl.Checkpoint root;
        public int stage,consistent_stages,required_stages,root_candidates,root_pending,nonroot_pending;
        public int immediate_go_candidates,safe_candidates,best_changes,nonroot_revisits;
        public long tree_actions,rollout_actions;
        public bool coverage,clear_leader,practical_tie,important,needs_refinement,continue_search,equivalent_winner_change;
        public double elapsed_ms,remaining_ms,next_stage_estimate_ms,uncertainty_width,mean_range,terminal_rate_range,immediate_reward_range;
        public string reason;
    }
    public static Context Capture(PlayerController player,GameManager manager,int score,SuikaPhysicsSimulator.PathSession frozen=null) {
        var c=new Context {score=score};
        var events=ScoreManager.Instance.EpisodeEvents.Read();
        c.actual_drop_count_known=events.known;if(events.known)c.actual_drop_count=events.drop_count;
        if(frozen!=null) {
            var state=frozen.Snapshot();c.score=state.score;c.source="frozen_prediction_root";c.actual_drop_count_known=false;c.actual_drop_count=-1;
            foreach(var fruit in state.fruits){c.board_fruits++;float band=Mathf.Max(.1f,2*fruit.half_height);if(fruit.has_collided&&fruit.y>=state.geometry[3]-band)c.near_line_contacted++;}
            return c;
        }
        foreach(var fruit in UnityEngine.Object.FindObjectsOfType<FruitEvolution>()) {
            if(fruit.Simulation!=null||fruit.IsPreview||fruit.IsMerging||fruit.gameObject==player.currentFruit||fruit.gameObject==player.nextFruitObject)continue;
            c.board_fruits++;
            var shape=FruitColliderShape.Get(fruit.gameObject);
            float band=shape==null ? .1f :Mathf.Max(.1f,2*shape.bounds.extents.y);
            if(fruit.HasCollided&&fruit.transform.position.y>=manager.GameOverHeight-band)c.near_line_contacted++;
        }
        return c;
    }
    static double Variance(MctsPlanner.Edge e) {
        return e.visits<2?0:Math.Max(0,(e.sumSquares-e.sum*e.sum/e.visits)/(e.visits-1));
    }
    // No IID confidence claim: 2 x estimated SE is a diagnostic stopping margin.
    public static Audit Assess(MctsPlanner.Node root,PlanningSettings s,int iterations,
        List<Audit> previous,List<MctsAdaptiveControl.Addition> additions,List<MctsPlanner.Node> nodes,
        Context context,double elapsedMs,double remainingMs,double maxIterationMs) {
        Audit prior=previous.Count==0?null:previous[previous.Count-1];
        var raw=MctsAdaptiveControl.Assess(root,s,iterations,prior==null?-1:prior.root.winner,prior==null?0:prior.root.mean);
        var a=new Audit {root=raw,stage=previous.Count+1,root_candidates=root.actions.Length,coverage=true,elapsed_ms=elapsedMs,remaining_ms=remainingMs};
        double lo=double.PositiveInfinity,hi=double.NegativeInfinity,tlo=1,thi=0,rlo=double.PositiveInfinity,rhi=double.NegativeInfinity,maxPairSe=0;
        var safe=new List<MctsPlanner.Edge>();
        foreach(var e in root.actions) {
            if(e.immediate!=null&&(!e.immediate.drop_success||e.immediate.predicted_game_over)){a.immediate_go_candidates+=e.immediate.predicted_game_over?1:0;continue;}
            if(e.immediate==null||e.visits<s.adaptive_min_action_visits)a.coverage=false;
            if(e.immediate==null||e.visits==0)continue;
            safe.Add(e);lo=Math.Min(lo,e.Mean);hi=Math.Max(hi,e.Mean);
            double t=(double)e.terminal_returns/e.visits;tlo=Math.Min(tlo,t);thi=Math.Max(thi,t);
            rlo=Math.Min(rlo,e.immediate.reward);rhi=Math.Max(rhi,e.immediate.reward);
        }
        a.safe_candidates=safe.Count;
        foreach(var e in safe)foreach(var f in safe)maxPairSe=Math.Max(maxPairSe,Math.Sqrt(Variance(e)/e.visits+Variance(f)/f.visits));
        a.mean_range=safe.Count==0?0:hi-lo;a.terminal_rate_range=safe.Count==0?0:thi-tlo;
        a.immediate_reward_range=safe.Count==0?0:rhi-rlo;
        a.uncertainty_width=2*maxPairSe;
        a.practical_tie=safe.Count>0&&a.mean_range+a.uncertainty_width<=s.adaptive_value_tolerance;
        // A selected max-visits action must also beat all competitors in mean.
        a.clear_leader=safe.Count==1||(safe.Count>1&&raw.gap>Math.Max(s.adaptive_value_tolerance,a.uncertainty_width));
        a.important=context.near_line_contacted>0||a.immediate_go_candidates>0||a.terminal_rate_range>s.adaptive_max_terminal_rate||raw.terminal_rate>s.adaptive_max_terminal_rate||a.immediate_reward_range>=s.mcts_point_scale;
        a.required_stages=a.important?4:3; // 256 vs 128 earliest; research thresholds, not tuned optima.
        a.best_changes=(prior==null?0:prior.best_changes)+(prior!=null&&raw.winner!=prior.root.winner?1:0);
        bool rootChanged=prior!=null&&prior.root_candidates!=root.actions.Length;
        a.equivalent_winner_change=prior!=null&&raw.winner!=prior.root.winner&&a.practical_tie&&prior.practical_tie;
        bool consistent=prior!=null&&!rootChanged&&(raw.winner==prior.root.winner||a.equivalent_winner_change)&&raw.mean_drift<=s.adaptive_value_tolerance;
        a.consistent_stages=consistent?prior.consistent_stages+1:0;
        foreach(var added in additions) {
            var e=nodes[added.node_id].actions[added.index];
            bool pending=(e.immediate==null||(!e.immediate.predicted_game_over&&e.immediate.drop_success))&&e.visits<s.adaptive_min_action_visits;
            if(pending){if(added.depth==0)a.root_pending++;else a.nonroot_pending++;}
        }
        foreach(var n in nodes)if(n.depth>0)foreach(var e in n.actions)a.nonroot_revisits+=Math.Max(0,e.visits-1);
        raw.stable=a.coverage&&a.root_pending==0&&a.stage>=a.required_stages&&a.consistent_stages>=2&&(a.clear_leader||a.practical_tie||(a.safe_candidates==0&&a.immediate_go_candidates==root.actions.Length));
        a.needs_refinement=!a.practical_tie&&(!a.clear_leader||!consistent||a.terminal_rate_range>s.adaptive_max_terminal_rate);
        a.reason=raw.stable&&a.safe_candidates==0?"all_candidates_predicted_terminal":raw.winner<0?"no_safe_candidate":!a.coverage?"insufficient_root_visits":a.root_pending>0?"root_added_actions_under_sampled":a.stage<a.required_stages?"need_multiple_checkpoints":a.consistent_stages<2?"winner_or_value_not_stable":raw.stable?(a.practical_tie?"stable_practical_tie":"stable_separated_leader"):"uncertain_candidate_order";
        int next=Math.Min(s.mcts_max_iterations,iterations*2);int needed=next-iterations;
        double stageCost=prior==null?elapsedMs/Math.Max(1,iterations):(elapsedMs-prior.elapsed_ms)/Math.Max(1,iterations-prior.root.iterations);
        // Recent stage mean + 50% reserve + one worst observed iteration. A soft
        // forecast, not a guarantee; the existing per-iteration deadline still wins.
        a.next_stage_estimate_ms=needed*Math.Max(.01,stageCost)*1.5+maxIterationMs;
        a.continue_search=!raw.stable;
        if(a.continue_search&&needed>0&&remainingMs<a.next_stage_estimate_ms){a.continue_search=false;a.reason="insufficient_budget_for_next_stage";}
        raw.reason=a.reason;return a;
    }
    public static bool AllowRefinement(MctsPlanner.Node node,PlanningSettings s,Audit last) {
        if(last==null||!last.needs_refinement||node.actions.Length>=s.widening_max_candidates)return false;
        // Local opportunity: do not add candidates to a locally flat, sampled node
        // merely because a different part of the tree is uncertain.
        double lo=double.PositiveInfinity,hi=double.NegativeInfinity,noise=0;
        foreach(var e in node.actions){if(e.immediate==null||e.visits==0)return false;if(e.immediate.predicted_game_over||!e.immediate.drop_success)continue;lo=Math.Min(lo,e.Mean);hi=Math.Max(hi,e.Mean);noise=Math.Max(noise,Variance(e));}
        return noise>0||hi-lo>s.adaptive_value_tolerance;
    }

    static MctsPlanner.Node TestNode(int id=0,int depth=0) {
        var n=new MctsPlanner.Node(5,id,depth){visits=128,positions=MctsAdaptiveControl.InitialPositions(5)};
        foreach(var e in n.actions){e.visits=16;e.sum=e.sumSquares=0;e.immediate=new StepPlanner.Candidate {success=true,drop_success=true};}
        return n;
    }
    static void Check(bool ok,string reason){if(!ok)throw new Exception("IMPORTANCE SELFTEST: "+reason);}
    public static void SelfTests() {
        var s=new PlanningSettings {ai_mode="mcts",mcts_extended_budget=true,mcts_budget_mode="importance",mcts_max_iterations=32768,mcts_time_limit_seconds=120,mcts_max_depth=4};s.Validate();
        var n=TestNode();var nodes=new List<MctsPlanner.Node>{n};var additions=new List<MctsAdaptiveControl.Addition>();var history=new List<Audit>();var context=new Context();
        for(int stage=0;stage<3;stage++){var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);Check(a.root.stable==(stage==2),"flat board needs three checkpoints");history.Add(a);}
        Check(history[2].practical_tie&&!history[2].needs_refinement,"equivalent sampled actions need no refinement");
        Check(!AllowRefinement(n,s,history[2]),"flat node no candidate inflation");
        history.Clear();
        for(int stage=0;stage<3;stage++){
            foreach(var e in n.actions)e.sum=e.sumSquares=0;
            n.actions[stage].sum=1.6;n.actions[stage].sumSquares=.16;
            var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);history.Add(a);
        }
        Check(history[2].root.stable&&history[2].equivalent_winner_change&&history[2].best_changes==2,"practically tied winner switches are logged, not falsely treated as meaningful rank instability");
        history.Clear();foreach(var e in n.actions){e.sum=160;e.sumSquares=3200;}n.actions[0].sum=168;n.actions[0].sumSquares=3364;
        for(int stage=0;stage<4;stage++){var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);Check(!a.root.stable&&a.continue_search,"overlapping variable returns continue");history.Add(a);}
        s.mcts_widening=true;s.widening_policy="budgeted";s.Validate();
        Check(AllowRefinement(n,s,history[3]),"uncertain local samples allow refinement");
        var edge=n.actions[0];var added=MctsAdaptiveControl.TryBudgeted(n,s,128,32768,10000,1);Check(added.Count==2&&ReferenceEquals(edge,n.actions[0]),"budgeted addition preserves old statistics");additions.AddRange(added);
        var pending=Assess(n,s,256,history,additions,nodes,context,10,10000,1);Check(!pending.root.stable&&pending.root_pending==2,"new root actions must be sampled");
        var future=TestNode(1,1);Check(MctsAdaptiveControl.TryBudgeted(future,s,128,32768,10000,1).Count==2,"nonroot additions supported");
        n=TestNode();nodes=new List<MctsPlanner.Node>{n};history.Clear();additions.Clear();context.near_line_contacted=1;
        for(int stage=0;stage<4;stage++){var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);Check(a.root.stable==(stage==3),"important stable board can stop at 256, not forced to time limit");history.Add(a);}
        future=TestNode(1,1);nodes.Add(future);future.actions[0].visits=0;future.actions[0].immediate=null;
        additions.Add(new MctsAdaptiveControl.Addition {node_id=1,depth=1,index=0});
        var nonroot=Assess(n,s,512,history,additions,nodes,context,10,10000,1);Check(nonroot.root.stable&&nonroot.nonroot_pending==1,"irrelevant nonroot additions do not veto root stability");
        history.Clear();context.near_line_contacted=0;additions.Clear();nodes.RemoveAt(1);
        n.actions[0].sum=160;n.actions[0].sumSquares=1600;
        for(int stage=0;stage<3;stage++){var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);history.Add(a);}
        Check(history[2].clear_leader&&history[2].root.stable,"separated deterministic leader");
        n.actions[0].sum=0;n.actions[1].sum=320;n.actions[1].sumSquares=6400;
        var changed=Assess(n,s,256,history,additions,nodes,context,10,10000,1);Check(!changed.root.stable&&changed.best_changes>0,"changed winner requires new evidence");
        var budget=Assess(n,s,256,history,additions,nodes,context,10,1,100);Check(!budget.continue_search&&budget.reason=="insufficient_budget_for_next_stage","bounded additional-stage estimate");
        n=TestNode();nodes=new List<MctsPlanner.Node>{n};history.Clear();foreach(var e in n.actions)e.immediate.predicted_game_over=true;
        for(int stage=0;stage<4;stage++){var a=Assess(n,s,32<<stage,history,additions,nodes,context,10,10000,1);history.Add(a);}
        Check(history[3].root.stable&&history[3].reason=="all_candidates_predicted_terminal","terminal fallback stops without altering GO or reward");
        s.mcts_auto_depth=false;s.mcts_max_depth=256;s.Validate();s.mcts_auto_depth=true;s.mcts_max_depth=4;s.Validate();
        Debug.Log("IMPORTANCE CONTROL SELFTESTS OK");
    }

}
