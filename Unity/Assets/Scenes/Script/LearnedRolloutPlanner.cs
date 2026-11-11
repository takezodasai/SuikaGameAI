using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;
using Edge = MctsPlanner.Edge;
using Node = MctsPlanner.Node;
using ActionMetric = MctsPlanner.ActionMetric;
using NodeMetric = MctsPlanner.NodeMetric;
using IterationMetric = MctsPlanner.IterationMetric;
using Report = MctsPlanner.Report;
// Isolated exact source clone, changes limited to rollout dispatch. Original MCTS untouched.
public static class LearnedRolloutPlanner {
    // Values are points. Only UCT's selection statistic is divided by a declared
    // point scale, so exploration C is dimensionless; logged/backed-up returns stay points.
    public static int Select(Node node,double exploration,double scale)
    {
        using(MctsPerformance.Measure("uct_select")) {

        bool safe=false;foreach(var e in node.actions) if(e.immediate==null || (!e.immediate.predicted_game_over&&e.immediate.drop_success))safe=true;
        // A per-node permutation only orders first visits. The UCT loop/ties below stay unchanged.
        if(node.unvisited_order!=null)foreach(int i in node.unvisited_order) {
            var e=node.actions[i];
            if(e.visits==0 && !(safe&&e.immediate!=null&&(e.immediate.predicted_game_over||!e.immediate.drop_success)))return i;
        }
        int best=-1;double score=double.NegativeInfinity;
        for(int i=0;i<node.actions.Length;i++)
        {
            var e=node.actions[i];
            if(safe && e.immediate!=null && (e.immediate.predicted_game_over||!e.immediate.drop_success))continue;
            if(e.visits==0)return i;
            double v=e.Mean/scale+exploration*Math.Sqrt(Math.Log(Math.Max(1,node.visits))/e.visits);
            if(v>score){score=v;best=i;}
        }
        if(!safe)
        {
            var d=new StepPlanner.Decision {candidates=new StepPlanner.Candidate[node.actions.Length]};
            for(int i=0;i<node.actions.Length;i++)d.candidates[i]=node.actions[i].immediate;
            StepPlanner.Choose(d);return d.selected_index;
        }
        return best;
    
        }
}
    // Independent, node-local Fisher-Yates stream: never consumes chance/rollout/live RNG.
    public static int[] ShuffledOrder(int count,int seed,int nodeId) {
        var order=new int[count];for(int i=0;i<count;i++)order[i]=i;
        var shuffle=new System.Random(unchecked(seed*1000003 ^ nodeId*9176 ^ 0x4D435453));
        for(int i=count-1;i>0;i--){int j=shuffle.Next(i+1);int tmp=order[i];order[i]=order[j];order[j]=tmp;}
        return order;
    }
    static Node SearchNode(int id,int depth,PlanningSettings s) {
        var n=new Node(s.candidate_policy=="coarse-root"&&depth>0?5:s.candidate_count,id,depth);
        if(s.action_order_policy=="shuffle")n.unvisited_order=ShuffledOrder(s.candidate_count,s.mcts_seed,id);
        if(s.mcts_widening)n.positions=MctsAdaptiveControl.InitialPositions(s.candidate_count);
        return n;
    }
    static readonly int[] CoverageSeconds={0,2,4,1,3};
    public static int CoverageAction(int iteration,int depth) {
        if(iteration<0||iteration>=25||depth<0)throw new ArgumentOutOfRangeException();
        return depth==0?iteration%5:depth==1?CoverageSeconds[iteration/5]:-1;
    }
    // At most one extra decision action per iteration, even if that action creates another chance child.
    public static bool AfterChanceRollout(bool expanded,bool newChance,bool extend,bool extraUsed,out bool pending) {
        pending=extend&&newChance&&!extraUsed;
        return !pending&&(expanded||newChance);
    }
    public static StepPlanner.Candidate[] BindOpenState(Node node,string stateKey,int count) {
        if(node.state_immediates==null) {
            node.state_immediates=new Dictionary<string,StepPlanner.Candidate[]>();node.state_transitions=new Dictionary<string,string[]>();node.state_signatures=new HashSet<string>();
        }
        node.state_signatures.Add(stateKey);StepPlanner.Candidate[] local;
        if(!node.state_immediates.TryGetValue(stateKey,out local)) {
            local=new StepPlanner.Candidate[count];node.state_immediates.Add(stateKey,local);node.state_transitions.Add(stateKey,new string[count]);
        }
        for(int a=0;a<count;a++)node.actions[a].immediate=local[a];return local;
    }
    public static string OpenNodeKey(string history,string publicFruitKey) {return history+"|"+publicFruitKey;}
    static string Digest(string value)
    {
        using(var sha=System.Security.Cryptography.SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(value)));
    }
    [Serializable] class Transition {public UDPCommunicatorUnity.BoardFruit[] fruits;public UDPCommunicatorUnity.ControlledFruit held;public int score,ticks;public bool go;}
    struct Visit {public Node node;public Edge edge;public int score;}
    public static StepPlanner.Decision Plan(PlayerController player,GameManager manager,Collider2D floor,PlanningSettings settings)
    {
        var previous=MctsPerformance.Current;
        var profile=SuikaRuntimeProbe.Instance!=null&&!MctsPerformance.SuppressProfiler?new MctsPerformance():previous;
        MctsPerformance.Current=profile;
        try {
            StepPlanner.Decision result;
            using(MctsPerformance.Measure("plan_total")) {
                result=null;
                using(var work=PlanFrames(player,manager,floor,settings))
                    while(work.MoveNext())if(work.Current!=null)result=work.Current;
            }
            if(profile!=null)result.mcts.profile=profile.Results();
            return result;
        } finally {MctsPerformance.Current=previous;}
    }
    public static IEnumerator<StepPlanner.Decision> PlanFrames(PlayerController player,GameManager manager,Collider2D floor,PlanningSettings settings,SuikaPhysicsSimulator.PathSession frozenRoot=null)
    {
        var extendedTimer=settings.mcts_extended_budget?Stopwatch.StartNew():null;
        LearnedRolloutPolicy.Begin(settings.mcts_seed,settings.mcts_max_depth);
        var s=settings.Freeze();bool open=s.tree_policy=="public_open_loop",extend=s.expansion_policy=="chance_decision";
        if(floor==null || !(floor is BoxCollider2D) || !floor.enabled || floor.isTrigger || Mathf.Abs(Mathf.DeltaAngle(floor.transform.eulerAngles.z,0))>.001f)
            throw new InvalidOperationException("MCTS requires the existing horizontal planning floor");
        int slots=player.fruits.Length;if(slots<1)throw new InvalidOperationException("No public fruit slots");
        var range=player.GetDropRange();if(!range.valid)throw new InvalidOperationException(range.error);
        string source=frozenRoot==null?SuikaPhysicsSimulator.LiveSignature(player):frozenRoot.StateSignature();var liveRandom=UnityEngine.Random.state;int initialScore=frozenRoot==null?ScoreManager.Instance.GetScore():frozenRoot.Score;
        var network=s.ai_mode=="mcts_value"?SuikaValueNetwork.Load(s.value_model_path):null;
        var publicTypes=new int[slots];for(int slot=0;slot<slots;slot++)publicTypes[slot]=player.fruits[slot].GetComponent<FruitEvolution>().fruitType;
        var rng=new System.Random(s.mcts_seed);var root=SearchNode(0,0,s);var nodes=new List<Node>{root};
        var report=new Report {experimental_depth=s.mcts_max_depth>=16,leaf=network==null?"reward":"value",requested_iterations=s.mcts_iterations,max_depth=s.mcts_max_depth,seed=s.mcts_seed,
            candidate_policy=s.candidate_policy,public_spawn_slots=slots,public_spawn_types=publicTypes,irrelevant_final_chance_collapsed=network==null&&s.mcts_max_depth>=2&&!(LearnedRolloutPolicy.Active!=null&&LearnedRolloutPolicy.Mixture>0),managed_start_bytes=GC.GetTotalMemory(false),unity_allocated_start_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()};
        report.lifetime_start=PredictionLifecycle.Read(false);
        report.unity_allocated_sampled_peak_bytes=report.unity_allocated_start_bytes;
        var d=new StepPlanner.Decision {settings=s,ai_mode=s.ai_mode,evaluation_version="step8b-uct-"+report.leaf,mcts=report,
            decision_id=Guid.NewGuid().ToString("N"),drop_range=range,candidates=new StepPlanner.Candidate[s.candidate_count],
            held_fruit_id=player.currentFruit.GetComponent<FruitEvolution>().ObservationId,held_fruit_type=player.currentFruit.GetComponent<FruitEvolution>().fruitType,
            next_fruit_type=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType,move_speed=player.EffectiveAIMoveSpeed,
            fixed_delta_time=Time.fixedDeltaTime,floor_y=floor.bounds.max.y,game_over_y=manager.GameOverHeight};
        if(network!=null){d.model_sha256=network.file_sha256;d.checkpoint_sha256=network.model.checkpoint_sha256;}
        var sharedNodes=new Dictionary<string,Node>();
        report.pair_coverage_iterations=s.pair_coverage_iterations;report.action_order_policy=s.action_order_policy;report.expansion_policy=s.expansion_policy;report.tree_policy=s.tree_policy;report.sharing_limitation=open?"action history + observed held/NEXT; past board differences averaged statistically, never reused physically":"full action/chance history";
        report.rollout_policy=s.rollout_policy;report.common_chance=s.mcts_common_chance;report.rollout_by_depth=new int[s.mcts_max_depth];
        if(s.mcts_common_chance) {
            var crng=new System.Random(s.mcts_seed^0x356A9);report.common_chance_samples=new int[s.mcts_iterations*s.mcts_max_depth];
            for(int i=0;i<report.common_chance_samples.Length;i++)report.common_chance_samples[i]=crng.Next(slots);
        }
        var timer=extendedTimer??Stopwatch.StartNew();var iterations=new List<IterationMetric>();
        if(s.candidate_policy=="coarse-root") {
            var generation=Stopwatch.StartNew();
            using(var preview=frozenRoot==null?new SuikaPhysicsSimulator.PathSession(player,manager,floor):frozenRoot.Fork(manager))
                report.refinement=CoarseToFineCandidates.Build(preview,manager,s);
            report.refinement.total_ms=generation.Elapsed.TotalMilliseconds;
            report.candidate_generation_ms+=report.refinement.total_ms;report.candidate_generation_calls++;
            root.positions=new DropCandidateGenerator.Set {x=report.refinement.positions,sources=new string[s.candidate_count]};
            for(int i=0;i<s.candidate_count;i++)root.positions.sources[i]=Array.IndexOf(report.refinement.added,root.positions.x[i])>=0?"coarse-midpoint":"coarse-anchor";
        }
        bool flexible=s.mcts_budget_mode!="fixed"||s.mcts_extended_budget;
        int cap=s.mcts_budget_mode!="fixed"?s.mcts_max_iterations:s.mcts_iterations;
        report.iteration_cap=cap;if(flexible)report.requested_iterations=cap;report.time_limit_ms=flexible?s.mcts_time_limit_seconds*1000d:0;
        report.budget_stop_reason="iteration_limit";
        var checkpoints=new List<MctsAdaptiveControl.Checkpoint>();var additions=new List<MctsAdaptiveControl.Addition>();
        bool importance=s.mcts_budget_mode=="importance";
        var importanceChecks=new List<MctsImportanceControl.Audit>();
        if(importance)report.importance_context=MctsImportanceControl.Capture(player,manager,initialScore,frozenRoot);
        int nextCheckpoint=s.adaptive_initial_iterations,previousWinner=-1,previousCheckpoint=0;double previousMean=0,maxIterationMs=0;
        for(int iteration=0;iteration<cap;iteration++)
        {
            if(flexible&&timer.Elapsed.TotalMilliseconds>=report.time_limit_ms){report.budget_stop_reason="time_limit";break;}
            if(s.planning_budget_ms>0 && timer.Elapsed.TotalMilliseconds>s.planning_budget_ms)
                throw new InvalidOperationException("MCTS budget exhausted; no action committed from incomplete search");
            bool coverage=iteration<s.pair_coverage_iterations;var forcedSteps=new List<bool>();
            var watch=Stopwatch.StartNew();var visits=new List<Visit>();var actions=new List<int>();var chances=new List<int>();var treeIds=new List<int>();var observations=new List<string>();var stateDigests=new List<string>();var rolloutSteps=new List<bool>();var guidedSteps=new List<bool>();var actionXs=s.candidate_policy=="grid"&&!s.mcts_widening?null:new List<float>();
            root.arrivals++;var node=root;string history="";bool rollout=false,extraUsed=false,chancePending=false;int extraDecisions=0,expandedActions=0,newChanceNodes=0;int merges=0;Edge freshLeaf=null,cachedLeaf=null;
            using(var path=frozenRoot==null?new SuikaPhysicsSimulator.PathSession(player,manager,floor):frozenRoot.Fork(manager))
            {
                for(int depth=0;depth<s.mcts_max_depth && !path.GameOver;depth++)
                {
                    if(chancePending) {
                        if(rollout||extraUsed)throw new InvalidOperationException("Invalid extra-decision boundary");
                        chancePending=false;extraUsed=true;extraDecisions++;
                    }
                    string stateKey=null;StepPlanner.Candidate[] localImmediate=null;string[] localTransitions=null;
                    string publicKey=(open||extend||flexible||s.mcts_widening)?path.PublicFruitKey(network==null&&depth>0&&depth==s.mcts_max_depth-1):null;
                    if(open||extend||flexible||s.mcts_widening) {observations.Add(publicKey);treeIds.Add(rollout?-1:node.id);}
                    if(!rollout)
                    {
                        string signature=path.StateSignature();
                        if(open) {
                            stateKey=signature;node.public_context=publicKey;node.history_key=history;
                            bool fresh=node.state_immediates==null||!node.state_immediates.ContainsKey(stateKey);
                            localImmediate=BindOpenState(node,stateKey,s.candidate_count);localTransitions=node.state_transitions[stateKey];
                            if(fresh)report.local_state_entries++;
                        } else {
                            if(node.signature==null)node.signature=signature;
                            else if(node.signature!=signature){report.prefixes_match=false;throw new InvalidOperationException("MCTS native prefix replay diverged");}
                        }
                    }
                    if(open)stateDigests.Add(Digest(stateKey??path.StateSignature()));
                    if(s.mcts_widening&&!rollout) {
                        if(s.widening_policy=="budgeted") {
                            if(!importance||MctsImportanceControl.AllowRefinement(node,s,importanceChecks.Count==0?null:importanceChecks[importanceChecks.Count-1]))
                                additions.AddRange(MctsAdaptiveControl.TryBudgeted(node,s,iteration,cap,report.time_limit_ms-timer.Elapsed.TotalMilliseconds,maxIterationMs));
                            if(depth==0)Array.Resize(ref d.candidates,node.actions.Length);
                        } else {
                            var added=MctsAdaptiveControl.TryWiden(node,s,iteration);
                            if(added!=null){additions.Add(added);if(depth==0)Array.Resize(ref d.candidates,node.actions.Length);}
                        }
                    }
                    int actionCount=s.mcts_widening&&!rollout?node.actions.Length:s.candidate_policy=="coarse-root"&&depth>0?5:s.candidate_count;
                    DropCandidateGenerator.Set positions=s.mcts_widening&&!rollout?node.positions:s.candidate_policy=="coarse-root"&&depth==0?root.positions:null;
                    if(s.candidate_policy=="board-five") {
                        positions=rollout?null:node.positions;
                        if(positions==null) {
                            var geometryWatch=Stopwatch.StartNew();
                            using(MctsPerformance.Measure("candidate_geometry"))positions=path.DropCandidates();
                            report.candidate_generation_ms+=geometryWatch.Elapsed.TotalMilliseconds;report.candidate_generation_calls++;
                            if(!rollout)node.positions=positions;
                        }
                    }
                    int action;bool guided=false;
                    if(rollout) {
                        var choiceWatch=Stopwatch.StartNew();report.rollout_calls++;report.rollout_by_depth[depth]++;
                        int beforeLearned=LearnedRolloutPolicy.Last.learned_calls;
                        action=LearnedRolloutPolicy.Choose(path,rng,actionCount,depth);
                        guided=LearnedRolloutPolicy.Last.learned_calls>beforeLearned;
                        if(guided)report.guided_calls++;
                        report.rollout_choice_ms+=choiceWatch.Elapsed.TotalMilliseconds;
                    } else action=Select(node,s.mcts_exploration,s.mcts_point_scale);
                    bool forced=false;
                    if(coverage&&depth<2) {
                        int proposed=CoverageAction(iteration,depth);
                        var known=rollout?null:node.actions[proposed].immediate;
                        if(known==null||(!known.predicted_game_over&&known.drop_success)){action=proposed;forced=true;}
                    }
                    forcedSteps.Add(forced);
                    rolloutSteps.Add(rollout);guidedSteps.Add(guided);
                    if(action<0)throw new InvalidOperationException("No legal MCTS action");
                    Edge edge=rollout?null:node.actions[action];bool expanded=edge!=null&&edge.visits==0;
                    if(expanded)expandedActions++;
                    if(edge!=null)visits.Add(new Visit {node=node,edge=edge,score=path.Score});
                    // Reward-only: the final undropped held fruit cannot change physical reward.
                    // -2 denotes a collapsed irrelevant chance (representative slot zero).
                    // At the final horizon the later NEXT is unknown and irrelevant to
                    // physical reward; no unnecessary chance sample/world is created.
                    // A learned policy consumes public NEXT at the final action: sample it honestly.
                    bool irrelevantChance=network==null && depth+2==s.mcts_max_depth && !(LearnedRolloutPolicy.Active!=null&&LearnedRolloutPolicy.Mixture>0);
                    int chance=depth+1<s.mcts_max_depth?(irrelevantChance?-2:s.mcts_common_chance?report.common_chance_samples[iteration*s.mcts_max_depth+depth]:rng.Next(slots)):-1;
                    float actionX=positions==null?(float)action/(actionCount-1):positions.x[action];
                    actions.Add(action);chances.Add(chance);if(actionXs!=null)actionXs.Add(actionX);
                    if(!open && depth+1==s.mcts_max_depth && edge!=null && edge.leaf_cached)
                    {cachedLeaf=edge;report.leaf_cache_hits++;report.skipped_physics_ticks+=edge.immediate.physics_steps;break;}
                    SuikaPhysicsSimulator.Result result=null;
                    if(s.frame_tick_slicing) {
                        using(var ticks=path.AdvanceSearchTicks(actionX,s.post_drop_steps,chance==-2?0:chance,
                            !MctsPerformance.Optimized || !rollout,
                            !MctsPerformance.Optimized || (edge!=null && edge.immediate==null),
                            !MctsPerformance.Optimized || (depth==0 && d.source_fruits==null)))
                        while(true) {
                            bool more;
                            using(MctsPerformance.Measure(rollout?"rollout_chunk":edge.transition_signature!=null?"replay_chunk":"expansion_chunk"))more=ticks.MoveNext();
                            if(!more)break;
                            if(ticks.Current!=null)result=ticks.Current;
                            yield return null;
                        }
                    } else using(MctsPerformance.Measure(rollout?"rollout_advance":edge.transition_signature!=null?"replay_advance":"expansion_advance"))
                        result=path.AdvanceSearch(actionX,s.post_drop_steps,chance==-2?0:chance,
                            !MctsPerformance.Optimized || !rollout,
                            !MctsPerformance.Optimized || (edge!=null && edge.immediate==null),
                            !MctsPerformance.Optimized || (depth==0 && d.source_fruits==null));
                    report.physics_advances++;merges+=result.merges;
                    if(edge!=null)
                    {
                        string transition;
                        using(MctsPerformance.Measure("transition_signature")) transition=JsonUtility.ToJson(new Transition {fruits=result.fruits,held=result.current_fruit,score=result.score,ticks=result.physics_steps,go=result.game_over});
                        if(open) {
                            if(localTransitions[action]==null)localTransitions[action]=transition;
                            else if(localTransitions[action]!=transition){report.prefixes_match=false;throw new InvalidOperationException("Open-loop exact state replay diverged");}
                        }
                        else if(edge.transition_signature==null)edge.transition_signature=transition;
                        else if(edge.transition_signature!=transition){report.prefixes_match=false;throw new InvalidOperationException("MCTS transition changed across public chance outcomes");}
                    }
                    if(edge!=null && edge.immediate==null)edge.immediate=TwoStepPlanner.Candidate(action,actionX,result,s);
                    if(open&&edge!=null)localImmediate[action]=edge.immediate;
                    if(depth==0)
                    {
                        if(d.source_fruits==null)d.source_fruits=result.initial_fruits;
                        if(d.candidates[action]==null)
                        {
                            d.candidates[action]=edge.immediate;
                            d.candidates[action].target_x=Mathf.Lerp(range.min_x,range.max_x,actionX);
                        }
                    }
                    if(depth+1==s.mcts_max_depth)freshLeaf=edge;
                    yield return null; // Main-thread work boundary: native APIs never run on Task.Run.
                    if(path.GameOver || depth+1==s.mcts_max_depth)break;
                    if(s.frame_tick_slicing) {
                        using(var waits=path.WaitTickFrames(s.inter_step_wait_ticks))while(waits.MoveNext())yield return null;
                    } else {
                        path.WaitTicks(s.inter_step_wait_ticks);
                        if(s.inter_step_wait_ticks>0)yield return null;
                    }
                    if(path.GameOver)break;
                    if(!rollout)
                    {
                        Node child;
                        bool newChance;
                        if(open)history+="/"+action;
                        if(open) {
                            string key=OpenNodeKey(history,path.PublicFruitKey(network==null&&depth+2==s.mcts_max_depth));
                            newChance=!sharedNodes.TryGetValue(key,out child);
                            if(newChance){child=SearchNode(nodes.Count,depth+1,s);child.public_context=path.PublicFruitKey(network==null&&depth+2==s.mcts_max_depth);child.history_key=history;nodes.Add(child);sharedNodes.Add(key,child);}
                            edge.chance[chance]=child;
                            if(edge.chance_counts==null)edge.chance_counts=new Dictionary<int,int>();
                            edge.chance_counts[chance]=edge.chance_counts.ContainsKey(chance)?edge.chance_counts[chance]+1:1;
                        } else {
                            newChance=!edge.chance.TryGetValue(chance,out child);
                            if(newChance){child=SearchNode(nodes.Count,depth+1,s);nodes.Add(child);edge.chance.Add(chance,child);}
                        }
                        if(newChance)newChanceNodes++;
                        child.arrivals++;node=child;
                        // Legacy stops at a fresh edge/chance. Optional policy grants at most
                        // one following decision action before uniformly random rollout.
                        // Chance is sampled regardless of visits/reward, never maximized.
                        rollout=AfterChanceRollout(expanded,newChance,extend,extraUsed,out chancePending);
                    }
                }
                int finalScore=path.Score+(cachedLeaf==null?0:cachedLeaf.immediate.reward);
                bool terminal=cachedLeaf==null?path.GameOver:cachedLeaf.immediate.predicted_game_over;
                float leaf;
                using(MctsPerformance.Measure("leaf_evaluation")) leaf=cachedLeaf!=null?cachedLeaf.leaf_value:network==null||terminal?0:network.Predict(path.Snapshot());
                if(!open&&freshLeaf!=null){freshLeaf.leaf_cached=true;freshLeaf.leaf_value=leaf;}
                using(MctsPerformance.Measure("backpropagation")) foreach(var visit in visits){visit.node.visits++;visit.edge.Add(finalScore-visit.score+leaf,terminal);}
                report.total_physics_ticks+=path.TotalTicks;
                if(extraDecisions>1)throw new InvalidOperationException("Extra decision quota exceeded");
                report.extra_decisions+=extraDecisions;report.expanded_actions+=expandedActions;report.new_chance_nodes+=newChanceNodes;
                iterations.Add(new IterationMetric {coverage_requested=coverage,coverage_forced_steps=forcedSteps.ToArray(),extra_decisions=extraDecisions,expanded_actions=expandedActions,new_chance_nodes=newChanceNodes,iteration=iteration,depth=actions.Count,ticks=path.TotalTicks+(cachedLeaf==null?0:cachedLeaf.immediate.physics_steps),simulated_ticks=path.TotalTicks,cached_leaf=cachedLeaf!=null,reward=finalScore-initialScore,
                    merges=merges+path.BoundaryWaitMerges+(cachedLeaf==null?0:cachedLeaf.immediate.merges),game_over=terminal,tree_node_ids=treeIds.ToArray(),public_observations=observations.ToArray(),state_signatures=stateDigests.ToArray(),rollout_steps=rolloutSteps.ToArray(),guided_steps=guidedSteps.ToArray(),actions=actions.ToArray(),chance_slots=chances.ToArray(),action_x=actionXs==null?null:actionXs.ToArray(),
                    leaf_points=leaf,total_points=finalScore-initialScore+leaf,state_digest=MctsPerformance.VerifyStates?Digest(path.StateSignature()):null,elapsed_ms=watch.Elapsed.TotalMilliseconds});
            }
            if(s.mcts_extended_budget&&!s.mcts_full_trace){var item=iterations[iterations.Count-1];item.actions=null;item.chance_slots=null;item.tree_node_ids=null;item.public_observations=null;item.state_signatures=null;item.action_x=null;item.guided_steps=null;item.coverage_forced_steps=null;item.state_digest=null;}
            report.completed_iterations++;maxIterationMs=Math.Max(maxIterationMs,watch.Elapsed.TotalMilliseconds);
            if(importance&&report.completed_iterations>=nextCheckpoint) {
                var audit=MctsImportanceControl.Assess(root,s,report.completed_iterations,importanceChecks,additions,nodes,report.importance_context,timer.Elapsed.TotalMilliseconds,report.time_limit_ms-timer.Elapsed.TotalMilliseconds,maxIterationMs);
                foreach(var it in iterations)foreach(bool isRollout in it.rollout_steps){if(isRollout)audit.rollout_actions++;else audit.tree_actions++;}
                importanceChecks.Add(audit);checkpoints.Add(audit.root);
                nextCheckpoint=Math.Min(cap,Math.Max(nextCheckpoint+1,nextCheckpoint*2));
                if(!audit.continue_search){report.budget_stop_reason=audit.reason;break;}
            }
            if(s.mcts_budget_mode=="adaptive"&&report.completed_iterations>=nextCheckpoint) {
                var checkpoint=MctsAdaptiveControl.Assess(root,s,report.completed_iterations,previousWinner,previousMean);
                MctsAdaptiveControl.GuardAdditions(checkpoint,additions,nodes,s,previousCheckpoint);previousCheckpoint=report.completed_iterations;
                checkpoints.Add(checkpoint);previousWinner=checkpoint.winner;previousMean=checkpoint.mean;
                nextCheckpoint=Math.Min(cap,Math.Max(nextCheckpoint+1,nextCheckpoint*2));
                if(checkpoint.stable){report.budget_stop_reason="adaptive_stable";break;}
            }
            report.unity_allocated_sampled_peak_bytes=Math.Max(report.unity_allocated_sampled_peak_bytes,UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong());
        }
        if(s.mcts_extended_budget&&report.completed_iterations<32)throw new InvalidOperationException("Extended MCTS minimum32 not reached; no drop; completed="+report.completed_iterations+"; elapsed_ms="+timer.Elapsed.TotalMilliseconds+"; time_limit_ms="+report.time_limit_ms+"; overrun_ms="+Math.Max(0,timer.Elapsed.TotalMilliseconds-report.time_limit_ms));
        if(report.completed_iterations==0)throw new InvalidOperationException("MCTS time limit: completed_iterations=0; no drop; elapsed_ms="+timer.Elapsed.TotalMilliseconds);
        foreach(var a in additions){var e=nodes[a.node_id].actions[a.index];a.final_visits=e.visits;a.final_revisits=Math.Max(0,e.visits-1);a.immediate_go=e.immediate!=null&&e.immediate.predicted_game_over;}
        report.budget_checkpoints=checkpoints.ToArray();report.candidate_additions=additions.ToArray();if(importance)report.importance_checkpoints=importanceChecks.ToArray();
        for(int i=0;i<d.candidates.Length;i++)
        {
            var c=d.candidates[i];if(c==null) {
                if(!flexible)throw new InvalidOperationException("MCTS did not cover every root action");
                c=d.candidates[i]=new StepPlanner.Candidate {index=i,x=root.positions==null?(float)i/(root.actions.Length-1):root.positions.x[i],success=false,excluded_reason="unvisited_time_limit"};
            }
            c.search_evaluated=true;c.search_score=(float)root.actions[i].Mean;
            // Deep terminal frequency is a logged diagnostic, not a new GO penalty.
            c.search_terminal_probability=0;
            if(c.excluded_reason==null)c.selection_score_json=c.search_score.ToString("R",System.Globalization.CultureInfo.InvariantCulture);
        }
        StepPlanner.Choose(d); // Preserves original all-GO survival fallback.
        if(!d.all_predicted_terminal)
        {
            int best=-1;
            for(int i=0;i<d.candidates.Length;i++)
            {
                var c=d.candidates[i];if(!c.success||!c.drop_success||c.predicted_game_over)continue;
                if(best<0 || root.actions[i].visits>root.actions[best].visits || (root.actions[i].visits==root.actions[best].visits&&root.actions[i].Mean>root.actions[best].Mean+.001))best=i;
            }
            if(best>=0){d.selected_index=best;d.selected_x=d.candidates[best].x;}
        }
        report.source_unchanged=frozenRoot!=null?source==frozenRoot.StateSignature() : (source==SuikaPhysicsSimulator.LiveSignature(player)&&liveRandom.Equals(UnityEngine.Random.state)&&initialScore==ScoreManager.Instance.GetScore());
        if(!report.source_unchanged)throw new InvalidOperationException("MCTS mutated live source/score/RNG");
        var metrics=new List<NodeMetric>();
        foreach(var n in nodes)
        {
            var rows=new ActionMetric[n.actions.Length];
            for(int i=0;i<rows.Length;i++)
            {
                var e=n.actions[i];var keys=new List<int>(e.chance.Keys);keys.Sort();var ids=new List<int>();var counts=new List<int>();
                foreach(int key in keys){ids.Add(e.chance[key].id);counts.Add(open?e.chance_counts[key]:e.chance[key].arrivals);}
                rows[i]=new ActionMetric {index=i,x=n.positions==null?(float)i/(rows.Length-1):n.positions.x[i],position_source=n.positions==null?null:n.positions.sources[i],visits=e.visits,mean_points=e.Mean,
                    sd_points=e.visits==0?0:Math.Sqrt(Math.Max(0,e.sumSquares/e.visits-e.Mean*e.Mean)),min_points=e.visits==0?0:e.min,max_points=e.visits==0?0:e.max,
                    immediate_go=e.immediate!=null&&e.immediate.predicted_game_over,drop_success=e.immediate!=null&&e.immediate.drop_success,
                    terminal_returns=e.terminal_returns,chance_slots=keys.ToArray(),chance_node_ids=ids.ToArray(),chance_visits=counts.ToArray()};
            }
            metrics.Add(new NodeMetric {unvisited_order=n.unvisited_order,id=n.id,depth=n.depth,visits=n.visits,arrivals=n.arrivals,distinct_states=n.state_signatures==null?0:n.state_signatures.Count,public_context=n.public_context,history_key=n.history_key,actions=rows});
        }
        report.nodes=metrics.ToArray();report.iterations=iterations.ToArray();if(s.mcts_extended_budget){report.depth_metrics=MctsDepthControl.Levels(report);foreach(var it in iterations){report.search_go_samples+=it.game_over?1:0;report.max_reached_depth=Math.Max(report.max_reached_depth,it.depth);}if(!s.mcts_full_trace){report.compact_report=true;report.iterations=new IterationMetric[0];report.nodes=new[]{report.nodes[0]};}}report.decision_nodes=nodes.Count;
        report.lifetime_end=PredictionLifecycle.Read(false);
        report.managed_end_bytes=GC.GetTotalMemory(false);report.elapsed_ms=timer.Elapsed.TotalMilliseconds;report.time_overrun_ms=flexible?Math.Max(0,report.elapsed_ms-report.time_limit_ms):0;report.mcts_search_ms=report.elapsed_ms-(report.refinement==null?0:report.refinement.total_ms);
        d.same_source_verified=report.source_unchanged&&report.prefixes_match;d.evaluated_count=d.candidates.Length;if(flexible){d.evaluated_count=0;foreach(var candidate in d.candidates)if(candidate.success)d.evaluated_count++;}d.elapsed_ms=report.elapsed_ms;yield return d;
    }
}
