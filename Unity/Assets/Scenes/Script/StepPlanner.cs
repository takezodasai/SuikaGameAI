using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;

[Serializable]
public class PlanningSettings
{
    [Range(2,31)] public int candidate_count = 5;
    [Range(1,150)] public int post_drop_steps = 25;
    [Range(2,128)] public int height_bins = 9;
    public float score_scale = 55, weight_roughness = .2f;
    [HideInInspector] public float weight_danger = 0;
    [HideInInspector] public float weight_height = 0; // Legacy JSON compatibility; ignored.
    public float danger_band_fraction = .15f, uncontacted_risk_weight = .5f;
    public float planning_budget_ms;
    public string ai_mode="heuristic",value_model_path="",search_leaf="reward";
    public int inter_step_wait_ticks=0;
    // Execution policy only; does not alter UCT, depth, rollout or physical rules.
    public string execution_mode="sync";
    public bool frame_tick_slicing=false;
    public float frame_budget_ms=6,frame_timeout_seconds=24;
    public int frame_lead_ticks=150,frame_max_attempts=2;
    public int mcts_iterations=32,mcts_max_depth=3,mcts_seed=8191;
    public float mcts_exploration=1.41421356f,mcts_point_scale=55;
    public bool two_step_exhaustive_reward=false;
    public string candidate_policy="grid";
    public string rollout_policy="random",tree_policy="chance";
    public float rollout_random_probability=.5f;
    public bool mcts_common_chance=false;
    public string action_order_policy="index";
    public string expansion_policy="legacy";
    public int pair_coverage_iterations=0;
    public bool mcts_extended_budget=false, mcts_auto_depth=false, mcts_full_trace=false;
    public int auto_depth_min=2, auto_depth_max=8;
    public string mcts_budget_mode="fixed";
    public float mcts_time_limit_seconds=5;
    public int mcts_max_iterations=256,adaptive_initial_iterations=32,adaptive_min_action_visits=4;
    public float adaptive_uncertainty_multiplier=1,adaptive_value_tolerance=3,adaptive_max_terminal_rate=.1f;
    public bool mcts_widening=false;
    public int widening_max_candidates=9,widening_after_visits=10,widening_min_action_visits=1;
    public float widening_min_spacing=.03125f;
    public PlanningSettings Freeze()
    {
        var copy = JsonUtility.FromJson<PlanningSettings>(JsonUtility.ToJson(this));
        copy.Validate(); copy.weight_height=0; copy.weight_danger=0; return copy;
    }
    public void Validate()
    {
        MctsAdaptiveControl.Validate(this);
        if(pair_coverage_iterations<0||pair_coverage_iterations>25||pair_coverage_iterations>mcts_iterations)throw new ArgumentException("Invalid pair coverage budget");
        if(pair_coverage_iterations>0&&(ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing||candidate_policy!="grid"||candidate_count!=5||mcts_max_depth<2||tree_policy!="chance"||rollout_policy!="random"||action_order_policy!="index"||expansion_policy!="legacy"))throw new ArgumentException("Pair coverage prototype requires sync five-grid legacy chance/random MCTS");
        if(action_order_policy!="index"&&action_order_policy!="shuffle")throw new ArgumentException("Invalid action order policy");
        if(action_order_policy!="index"&&(ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing||tree_policy!="chance"||candidate_policy!="grid"||rollout_policy!="random"||expansion_policy!="legacy"))throw new ArgumentException("Shuffle prototype requires sync chance grid MCTS with legacy expansion and random rollout");
        if(expansion_policy!="legacy"&&expansion_policy!="chance_decision")throw new ArgumentException("Invalid expansion policy");
        if(expansion_policy!="legacy"&&(ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing||tree_policy!="chance"||candidate_policy!="grid"||rollout_policy!="random"))throw new ArgumentException("Chance-decision prototype requires sync chance-tree grid MCTS with random rollout");
        if(tree_policy!="chance"&&tree_policy!="public_open_loop")throw new ArgumentException("Invalid tree policy");
        if(tree_policy!="chance"&&(ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing||candidate_policy!="grid"||rollout_policy!="random"))throw new ArgumentException("Open-loop prototype requires sync grid MCTS with random rollout");
        if((rollout_policy!="random"&&rollout_policy!="guided") || float.IsNaN(rollout_random_probability)||float.IsInfinity(rollout_random_probability)||rollout_random_probability<0||rollout_random_probability>1)throw new ArgumentException("Invalid rollout policy");
        if((rollout_policy!="random"||mcts_common_chance) && (ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing))throw new ArgumentException("Guided rollout prototype requires synchronous MCTS");
        if(candidate_policy!="grid" && candidate_policy!="board-five" && candidate_policy!="coarse-root")throw new ArgumentException("Unknown candidate policy");
        if(candidate_policy=="coarse-root"&&(candidate_count!=7||ai_mode!="mcts"||execution_mode!="sync"||frame_tick_slicing||tree_policy!="chance"||rollout_policy!="random"||expansion_policy!="legacy"||action_order_policy!="index"))throw new ArgumentException("Coarse-root requires seven root actions, sync legacy chance MCTS with random rollout/index order");
        if(candidate_policy=="board-five" && (candidate_count!=5 || ai_mode!="mcts" || execution_mode!="sync" || frame_tick_slicing))
            throw new ArgumentException("Board-five prototype requires synchronous MCTS with five candidates");
        if((execution_mode!="sync" && execution_mode!="frames" && execution_mode!="frames_adaptive") ||
            float.IsNaN(frame_budget_ms)||float.IsInfinity(frame_budget_ms)||frame_budget_ms<1||frame_budget_ms>30 ||
            float.IsNaN(frame_timeout_seconds)||float.IsInfinity(frame_timeout_seconds)||frame_timeout_seconds<1||frame_timeout_seconds>25 ||
            frame_lead_ticks<10||frame_lead_ticks>500||frame_max_attempts<1||frame_max_attempts>3 ||
            (execution_mode!="sync" && ai_mode!="mcts" && ai_mode!="mcts_value")) throw new ArgumentException("Invalid frame execution policy");
        if(ai_mode!="heuristic" && ai_mode!="value" && ai_mode!="two_step" && ai_mode!="mcts" && ai_mode!="mcts_value") throw new ArgumentException("Unknown AI mode");
        if((search_leaf!="reward" && search_leaf!="heuristic" && search_leaf!="value") || inter_step_wait_ticks<0 || inter_step_wait_ticks>500) throw new ArgumentException("Invalid two-step leaf/wait");
        if(mcts_iterations<(mcts_extended_budget?32:2) || mcts_iterations>(mcts_extended_budget?32768:256) || mcts_max_depth<(mcts_extended_budget?2:1) || mcts_max_depth>(mcts_extended_budget?256:8) || mcts_seed<0 ||
            float.IsNaN(mcts_exploration) || float.IsInfinity(mcts_exploration) || mcts_exploration<0 ||
            float.IsNaN(mcts_point_scale) || float.IsInfinity(mcts_point_scale) || mcts_point_scale<=0 ||
            ((ai_mode=="mcts" || ai_mode=="mcts_value") && mcts_iterations<candidate_count)) throw new ArgumentException("Invalid MCTS budget/depth/scale/seed");
        if(candidate_count<2 || candidate_count>31 || post_drop_steps<1 || post_drop_steps>150 || height_bins<2 || height_bins>128)
            throw new ArgumentException("Invalid planning count/horizon/bins");
        foreach(float n in new[]{score_scale,weight_height,weight_danger,weight_roughness,danger_band_fraction,uncontacted_risk_weight,planning_budget_ms})
            if(float.IsNaN(n)||float.IsInfinity(n)||n<0) throw new ArgumentException("Invalid planning coefficient");
        if(score_scale<=0 || danger_band_fraction<=0 || danger_band_fraction>1 || uncontacted_risk_weight>1)
            throw new ArgumentException("Invalid planning normalization");
    }
}

// No physics changes here: pure numerical features -> evaluation -> choice.
public static class HeuristicEvaluator
{
    [Serializable] public class FruitFeature
    {
        public long id; public bool contacted, has_collided;
        public float min_x,max_x,top_y,center_y;
    }
    [Serializable] public class Features
    {
        public FruitFeature[] fruits;
        public float floor_y,go_y,left_x,right_x;
    }
    [Serializable] public class Breakdown
    {
        public float height,danger,roughness,score_term,height_penalty,danger_penalty,roughness_penalty,value;
        public float terminal_excess,unclamped_height,airborne_top;
        public int board_count,contact_count,airborne_count;
        public long danger_fruit_id; public bool danger_fruit_has_collided;
    }
    public static Breakdown Evaluate(Features f, int reward, PlanningSettings s)
    {
        s.Validate();
        float length=f.go_y-f.floor_y;
        if(length<=0 || f.right_x<=f.left_x || f.fruits==null) throw new ArgumentException("Invalid evaluation geometry");
        var b=new Breakdown(); var bins=new float[s.height_bins];
        foreach(var fruit in f.fruits)
        {
            foreach(float v in new[]{fruit.min_x,fruit.max_x,fruit.top_y,fruit.center_y})
                if(float.IsNaN(v)||float.IsInfinity(v)) throw new ArgumentException("Nonfinite collider feature");
            b.board_count++;
            float raw=(fruit.top_y-f.floor_y)/length, h=Mathf.Clamp01(raw);
            b.unclamped_height=Mathf.Max(b.unclamped_height,raw);
            if(fruit.contacted)
            {
                b.contact_count++; b.height=Mathf.Max(b.height,h);
                for(int j=0;j<bins.Length;j++)
                {
                    float left=Mathf.Lerp(f.left_x,f.right_x,(float)j/bins.Length);
                    float right=Mathf.Lerp(f.left_x,f.right_x,(float)(j+1)/bins.Length);
                    if(fruit.max_x>left && fruit.min_x<right) bins[j]=Mathf.Max(bins[j],h);
                }
            }
            else { b.airborne_count++; b.airborne_top=Mathf.Max(b.airborne_top,raw); }
            float risk=Mathf.Clamp01((fruit.center_y-(f.go_y-s.danger_band_fraction*length))/(s.danger_band_fraction*length))
                *(fruit.has_collided?1:s.uncontacted_risk_weight);
            if(risk>b.danger) { b.danger=risk; b.danger_fruit_id=fruit.id; b.danger_fruit_has_collided=fruit.has_collided; }
            if(fruit.has_collided) b.terminal_excess=Mathf.Max(b.terminal_excess,(fruit.center_y-f.go_y)/length);
        }
        float mean=0,variance=0;
        foreach(float v in bins) mean+=v/bins.Length;
        foreach(float v in bins) variance+=(v-mean)*(v-mean)/bins.Length;
        b.roughness=Mathf.Clamp01(2*Mathf.Sqrt(variance));
        b.score_term=reward/s.score_scale;
        b.height_penalty=0; // Retained diagnostic field. H never affects the STEP 6 evaluation.
        b.danger_penalty=0; // D is diagnostic only, including legacy nonzero settings.
        b.roughness_penalty=s.weight_roughness*b.roughness;
        b.value=b.score_term-b.height_penalty-b.danger_penalty-b.roughness_penalty;
        return b;
    }
}

public static class StepPlanner
{
    [Serializable] public class Candidate
    {
        public int index; public float x,target_x,applied_x;
        public bool success,drop_success,predicted_game_over,source_unchanged;
        public string excluded_reason;
        public bool value_evaluated,search_evaluated;
        public float search_score,search_terminal_probability;
        public float future_value,q_points;
        public double inference_ms;
        public ValueSnapshot value_state;
        // JsonUtility has no nullable floats; the string is valid JSON numeric text or null.
        // Eligibility is explicit. Python converts selection_score_json to a nullable number.
        public string selection_score_json = "null";
        public HeuristicEvaluator.Breakdown evaluation;
        public int predicted_score,reward,movement_reward,cooldown_wait_reward,post_drop_reward,merges;
        public int score_before,score_at_drop,physics_steps,movement_steps,cooldown_wait_steps,post_drop_steps,drop_tick,game_over_tick;
        public bool has_score_at_drop;
        public double elapsed_ms,scene_create_ms,copy_ms,simulation_ms,cleanup_schedule_ms;
    }
    [Serializable] public class Decision
    {
        public string evaluation_version="step5-v3-score-roughness",status,episode_id,decision_id;
        public string ai_mode="heuristic",model_sha256,checkpoint_sha256;
        [NonSerialized] public TwoStepPlanner.Report two_step;
        [NonSerialized] public MctsPlanner.Report mcts;
        [NonSerialized] public FrameSearchReport frame_search;
        public long source_state_id,held_fruit_id;
        public int held_fruit_type,next_fruit_type,selected_index=-1,evaluated_count;
        public bool partial_plan,all_predicted_terminal;
        public float selected_x,fixed_delta_time,move_speed,floor_y,game_over_y;
        public double elapsed_ms,model_load_ms;
        public PlanningSettings settings;
        public PlayerController.DropRange drop_range;
        public Candidate[] candidates;
        public UDPCommunicatorUnity.BoardFruit[] source_fruits;
        public bool same_source_verified;
    }
    public static Decision Plan(PlayerController player,GameManager manager,Collider2D floor,PlanningSettings settings)
    {
        var s=settings.Freeze();
        if(s.ai_mode=="mcts" || s.ai_mode=="mcts_value") return MctsPlanner.Plan(player,manager,floor,s);
        if(s.ai_mode=="two_step") return TwoStepPlanner.Plan(player,manager,floor,s);
        if(floor==null || !floor.enabled || !floor.gameObject.activeInHierarchy || floor.isTrigger || !(floor is BoxCollider2D)
            || Mathf.Abs(Mathf.DeltaAngle(floor.transform.eulerAngles.z,0))>.001f)
            throw new InvalidOperationException("Planning Floor must reference the existing horizontal BoxCollider2D: "+(floor==null?"missing":floor.GetType().Name+" enabled="+floor.enabled+" active="+floor.gameObject.activeInHierarchy+" trigger="+floor.isTrigger+" angle="+floor.transform.eulerAngles.z));
        var range=player.GetDropRange();
        if(!range.valid || range.max_x<=range.min_x || floor.bounds.max.y>=manager.GameOverHeight)
            throw new InvalidOperationException("Invalid planning floor/drop range");
        var d=new Decision { settings=s,drop_range=range,decision_id=Guid.NewGuid().ToString("N"),
            held_fruit_id=player.currentFruit.GetComponent<FruitEvolution>().ObservationId,
            held_fruit_type=player.currentFruit.GetComponent<FruitEvolution>().fruitType,
            next_fruit_type=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType,
            fixed_delta_time=Time.fixedDeltaTime,move_speed=player.EffectiveAIMoveSpeed,
            floor_y=floor.bounds.max.y,game_over_y=manager.GameOverHeight,candidates=new Candidate[s.candidate_count] };
        // Fail closed before any candidate/action if the requested model is unavailable.
        var loadTimer=Stopwatch.StartNew();
        var network=s.ai_mode=="value"?SuikaValueNetwork.Load(s.value_model_path):null;
        d.model_load_ms=s.ai_mode=="value"?loadTimer.Elapsed.TotalMilliseconds:0;
        d.ai_mode=s.ai_mode;
        if(network!=null) {d.evaluation_version="step7c-v1-value-points";d.model_sha256=network.file_sha256;d.checkpoint_sha256=network.model.checkpoint_sha256;}
        var timer=Stopwatch.StartNew();
        for(int i=0;i<s.candidate_count;i++)
        {
            float x=(float)i/(s.candidate_count-1);
            var c=new Candidate { index=i,x=x,target_x=Mathf.Lerp(range.min_x,range.max_x,x),excluded_reason="not_evaluated" };
            d.candidates[i]=c;
            if(s.planning_budget_ms>0 && timer.Elapsed.TotalMilliseconds>=s.planning_budget_ms) continue;
            d.evaluated_count++;
            try
            {
                var r=SuikaPhysicsSimulator.Predict(player,manager,x,s.post_drop_steps,floor);
                if(d.source_fruits==null) d.source_fruits=r.initial_fruits;
                else if(JsonUtility.ToJson(new BoardWrapper {fruits=d.source_fruits})!=JsonUtility.ToJson(new BoardWrapper {fruits=r.initial_fruits}))
                    throw new InvalidOperationException("Candidate initial board mismatch");
                c.evaluation=HeuristicEvaluator.Evaluate(r.evaluation_features,r.reward,s);
                c.success=true;c.drop_success=r.drop_success;c.predicted_game_over=r.game_over;c.source_unchanged=r.source_unchanged;
                c.applied_x=r.applied_x;c.predicted_score=r.score;c.reward=r.reward;c.merges=r.merges;
                c.score_before=r.score-r.reward;c.score_at_drop=r.score_at_drop;c.has_score_at_drop=r.drop_success;
                c.movement_reward=r.movement_reward;c.cooldown_wait_reward=r.cooldown_wait_reward;c.post_drop_reward=r.post_drop_reward;
                c.physics_steps=r.physics_steps;c.movement_steps=r.movement_steps;c.cooldown_wait_steps=r.cooldown_wait_steps;
                c.post_drop_steps=r.post_drop_steps;c.drop_tick=r.drop_tick;c.game_over_tick=r.game_over_tick;
                c.elapsed_ms=r.elapsed_ms;c.scene_create_ms=r.scene_create_ms;c.copy_ms=r.copy_ms;
                c.simulation_ms=r.simulation_ms;c.cleanup_schedule_ms=r.cleanup_schedule_ms;
                c.excluded_reason=r.game_over?"predicted_game_over":!r.drop_success?"drop_failed":null;
                if(network!=null)
                {
                    c.value_state=r.value_state;
                    var inference=Stopwatch.StartNew();c.future_value=network.Predict(r.value_state);
                    c.inference_ms=inference.Elapsed.TotalMilliseconds;
                    c.q_points=r.reward+c.future_value;c.value_evaluated=true;
                }
                if(c.excluded_reason==null) c.selection_score_json=(c.value_evaluated?c.q_points:c.evaluation.value).ToString("R",System.Globalization.CultureInfo.InvariantCulture);
            }
            catch(Exception e) { c.success=false;c.selection_score_json="null"; c.excluded_reason="prediction_failed:"+e.Message; }
        }
        d.same_source_verified=d.evaluated_count==s.candidate_count;
        foreach(var c in d.candidates) d.same_source_verified &= c.success && c.source_unchanged;
        Choose(d);d.elapsed_ms=timer.Elapsed.TotalMilliseconds;return d;
    }
    [Serializable] class BoardWrapper { public UDPCommunicatorUnity.BoardFruit[] fruits; }
    public static void Choose(Decision d)
    {
        d.selected_index=-1;d.all_predicted_terminal=false;
        Candidate best=null;
        bool allTerminal=true; int successes=0;
        foreach(var c in d.candidates)
        {
            if(c.success) successes++;
            if(!c.success || !c.predicted_game_over) allTerminal=false;
            if(!c.success || !c.drop_success || c.predicted_game_over) continue;
            if(best==null || BetterNormal(c,best)) best=c;
        }
        d.partial_plan=successes<d.candidates.Length;
        if(best==null && allTerminal)
        {
            d.all_predicted_terminal=true;
            foreach(var c in d.candidates)
                if(best==null || BetterTerminal(c,best)) best=c;
        }
        d.status=best==null?"no_nonterminal_evaluated":d.all_predicted_terminal?"all_predicted_terminal":d.partial_plan?"partial_plan":"selected";
        if(best!=null) {d.selected_index=best.index;d.selected_x=best.x;}
    }
    static bool BetterNormal(Candidate a,Candidate b)
    {
        if(a.search_evaluated && b.search_evaluated && Mathf.Abs(a.search_terminal_probability-b.search_terminal_probability)>1e-6f) return a.search_terminal_probability<b.search_terminal_probability;
        float av=a.search_evaluated?a.search_score:a.value_evaluated?a.q_points:a.evaluation.value,bv=b.search_evaluated?b.search_score:b.value_evaluated?b.q_points:b.evaluation.value;
        if(Mathf.Abs(av-bv)>(a.value_evaluated||a.search_evaluated?0.001f:1e-6f)) return av>bv;
        if(a.drop_tick!=b.drop_tick) return a.drop_tick<b.drop_tick;
        return a.index<b.index;
    }
    static bool BetterTerminal(Candidate a,Candidate b)
    {
        if(a.game_over_tick!=b.game_over_tick) return a.game_over_tick>b.game_over_tick;
        if(a.evaluation.terminal_excess!=b.evaluation.terminal_excess) return a.evaluation.terminal_excess<b.evaluation.terminal_excess;
        if(a.evaluation.value!=b.evaluation.value) return a.evaluation.value>b.evaluation.value;
        return a.index<b.index;
    }
}
