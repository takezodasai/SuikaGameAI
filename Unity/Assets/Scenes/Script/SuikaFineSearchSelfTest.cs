using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Bounded fixed-root parity/cost test, installed only by explicit Player argument.
public sealed class SuikaFineSearchSelfTest : MonoBehaviour
{
    [Serializable] class Config {public string output;public string[] fixtures;}
    [Serializable] class Quality {public int selected;public MctsPlanner.NodeMetric[] nodes;public MctsPlanner.IterationMetric[] iterations;public StepPlanner.Candidate[] candidates;}
    [Serializable] class Row {
        public string fixture,variant,error;public int depth,selected,yields,gc0;public bool equal;
        public double wall_ms,work_ms,max_chunk_ms,max_update_ms,heap_bytes,unity_bytes;
        public MctsPlanner.Report report;public MctsPerformance.Metric[] profile;
    }
    static string configPath;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaFineSelfTest");if(i<0)return;
        configPath=a[i+1];new GameObject("Fine MCTS parity").AddComponent<SuikaFineSearchSelfTest>();
    }
    static string Signature(StepPlanner.Decision d) {
        var copy=JsonUtility.FromJson<Quality>(JsonUtility.ToJson(new Quality {selected=d.selected_index,nodes=d.mcts.nodes,iterations=d.mcts.iterations,candidates=d.candidates}));
        foreach(var i in copy.iterations)i.elapsed_ms=0;
        foreach(var c in copy.candidates)c.elapsed_ms=0;
        return JsonUtility.ToJson(copy);
    }
    IEnumerator Start() {
        yield return null;yield return null;
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        var p=FindObjectOfType<PlayerController>();var g=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        int failures=0;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))
        foreach(var fixture in c.fixtures)foreach(int depth in new[]{4,5,6}) {
            if(fixture=="early")g.ResetGame("fine_parity");else SuikaRuntimeProbe.Instance.LoadFixture(p,g,Guid.NewGuid().ToString("N"),fixture);
            yield return null;yield return null;
            var root=new SuikaPhysicsSimulator.PathSession(p,g,udp.planningFloor);string baseline=null;
            foreach(string variant in new[]{"sync","coarse","fine"}) {
                var row=new Row {fixture=fixture,depth=depth,variant=variant};
                var settings=new PlanningSettings {ai_mode="mcts",mcts_iterations=32,mcts_max_depth=depth,frame_tick_slicing=variant=="fine"};
                var profile=new MctsPerformance();MctsPerformance.VerifyStates=true;
                IEnumerator<StepPlanner.Decision> work=MctsPlanner.PlanFrames(p,g,root.LocalFloor,settings,root);
                StepPlanner.Decision decision=null;bool more=true;int gc=GC.CollectionCount(0);
                double started=Time.realtimeSinceStartupAsDouble,previous=started;
                while(more) {
                    double now=Time.realtimeSinceStartupAsDouble;row.max_update_ms=Math.Max(row.max_update_ms,(now-previous)*1000);previous=now;
                    var budget=System.Diagnostics.Stopwatch.StartNew();
                    do {
                        var sw=System.Diagnostics.Stopwatch.StartNew();MctsPerformance.Current=profile;
                        try {more=work.MoveNext();if(more&&work.Current!=null)decision=work.Current;}
                        catch(Exception e){row.error=e.ToString();more=false;}
                        finally {MctsPerformance.Current=null;}
                        row.work_ms+=sw.Elapsed.TotalMilliseconds;row.max_chunk_ms=Math.Max(row.max_chunk_ms,sw.Elapsed.TotalMilliseconds);
                    }while(more && row.error==null && (variant=="sync" || budget.Elapsed.TotalMilliseconds<6));
                    row.max_update_ms=Math.Max(row.max_update_ms,budget.Elapsed.TotalMilliseconds);
                    if(more){row.yields++;yield return null;}
                }
                work.Dispose();row.wall_ms=(Time.realtimeSinceStartupAsDouble-started)*1000;row.gc0=GC.CollectionCount(0)-gc;
                if(decision!=null){row.report=decision.mcts;row.selected=decision.selected_index;string quality=Signature(decision);if(baseline==null)baseline=quality;row.equal=baseline==quality;}
                if(row.error!=null || !row.equal)failures++;
                row.profile=profile.Results();row.heap_bytes=GC.GetTotalMemory(false);row.unity_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();
                log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                yield return null;yield return null;
            }
            root.Dispose();MctsPerformance.VerifyStates=false;
            yield return null;yield return null;yield return null;
        }
        Application.Quit(failures==0?0:1);
    }
}
