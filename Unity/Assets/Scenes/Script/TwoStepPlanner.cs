using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;

// Bounded depth-two expectimax, not MCTS. Each path owns a native scene and
// replays only its short prefix so that siblings never copy a cold intermediate board.
public static class TwoStepPlanner
{
    [Serializable] public class PathMetric
    {
        public int first_index,second_index,chance_index,chance_type,total_reward,first_reward,wait_reward,second_reward,total_ticks,first_ticks,second_ticks,merges,wait_merges;
        public float first_x,second_x,probability,leaf_value,points;
        public bool game_over,first_game_over,prefix_match;
        public double elapsed_ms;
    }
    [Serializable] public class Report
    {
        public string algorithm="depth2-expectimax",leaf,selection_rule="min terminal probability, then max expected points; existing first-step all-GO fallback";
        public string branching="fresh root + short-prefix replay; native world retained across both actions";
        public int paths,inter_step_wait_ticks,public_spawn_slots,chance_evaluations;
        public bool reward_chance_collapsed;
        public bool source_unchanged,prefixes_match=true;
        public double elapsed_ms,managed_start_bytes,managed_end_bytes,unity_allocated_start_bytes,unity_allocated_sampled_peak_bytes;
        public PathMetric[] outcomes;
    }
    static long Allocated() {return UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();}
    public static StepPlanner.Candidate Candidate(int i,float x,SuikaPhysicsSimulator.Result r,PlanningSettings s)
    {
        return new StepPlanner.Candidate {index=i,x=x,target_x=r.drop_success?r.applied_x:0,applied_x=r.applied_x,
            success=true,drop_success=r.drop_success,predicted_game_over=r.game_over,source_unchanged=true,
            evaluation=HeuristicEvaluator.Evaluate(r.evaluation_features,r.reward,s),predicted_score=r.score,reward=r.reward,
            score_before=r.score-r.reward,score_at_drop=r.score_at_drop,has_score_at_drop=r.drop_success,
            movement_reward=r.movement_reward,cooldown_wait_reward=r.cooldown_wait_reward,post_drop_reward=r.post_drop_reward,
            merges=r.merges,physics_steps=r.physics_steps,movement_steps=r.movement_steps,cooldown_wait_steps=r.cooldown_wait_steps,
            post_drop_steps=r.post_drop_steps,drop_tick=r.drop_tick,game_over_tick=r.game_over_tick,elapsed_ms=r.elapsed_ms,
            excluded_reason=r.game_over?"predicted_game_over":!r.drop_success?"drop_failed":null};
    }
    public static float LeafPoints(string mode,int totalReward,HeuristicEvaluator.Features features,ValueSnapshot state,PlanningSettings s,SuikaValueNetwork model)
    {
        if(mode=="reward" || state.game_over) return totalReward;
        if(mode=="heuristic") return totalReward+s.score_scale*HeuristicEvaluator.Evaluate(features,0,s).value;
        if(mode=="value") return totalReward+model.Predict(state);
        throw new ArgumentException("Unknown leaf evaluator");
    }
    public static StepPlanner.Decision Plan(PlayerController player,GameManager manager,Collider2D floor,PlanningSettings settings)
    {
        var s=settings.Freeze();int n=s.candidate_count,k=player.fruits.Length;
        if(floor==null || !(floor is BoxCollider2D) || !floor.enabled || floor.isTrigger || Mathf.Abs(Mathf.DeltaAngle(floor.transform.eulerAngles.z,0))>.001f)
            throw new InvalidOperationException("Two-step requires the same horizontal planning floor");
        if(k<1 || n*n*k>64) throw new InvalidOperationException("STEP8-A limited to 64 paths; use --candidates 2 or 3");
        bool collapse=s.search_leaf=="reward" && !s.two_step_exhaustive_reward;
        int chanceCount=collapse?1:k;
        var source=SuikaPhysicsSimulator.LiveSignature(player);var random=UnityEngine.Random.state;
        var range=player.GetDropRange();if(!range.valid)throw new InvalidOperationException(range.error);
        int initialScore=ScoreManager.Instance.GetScore();
        var network=s.search_leaf=="value"?SuikaValueNetwork.Load(s.value_model_path):null;
        var report=new Report {leaf=s.search_leaf,inter_step_wait_ticks=s.inter_step_wait_ticks,public_spawn_slots=k,chance_evaluations=chanceCount,reward_chance_collapsed=collapse,
            managed_start_bytes=GC.GetTotalMemory(false),unity_allocated_start_bytes=Allocated()};
        report.unity_allocated_sampled_peak_bytes=report.unity_allocated_start_bytes;
        var d=new StepPlanner.Decision {settings=s,ai_mode="two_step",evaluation_version="step8a-depth2-"+s.search_leaf,
            decision_id=Guid.NewGuid().ToString("N"),drop_range=range,candidates=new StepPlanner.Candidate[n],two_step=report,
            held_fruit_id=player.currentFruit.GetComponent<FruitEvolution>().ObservationId,held_fruit_type=player.currentFruit.GetComponent<FruitEvolution>().fruitType,
            next_fruit_type=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType,move_speed=player.EffectiveAIMoveSpeed,
            fixed_delta_time=Time.fixedDeltaTime,floor_y=floor.bounds.max.y,game_over_y=manager.GameOverHeight};
        if(network!=null){d.model_sha256=network.file_sha256;d.checkpoint_sha256=network.model.checkpoint_sha256;}
        var timer=Stopwatch.StartNew();var metrics=new List<PathMetric>();
        for(int i=0;i<n;i++)
        {
            float x1=(float)i/(n-1);string firstSignature=null;float expected=0,terminalProbability=0;
            for(int chance=0;chance<chanceCount;chance++)
            {
                PathMetric best=null;StepPlanner.Candidate bestTerminal=null;
                for(int j=0;j<n;j++)
                {
                    if(s.planning_budget_ms>0 && timer.Elapsed.TotalMilliseconds>s.planning_budget_ms)
                        throw new InvalidOperationException("Two-step budget exhausted; no partially weighted result used");
                    var pathTimer=Stopwatch.StartNew();
                    using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,floor))
                    {
                        var first=path.Advance(x1,s.post_drop_steps,chance);
                        if(d.source_fruits==null)d.source_fruits=first.initial_fruits;
                        string signature=JsonUtility.ToJson(new Prefix {fruits=first.fruits,held=first.current_fruit,score=first.score,ticks=first.physics_steps,go=first.game_over});
                        if(firstSignature==null)firstSignature=signature;
                        bool prefixMatch=firstSignature==signature;report.prefixes_match &= prefixMatch;
                        if(!prefixMatch) throw new InvalidOperationException("Prefix replay diverged; sibling comparison rejected");
                        if(d.candidates[i]==null) {d.candidates[i]=Candidate(i,x1,first,s);d.candidates[i].target_x=Mathf.Lerp(range.min_x,range.max_x,x1);}
                        var m=new PathMetric {first_index=i,second_index=j,chance_index=chance,
                            chance_type=player.fruits[chance].GetComponent<FruitEvolution>().fruitType,first_x=x1,second_x=(float)j/(n-1),
                            probability=1f/chanceCount,first_reward=first.reward,first_ticks=first.physics_steps,first_game_over=first.game_over,prefix_match=prefixMatch};
                        SuikaPhysicsSimulator.Result second=null;
                        if(!path.GameOver)path.WaitTicks(s.inter_step_wait_ticks);
                        if(!path.GameOver)second=path.Advance(m.second_x,s.post_drop_steps,-1);
                        var snapshot=path.Snapshot();m.total_reward=path.Score-initialScore;m.wait_reward=path.BoundaryWaitReward;
                        m.second_reward=second==null?0:second.reward;m.second_ticks=second==null?0:second.physics_steps;
                        m.total_ticks=path.TotalTicks;m.wait_merges=path.BoundaryWaitMerges;m.merges=first.merges+m.wait_merges+(second==null?0:second.merges);
                        m.game_over=path.GameOver;m.points=LeafPoints(s.search_leaf,m.total_reward,path.EvaluationFeatures(),snapshot,s,network);
                        m.leaf_value=m.points-m.total_reward;m.elapsed_ms=pathTimer.Elapsed.TotalMilliseconds;
                        if(m.total_reward!=m.first_reward+m.wait_reward+m.second_reward)throw new InvalidOperationException("Two-step reward not conserved");
                        metrics.Add(m);report.paths++;
                        var terminal=Candidate(j,m.second_x,second??first,s);
                        terminal.predicted_game_over=m.game_over;terminal.game_over_tick=path.TotalTicks;
                        terminal.evaluation=HeuristicEvaluator.Evaluate(path.EvaluationFeatures(),0,s);
                        if(best==null || (!m.game_over && best.game_over) || (m.game_over==best.game_over &&
                            (m.game_over?TerminalBetter(terminal,bestTerminal):m.points>best.points+.001f)))
                        {best=m;bestTerminal=terminal;}
                    }
                    report.unity_allocated_sampled_peak_bytes=Math.Max(report.unity_allocated_sampled_peak_bytes,Allocated());
                }
                expected+=best.points/chanceCount;if(best.game_over)terminalProbability+=1f/chanceCount;
            }
            var candidate=d.candidates[i];candidate.search_evaluated=true;candidate.search_score=expected;candidate.search_terminal_probability=terminalProbability;
            if(candidate.excluded_reason==null)candidate.selection_score_json=expected.ToString("R",System.Globalization.CultureInfo.InvariantCulture);
        }
        report.source_unchanged=source==SuikaPhysicsSimulator.LiveSignature(player)&&random.Equals(UnityEngine.Random.state)&&initialScore==ScoreManager.Instance.GetScore();
        if(!report.source_unchanged)throw new InvalidOperationException("Two-step changed live source/RNG");
        report.outcomes=metrics.ToArray();report.managed_end_bytes=GC.GetTotalMemory(false);report.elapsed_ms=timer.Elapsed.TotalMilliseconds;
        d.same_source_verified=report.source_unchanged&&report.prefixes_match;d.evaluated_count=n;StepPlanner.Choose(d);d.elapsed_ms=timer.Elapsed.TotalMilliseconds;return d;
    }
    static bool TerminalBetter(StepPlanner.Candidate a,StepPlanner.Candidate b)
    {
        var d=new StepPlanner.Decision {candidates=new[]{a,b}};a.index=0;b.index=1;
        StepPlanner.Choose(d);return d.selected_index==0;
    }
    [Serializable] class Prefix {public UDPCommunicatorUnity.BoardFruit[] fruits;public UDPCommunicatorUnity.ControlledFruit held;public int score,ticks;public bool go;}
}
