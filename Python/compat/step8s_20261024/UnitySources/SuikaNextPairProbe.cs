using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEngine;

// Explicit diagnostic only; no production planner, Scene, or rules are modified.
public sealed class SuikaNextPairProbe : MonoBehaviour {
    [Serializable] class Config {public string output;public string[] fixtures;}
    [Serializable] public class Late {public int target_post_ticks,actual_wait_ticks,reward,merges;public bool game_over;}
    [Serializable] public class LateSeries {public Late[] samples;}
    [Serializable] public class Pair {
        public int first_index,second_index,total_reward,merges,ticks;
        public StepPlanner.Candidate first,second;public HeuristicEvaluator.Breakdown final_evaluation;
        public bool prefix_match,game_over;public double rebuild_ms,first_ms,second_ms,evaluate_ms,dispose_ms;
    }
    [Serializable] public class Row {
        public string fixture,error;public int held_type,next_type,initial_score;
        public StepPlanner.Candidate[] one;public LateSeries[] delayed;public Pair[] pairs;
        public bool source_unchanged,root_unchanged,random_unchanged,unknown_next_invariant;
        public double initial_build_ms,one_ms,pair_ms,late_ms,mcts_ms,measured_total_ms;
        public int one_ticks,pair_ticks,late_ticks,pair_advances;
        public long managed_start,managed_end,unity_start,unity_sampled_peak;
        public MctsPlanner.Report baseline;public float baseline_selected_x;
    }
    [Serializable] class Comparable {public UDPCommunicatorUnity.BoardFruit[] fruits;public int score,merges,ticks;public bool go;public float applied_x;}
    static string config;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaNextPairProbe");if(i<0)return;
        config=args[i+1];new GameObject("Public NEXT pair diagnostic").AddComponent<SuikaNextPairProbe>();
    }
    static string Physical(SuikaPhysicsSimulator.Result r) {return JsonUtility.ToJson(new Comparable {fruits=r.fruits,score=r.score,merges=r.merges,ticks=r.physics_steps,go=r.game_over,applied_x=r.applied_x});}
    static Row Run(string fixture,PlayerController player,GameManager manager,Collider2D floor) {
        var row=new Row {fixture=fixture,one=new StepPlanner.Candidate[5],delayed=new LateSeries[5],managed_start=GC.GetTotalMemory(false),unity_start=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()};
        var all=Stopwatch.StartNew();var watch=Stopwatch.StartNew();
        string live=SuikaPhysicsSimulator.LiveSignature(player);int liveScore=ScoreManager.Instance.GetScore();var random=UnityEngine.Random.state;
        using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,floor)) {
            row.initial_build_ms=watch.Elapsed.TotalMilliseconds;var snapshot=root.Snapshot();row.held_type=snapshot.current_fruit.type;row.next_type=snapshot.next_fruit_type;row.initial_score=root.Score;
            string signature=root.StateSignature();var prefixes=new string[5];var settings=new PlanningSettings {ai_mode="mcts",candidate_count=5,mcts_iterations=32,mcts_max_depth=4,mcts_common_chance=true};
            // Standalone one-drop evaluation. Waiting extensions are measured separately.
            for(int i=0;i<5;i++) {
                watch.Restart();var path=root.Fork(manager);
                try {
                    var result=path.Advance(i/4f,25,0);row.one[i]=TwoStepPlanner.Candidate(i,i/4f,result,settings);row.one_ticks+=result.physics_steps;
                    if(!path.GameOver && path.Snapshot().current_fruit.type!=row.next_type)throw new Exception("Second held fruit is not public NEXT");
                    prefixes[i]=path.StateSignature();row.one_ms+=watch.Elapsed.TotalMilliseconds;
                    watch.Restart();var late=new List<Late>();int previous=25;int rewardStart=path.Score,mergeStart=0;
                    foreach(int target in new[]{50,100,150}) {
                        path.WaitTicks(target-previous);previous=target;
                        late.Add(new Late {target_post_ticks=target,actual_wait_ticks=path.BoundaryWaitTicks,reward=path.Score-rewardStart,merges=path.BoundaryWaitMerges-mergeStart,game_over=path.GameOver});
                    }
                    row.late_ticks+=path.BoundaryWaitTicks;row.delayed[i]=new LateSeries {samples=late.ToArray()};row.late_ms+=watch.Elapsed.TotalMilliseconds;
                }finally {watch.Restart();path.Dispose();row.one_ms+=watch.Elapsed.TotalMilliseconds;}
            }
            var pairs=new List<Pair>();watch.Restart();var pairClock=Stopwatch.StartNew();
            for(int i=0;i<5;i++)for(int j=0;j<5;j++) {
                var p=new Pair {first_index=i,second_index=j};watch.Restart();var path=root.Fork(manager);p.rebuild_ms=watch.Elapsed.TotalMilliseconds;
                try {
                    watch.Restart();var first=path.Advance(i/4f,25,0);p.first_ms=watch.Elapsed.TotalMilliseconds;row.pair_advances++;
                    p.first=TwoStepPlanner.Candidate(i,i/4f,first,settings);p.prefix_match=prefixes[i]==path.StateSignature();
                    if(!p.prefix_match)throw new Exception("First-move replay divergence");
                    if(!path.GameOver) {
                        if(path.Snapshot().current_fruit.type!=row.next_type)throw new Exception("Nonpublic second fruit");
                        // C is deliberately not inspected. B action is fixed, not conditioned on C.
                        watch.Restart();var second=path.Advance(j/4f,25,-1);p.second_ms=watch.Elapsed.TotalMilliseconds;row.pair_advances++;
                        p.second=TwoStepPlanner.Candidate(j,j/4f,second,settings);
                    }
                    watch.Restart();p.total_reward=path.Score-root.Score;p.merges=first.merges+(p.second==null?0:p.second.merges);p.ticks=path.TotalTicks;p.game_over=path.GameOver;
                    p.final_evaluation=HeuristicEvaluator.Evaluate(path.EvaluationFeatures(),p.total_reward,settings);
                    if(p.total_reward!=p.first.reward+(p.second==null?0:p.second.reward)||p.ticks!=p.first.physics_steps+(p.second==null?0:p.second.physics_steps))throw new Exception("Pair score/tick conservation failure");
                    p.evaluate_ms=watch.Elapsed.TotalMilliseconds;
                }finally {watch.Restart();path.Dispose();p.dispose_ms=watch.Elapsed.TotalMilliseconds;}
                row.pair_ticks+=p.ticks;pairs.Add(p);row.unity_sampled_peak=Math.Max(row.unity_sampled_peak,UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong());
            }
            row.pair_ms=pairClock.Elapsed.TotalMilliseconds;row.pairs=pairs.ToArray();
            // A/B-only physical outcome must not depend on the placeholder for unobserved C.
            string check=null;row.unknown_next_invariant=true;
            foreach(int slot in new[]{0,player.fruits.Length-1})using(var path=root.Fork(manager)) {
                var first=path.Advance(.5f,25,slot);var key=Physical(first);
                if(!path.GameOver)key+="/"+Physical(path.Advance(0,25,-1));
                if(check==null)check=key;else row.unknown_next_invariant=check==key;
            }
            if(!row.unknown_next_invariant)throw new Exception("Hidden C changed two-drop outcome");
            watch.Restart();StepPlanner.Decision d=null;
            using(var work=MctsPlanner.PlanFrames(player,manager,floor,settings,root))while(work.MoveNext())if(work.Current!=null)d=work.Current;
            row.mcts_ms=watch.Elapsed.TotalMilliseconds;row.baseline=d.mcts;row.baseline_selected_x=d.selected_x;
            row.root_unchanged=signature==root.StateSignature();
        }
        row.source_unchanged=live==SuikaPhysicsSimulator.LiveSignature(player)&&liveScore==ScoreManager.Instance.GetScore();row.random_unchanged=random.Equals(UnityEngine.Random.state);
        if(!row.root_unchanged||!row.source_unchanged||!row.random_unchanged)throw new Exception("Diagnostic changed live/root/RNG");
        row.measured_total_ms=all.Elapsed.TotalMilliseconds;row.managed_end=GC.GetTotalMemory(false);return row;
    }
    IEnumerator Start() {
        yield return null;yield return null;
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));var player=FindObjectOfType<PlayerController>();var manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();int failures=0;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(string fixture in c.fixtures) {
            SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),fixture);
            Row row;
            try {row=Run(fixture,player,manager,udp.planningFloor);}catch(Exception e){row=new Row {fixture=fixture,error=e.ToString()};failures++;}
            log.WriteLine(JsonUtility.ToJson(row));log.Flush();yield return null;yield return null;
        }
        Application.Quit(failures==0?0:1);
    }
}
