using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
// Owned bounded fixed-root comparison; never installs in ordinary Players.
public sealed class SuikaCandidateProbe : MonoBehaviour {
    [Serializable] class Search {public string policy="grid",rollout_policy="random",tree_policy="chance",expansion_policy="legacy",action_order_policy="index";public int seed=8191,pair_coverage_iterations;public float rollout_random_probability=.5f;public bool common_chance;public int candidates=5,iterations=32;}
    [Serializable] class Config {public string output;public string[] fixtures,policies;public bool scan,exhaustive,information_tests;public Search[] searches;}
    static Search[] Searches(Config c) {
        if(c.searches!=null)return c.searches;
        var searches=new List<Search>();foreach(var p in c.policies)searches.Add(new Search {policy=p});return searches.ToArray();
    }
    [Serializable] class Row {public string fixture,policy,error;public ValueSnapshot initial;public StepPlanner.Decision decision;public MctsPlanner.Report report;public double wall_ms;public int gc0;public bool root_unchanged;public SuikaPhysicsSimulator.Result scan,continuation;public int two_step_reward;public float scan_x;public PairReport exhaustive;public double initial_build_ms;public InfoCase[] information_cases;}
    static string config;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaCandidateProbe");if(i<0)return;
        config=a[i+1];new GameObject("Candidate geometry probe").AddComponent<SuikaCandidateProbe>();
    }
    static void GeometryTests() {
        int[] rank,parents;
        var fine=CoarseToFineCandidates.Refine(new[]{0f,3f,2f,1f,0f},new[]{true,true,true,true,true},new float[5],new float[4],out rank,out parents);
        if(rank[0]!=1||rank[1]!=2||fine.Length!=2||fine[0]==fine[1]||fine[0]<0||fine[1]>1||parents[0]==parents[1])throw new Exception("Coarse refinement ranking/diversity failed");
        var all=new HashSet<float>{0,.25f,.5f,.75f,1};foreach(float x in fine)all.Add(x);
        if(all.Count!=7)throw new Exception("Coarse anchors lost");
        CoarseToFineCandidates.Refine(new[]{0f,100f,2f,1f,0f},new[]{true,false,true,true,true},new float[5],new float[4],out rank,out parents);
        if(rank[0]!=2)throw new Exception("Unsafe coarse parent preferred");
        Debug.Log("COARSE ROOT CHECKS OK");
        for(int seed=0;seed<20;seed++) {
            var order=MctsPlanner.ShuffledOrder(5,seed,0);var replay=MctsPlanner.ShuffledOrder(5,seed,0);
            var n=new MctsPlanner.Node(5,0,0);n.unvisited_order=order;var seen=new HashSet<int>();
            for(int j=0;j<5;j++) {
                if(order[j]!=replay[j]||!seen.Add(order[j])||MctsPlanner.Select(n,1.414,55)!=order[j])throw new Exception("Shuffle coverage/reproducibility failed");
                n.actions[order[j]].Add(10+j,false);n.visits++;
            }
            var legacy=new MctsPlanner.Node(5,0,0);legacy.visits=n.visits;
            for(int j=0;j<5;j++)legacy.actions[j]=n.actions[j];
            if(MctsPlanner.Select(n,1.414,55)!=MctsPlanner.Select(legacy,1.414,55))throw new Exception("Visited UCT changed");
        }
        var blocked=new MctsPlanner.Node(5,0,0);blocked.unvisited_order=MctsPlanner.ShuffledOrder(5,83,0);
        int first=blocked.unvisited_order[0];blocked.actions[first].immediate=new StepPlanner.Candidate {predicted_game_over=true,drop_success=true};
        if(MctsPlanner.Select(blocked,1.414,55)==first)throw new Exception("Shuffled GO candidate selected");
        if(String.Join(",",MctsPlanner.ShuffledOrder(9,8191,0))==String.Join(",",MctsPlanner.ShuffledOrder(9,8191,1)))throw new Exception("Node streams not distinct");
        Debug.Log("SHUFFLE ORDER CHECKS OK: 20 seeds, permutation coverage, UCT unchanged, GO exclusion, per-node stream");
        var range=new PlayerController.DropRange {valid=true,min_x=0,max_x=10,left_wall_inner=-1,right_wall_inner=11,fruit_left_extent=1,fruit_right_extent=1};
        var shapes=new List<DropCandidateGenerator.Shape> {
            new DropCandidateGenerator.Shape {type=0,center_x=2,min_x=1.5f,max_x=2.5f,top_y=2},
            new DropCandidateGenerator.Shape {type=0,center_x=8,min_x=7.5f,max_x=8.5f,top_y=2}};
        var set=DropCandidateGenerator.Generate(range,0,5,shapes);
        if(set.x.Length!=5 || set.x[0]!=0 || set.x[2]!=.5f || set.x[4]!=1 || set.x[1]!=.2f || set.x[3]!=.8f)throw new Exception("Candidate anchors or same-type alignment");
        shapes.Reverse();var reverse=DropCandidateGenerator.Generate(range,0,5,shapes);
        for(int i=0;i<5;i++)if(set.x[i]!=reverse.x[i] || set.x[i]<0 || set.x[i]>1 || (i>0&&set.x[i]<=set.x[i-1]))throw new Exception("Candidate order/safety/permutation");
        var empty=DropCandidateGenerator.Generate(range,0,5,new List<DropCandidateGenerator.Shape>());
        for(int i=0;i<5;i++)if(empty.x[i]!=i/4f)throw new Exception("Empty grid fallback");
        shapes.Add(new DropCandidateGenerator.Shape {type=1,center_x=2,min_x=1,max_x=3,top_y=3});
        var covered=DropCandidateGenerator.Generate(range,0,5,shapes);
        if(covered.sources[1]=="visible-same-type")throw new Exception("Blocked same-type proposal");
        var xs=new[]{0f,.25f,.5f,.75f,1f};var geometry=new List<DropCandidateGenerator.Shape> {
            new DropCandidateGenerator.Shape {type=0,center_x=5,min_x=4.5f,max_x=5.5f,top_y=2}};
        var values=SuikaPhysicsSimulator.RolloutGeometryScores(xs,range,0,.5f,.5f,0,0,0,10,geometry);
        if(values[2]!=1 || values[0]!=0)throw new Exception("Rollout same-type alignment");
        geometry.Add(new DropCandidateGenerator.Shape {type=1,center_x=5,min_x=4,max_x=6,top_y=3});
        values=SuikaPhysicsSimulator.RolloutGeometryScores(xs,range,0,.5f,.5f,0,0,0,10,geometry);
        if(values[2]!=0)throw new Exception("Rollout covered matching fruit must not attract");
        geometry[1]=new DropCandidateGenerator.Shape {type=1,center_x=5,min_x=4,max_x=6,top_y=10};
        values=SuikaPhysicsSimulator.RolloutGeometryScores(xs,range,0,.5f,.5f,0,0,0,10,geometry);
        if(values[2]!=-1)throw new Exception("Rollout near-line geometry risk");
        geometry.Reverse();var reversed=SuikaPhysicsSimulator.RolloutGeometryScores(xs,range,0,.5f,.5f,0,0,0,10,geometry);
        for(int i=0;i<5;i++)if(values[i]!=reversed[i])throw new Exception("Rollout order invariance");
        Debug.Log("ROLLOUT GEOMETRY CHECKS OK");
        bool pending;
        if(!MctsPlanner.AfterChanceRollout(false,true,false,false,out pending)||pending)throw new Exception("Legacy chance rollout changed");
        if(MctsPlanner.AfterChanceRollout(true,true,true,false,out pending)||!pending)throw new Exception("First chance must permit one extra action");
        if(!MctsPlanner.AfterChanceRollout(true,true,true,true,out pending)||pending)throw new Exception("Extra action quota failed");
        if(MctsPlanner.AfterChanceRollout(false,false,true,false,out pending)||pending)throw new Exception("Existing tree selection changed");
        Debug.Log("EXPANSION POLICY CHECKS OK");
        Debug.Log("CANDIDATE GEOMETRY CHECKS OK");
    }
    [Serializable] public class PairOutcome {
        public int first_index,second_index,first_reward,second_reward,total_reward,merges,ticks,first_ticks,second_ticks;
        public float first_x,second_x,first_applied_x,second_applied_x,danger,height,terminal_excess;
        public bool first_go,game_over,first_drop,second_drop,prefix_match;
        public double rebuild_ms,first_ms,second_ms,evaluate_ms,dispose_schedule_ms;
    }
    [Serializable] public class PairReport {
        public string selection="diagnostic: safe successful paths first, then two-drop reward, ties lexicographic; all GO least excess then latest termination";
        public string limitation="cold root contacts; live render GO timing not cloned; every pair replays first move in a fresh native root";
        public int paths,advances,physics_ticks,selected_path=-1,gc0;
        public bool root_unchanged,live_unchanged,random_unchanged;
        public double elapsed_ms,rebuild_ms,first_ms,second_ms,evaluate_ms,dispose_schedule_ms;
        public long managed_start_bytes,managed_end_bytes,unity_start_bytes,unity_sampled_peak_bytes;
        public PairOutcome[] outcomes;
    }
    public static bool BetterPair(PairOutcome a,PairOutcome b) {
        if(b==null)return true;
        bool safeA=!a.game_over&&a.first_drop&&a.second_drop,safeB=!b.game_over&&b.first_drop&&b.second_drop;
        if(safeA!=safeB)return safeA;
        if(!safeA) {if(a.terminal_excess!=b.terminal_excess)return a.terminal_excess<b.terminal_excess;if(a.ticks!=b.ticks)return a.ticks>b.ticks;}
        return a.total_reward>b.total_reward;
    }
    static PairReport EnumeratePairs(SuikaPhysicsSimulator.PathSession root,GameManager manager,PlayerController player) {
        var report=new PairReport {managed_start_bytes=GC.GetTotalMemory(false),unity_start_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()};
        report.unity_sampled_peak_bytes=report.unity_start_bytes;
        var timer=System.Diagnostics.Stopwatch.StartNew();int gc=GC.CollectionCount(0);
        var rows=new List<PairOutcome>();var prefixes=new Dictionary<int,string>();PairOutcome best=null;
        string rootSignature=root.StateSignature(),live=SuikaPhysicsSimulator.LiveSignature(player);var random=UnityEngine.Random.state;int liveScore=ScoreManager.Instance.GetScore();
        for(int i=0;i<9;i++)for(int j=0;j<9;j++) {
            var row=new PairOutcome {first_index=i,second_index=j,first_x=i/8f,second_x=j/8f};
            var watch=System.Diagnostics.Stopwatch.StartNew();var path=root.Fork(manager);row.rebuild_ms=watch.Elapsed.TotalMilliseconds;
            try {
                watch.Restart();var first=path.Advance(row.first_x,25,0);row.first_ms=watch.Elapsed.TotalMilliseconds;report.advances++;
                row.first_reward=first.reward;row.first_ticks=first.physics_steps;row.first_go=first.game_over;row.first_drop=first.drop_success;row.first_applied_x=first.applied_x;
                string signature=path.StateSignature();if(!prefixes.ContainsKey(i))prefixes.Add(i,signature);
                row.prefix_match=prefixes[i]==signature;if(!row.prefix_match)throw new Exception("Pair prefix replay diverged");
                SuikaPhysicsSimulator.Result second=null;
                if(!path.GameOver) {watch.Restart();second=path.Advance(row.second_x,25,-1);row.second_ms=watch.Elapsed.TotalMilliseconds;report.advances++;}
                watch.Restart();row.second_reward=second==null?0:second.reward;row.second_ticks=second==null?0:second.physics_steps;
                row.second_drop=second!=null&&second.drop_success;row.second_applied_x=second==null?0:second.applied_x;
                row.total_reward=path.Score-root.Score;row.merges=first.merges+(second==null?0:second.merges);row.ticks=path.TotalTicks;row.game_over=path.GameOver;
                var evaluation=HeuristicEvaluator.Evaluate(path.EvaluationFeatures(),0,new PlanningSettings());
                row.danger=evaluation.danger;row.height=evaluation.height;row.terminal_excess=evaluation.terminal_excess;
                if(row.total_reward!=row.first_reward+row.second_reward)throw new Exception("Pair rewards not conserved");
                if(BetterPair(row,best)){best=row;report.selected_path=rows.Count;}
                row.evaluate_ms=watch.Elapsed.TotalMilliseconds;
            } finally {watch.Restart();path.Dispose();row.dispose_schedule_ms=watch.Elapsed.TotalMilliseconds;}
            rows.Add(row);report.physics_ticks+=row.ticks;report.rebuild_ms+=row.rebuild_ms;report.first_ms+=row.first_ms;report.second_ms+=row.second_ms;report.evaluate_ms+=row.evaluate_ms;report.dispose_schedule_ms+=row.dispose_schedule_ms;
            report.unity_sampled_peak_bytes=Math.Max(report.unity_sampled_peak_bytes,UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong());
        }
        report.root_unchanged=rootSignature==root.StateSignature();report.random_unchanged=random.Equals(UnityEngine.Random.state);
        report.live_unchanged=live==SuikaPhysicsSimulator.LiveSignature(player)&&liveScore==ScoreManager.Instance.GetScore();
        if(!report.root_unchanged||!report.live_unchanged||!report.random_unchanged)throw new Exception("Pair scan changed source");
        if(rows.Count!=81)throw new Exception("Incomplete pair scan");
        report.outcomes=rows.ToArray();report.paths=rows.Count;report.gc0=GC.CollectionCount(0)-gc;
        report.managed_end_bytes=GC.GetTotalMemory(false);report.elapsed_ms=timer.Elapsed.TotalMilliseconds;return report;
    }
    [Serializable] public class InfoCase {public int chance_slot;public string[] public_keys,state_signatures;public int[] rewards;public bool game_over;public string shared_key,final_state_signature;}
    static InfoCase[] InformationTests(SuikaPhysicsSimulator.PathSession root,GameManager manager) {
        // Same action history, different publicly observed fruit => different decisions.
        string k=MctsPlanner.OpenNodeKey("/2","1:0");
        if(k==MctsPlanner.OpenNodeKey("/2","4:0")||k==MctsPlanner.OpenNodeKey("/2","1:4"))throw new Exception("Observed held/NEXT collapsed");
        var one=new MctsPlanner.Node(5,0,1);var two=new MctsPlanner.Node(5,1,1);
        for(int i=0;i<5;i++){one.actions[i].Add(i==0?50:0,false);two.actions[i].Add(i==4?50:0,false);}one.visits=two.visits=5;
        if(MctsPlanner.Select(one,0,55)!=0||MctsPlanner.Select(two,0,55)!=4)throw new Exception("Public contexts cannot adapt action");
        // Rebind identical action statistics to different physical states. GO must not leak.
        var localA=MctsPlanner.BindOpenState(one,"board-A",5);
        localA[0]=new StepPlanner.Candidate {success=true,drop_success=true,predicted_game_over=true};
        MctsPlanner.BindOpenState(one,"board-A",5);if(MctsPlanner.Select(one,0,55)==0)throw new Exception("State-local GO ignored");
        MctsPlanner.BindOpenState(one,"board-B",5);if(MctsPlanner.Select(one,0,55)!=0)throw new Exception("Other-state GO leaked");
        MctsPlanner.BindOpenState(one,"board-A",5);if(MctsPlanner.Select(one,0,55)==0)throw new Exception("Known-state GO was lost");
        var cases=new List<InfoCase>();
        foreach(int slot in new[]{0,4})using(var path=root.Fork(manager)) {
            var keys=new List<string>();var signatures=new List<string>();var rewards=new List<int>();
            foreach(float x in new[]{.5f,0f,.5f}) {
                if(path.GameOver)break;
                keys.Add(path.PublicFruitKey());signatures.Add(path.StateSignature());
                int index=rewards.Count;var result=path.Advance(x,25,index==0?slot:index==1?1:0);rewards.Add(result.reward);
            }
            cases.Add(new InfoCase {chance_slot=slot,public_keys=keys.ToArray(),state_signatures=signatures.ToArray(),rewards=rewards.ToArray(),game_over=path.GameOver,
                final_state_signature=path.StateSignature(),shared_key=path.GameOver?null:MctsPlanner.OpenNodeKey("/2/0/2",path.PublicFruitKey(true))});
        }
        if(root.Snapshot().fruits.Length==0) {
            if(cases[0].game_over||cases[1].game_over||cases[0].public_keys[1]==cases[1].public_keys[1]||cases[0].public_keys[2]==cases[1].public_keys[2]||cases[0].shared_key!=cases[1].shared_key)
                throw new Exception("Public sequence or open-loop merging test failed");
            if(cases[0].final_state_signature==cases[1].final_state_signature)throw new Exception("Chance did not create distinct physical states");
        }
        Debug.Log("OPEN LOOP INFORMATION CHECKS OK");return cases.ToArray();
    }
    IEnumerator Start() {
        yield return null;yield return null;
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));var p=FindObjectOfType<PlayerController>();var g=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();int failures=0;
        var generator=typeof(SuikaCandidateProbe).Assembly.GetType("DropCandidateGenerator");
        if(generator!=null)GeometryTests();
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))
        foreach(string fixture in c.fixtures) {
            SuikaRuntimeProbe.Instance.LoadFixture(p,g,Guid.NewGuid().ToString("N"),fixture);
            var buildWatch=System.Diagnostics.Stopwatch.StartNew();
            using(var root=new SuikaPhysicsSimulator.PathSession(p,g,udp.planningFloor)) {
                double buildMs=buildWatch.Elapsed.TotalMilliseconds;
                string signature=root.StateSignature();var initial=root.Snapshot();
                foreach(var search in Searches(c)) {
                    string policy=search.policy;
                    var row=new Row {fixture=fixture,policy=policy,initial=initial};int gc=GC.CollectionCount(0);var sw=System.Diagnostics.Stopwatch.StartNew();
                    try {
                        var settings=new PlanningSettings {ai_mode="mcts",candidate_count=search.candidates,mcts_iterations=search.iterations,mcts_max_depth=4,mcts_seed=search.seed,pair_coverage_iterations=search.pair_coverage_iterations,action_order_policy=search.action_order_policy,expansion_policy=search.expansion_policy,tree_policy=search.tree_policy,rollout_policy=search.rollout_policy,rollout_random_probability=search.rollout_random_probability,mcts_common_chance=search.common_chance};
                        var field=typeof(PlanningSettings).GetField("candidate_policy");
                        if(field!=null)field.SetValue(settings,policy);else if(policy!="grid")throw new Exception("Policy unavailable");
                        MctsPerformance.VerifyStates=true;
                        using(var work=MctsPlanner.PlanFrames(p,g,root.LocalFloor,settings,root))while(work.MoveNext())if(work.Current!=null)row.decision=work.Current;
                        row.report=row.decision.mcts;row.root_unchanged=signature==root.StateSignature();if(!row.root_unchanged)throw new Exception("Changed root");
                    }catch(Exception e){row.error=e.ToString();failures++;}
                    row.wall_ms=sw.Elapsed.TotalMilliseconds;row.gc0=GC.CollectionCount(0)-gc;log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                }
                if(c.information_tests) {
                    var row=new Row {fixture=fixture,policy="information-tests",initial=initial};
                    try {row.information_cases=InformationTests(root,g);row.root_unchanged=signature==root.StateSignature();if(!row.root_unchanged)throw new Exception("Info tests changed root");}
                    catch(Exception e){row.error=e.ToString();failures++;}
                    log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                }
                if(c.exhaustive) {
                    var row=new Row {fixture=fixture,policy="exhaustive-nine",initial=initial,initial_build_ms=buildMs};
                    try {row.exhaustive=EnumeratePairs(root,g,p);row.root_unchanged=signature==root.StateSignature();if(!row.root_unchanged)throw new Exception("Exhaustive changed root");}
                    catch(Exception e){row.error=e.ToString();failures++;}
                    log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                }
                if(c.scan) {
                    var positions=new List<float>();for(int i=0;i<9;i++)positions.Add(i/8f);
                    var range=p.GetDropRange();int added=0;
                    var fruit=new List<UDPCommunicatorUnity.BoardFruit>(initial.fruits);fruit.Sort((a,b)=>b.y.CompareTo(a.y));
                    foreach(var f in fruit)if(f.type==initial.current_fruit.type && added<4) {float x=Mathf.Clamp01((f.x-range.min_x)/(range.max_x-range.min_x));if(!positions.Contains(x)){positions.Add(x);added++;}}
                    foreach(float x in positions)using(var path=root.Fork(g)) {
                        var row=new Row {fixture=fixture,policy="diagnostic_scan",initial=initial,scan_x=x};
                        try {
                            // Only A and the displayed B are dropped. Slot zero is an
                            // irrelevant hypothetical C, never read from the live RNG.
                            row.scan=path.Advance(x,25,0);
                            if(!path.GameOver)row.continuation=path.Advance(x,25,-1);
                            row.two_step_reward=path.Score-root.Score;row.root_unchanged=signature==root.StateSignature();
                        }
                        catch(Exception e){row.error=e.ToString();failures++;}
                        log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                    }
                }
            }
            MctsPerformance.VerifyStates=false;yield return null;yield return null;yield return null;
        }
        Application.Quit(failures==0?0:1);
    }
}
