using System;
using System.Collections;
using System.IO;
using UnityEngine;
// Explicit diagnostic only: compares identical frozen roots without changing the live game.
public sealed class SuikaPhysicsThreadProbe:MonoBehaviour {
    [Serializable] class Spec {public int iterations=32,depth=4;}
    [Serializable] class Config {public string output;public string[] fixtures;public Spec[] specs;public int repeats=3;public bool verify=true,profile=false;}
    [Serializable] class Row {public string fixture,error,evt="search";public bool threaded,warmup,source_unchanged,equal,actual_multithreading,actual_sorting;public int repeat,iterations,depth;public float selected_x;public double elapsed_ms;public MctsPlanner.Report report;public PredictionLifecycle.Sample lifetime;}
    [Serializable] class Quality {public int selected;public StepPlanner.Candidate[] candidates;public MctsPlanner.NodeMetric[] nodes;public MctsPlanner.IterationMetric[] iterations;}
    static string config;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaPhysicsThreadProbe");if(i>=0){config=a[i+1];new GameObject("Isolated physics thread comparison").AddComponent<SuikaPhysicsThreadProbe>();}}
    static string Signature(StepPlanner.Decision d){foreach(var c in d.candidates)c.elapsed_ms=0;foreach(var x in d.mcts.iterations)x.elapsed_ms=0;return JsonUtility.ToJson(new Quality {selected=d.selected_index,candidates=d.candidates,nodes=d.mcts.nodes,iterations=d.mcts.iterations});}
    IEnumerator Start(){yield return null;yield return null;var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));if(c.repeats<1||c.repeats>5)throw new ArgumentException("Bounded probe");
        var originalJobs=Physics2D.jobOptions;var player=FindObjectOfType<PlayerController>();var manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(string fixture in c.fixtures){
            SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),fixture);
            using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor)){
                string initial=root.StateSignature();
                foreach(var spec in c.specs)for(int repeat=-1;repeat<c.repeats;repeat++){
                    string[] signatures=new string[2];string error=null;
                    for(int order=0;order<2;order++){
                        bool threaded=(order+Math.Max(0,repeat))%2==1;var row=new Row {fixture=fixture,threaded=threaded,warmup=repeat<0,repeat=repeat,iterations=spec.iterations,depth=spec.depth};
                        try{var jobs=originalJobs;jobs.useMultithreading=threaded;jobs.useConsistencySorting=threaded;Physics2D.jobOptions=jobs;row.actual_multithreading=Physics2D.jobOptions.useMultithreading;row.actual_sorting=Physics2D.jobOptions.useConsistencySorting;MctsPerformance.ExactOptimizations=true;MctsPerformance.VerifyStates=c.verify;MctsPerformance.SuppressProfiler=true;MctsPerformance.Current=c.profile?new MctsPerformance():null;
                            var s=new PlanningSettings {ai_mode="mcts",mcts_iterations=spec.iterations,mcts_max_iterations=spec.iterations,mcts_max_depth=spec.depth,mcts_seed=8191,mcts_extended_budget=spec.depth>8||spec.iterations>256,mcts_full_trace=true,mcts_time_limit_seconds=120};
                            StepPlanner.Decision d=null;var watch=System.Diagnostics.Stopwatch.StartNew();using(var work=MctsPlanner.PlanFrames(player,manager,udp.planningFloor,s,root))while(work.MoveNext())if(work.Current!=null)d=work.Current;
                            row.elapsed_ms=watch.Elapsed.TotalMilliseconds;row.selected_x=d.selected_x;row.report=d.mcts;if(MctsPerformance.Current!=null)row.report.profile=MctsPerformance.Current.Results();row.source_unchanged=root.StateSignature()==initial;row.lifetime=PredictionLifecycle.Read();signatures[threaded?1:0]=Signature(d);
                            if(!row.source_unchanged||d.mcts.completed_iterations!=spec.iterations)throw new Exception("Root changed or incomplete search");
                        }catch(Exception e){error=row.error=e.ToString();}finally{MctsPerformance.Current=null;Physics2D.jobOptions=originalJobs;}
                        log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                        if(error!=null)break;
                    }
                    bool equal=error==null&&signatures[0]==signatures[1];log.WriteLine(JsonUtility.ToJson(new Row {evt="pair",fixture=fixture,iterations=spec.iterations,depth=spec.depth,repeat=repeat,warmup=repeat<0,equal=equal,error=error}));log.Flush();
                    if(error!=null){Application.Quit(2);yield break;} // Numerical mismatches are recorded, never adopted as an optimization.
                    yield return null;
                }
            }
            yield return null;
        }
        MctsPerformance.ExactOptimizations=true;MctsPerformance.VerifyStates=false;MctsPerformance.SuppressProfiler=false;Application.Quit(0);
    }
}
