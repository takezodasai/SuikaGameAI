using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Bounded repeated frozen-root test. Installed only by an explicit Player argument.
public sealed class SuikaLifetimeProbe:MonoBehaviour {
    [Serializable] class Config {public string fixture,output;public int repeats=8,frames_between=2;public PlanningSettings settings;}
    [Serializable] class Row {public string phase,error;public int repetition;public bool source_unchanged;public PredictionLifecycle.Sample sample;public MctsPlanner.Report report;public float selected_x;public MctsPerformance.Metric[] profile;public double gc_ms;}
    static string config;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaLifetimeProbe");if(i>=0){config=a[i+1];new GameObject("Prediction lifetime diagnostic").AddComponent<SuikaLifetimeProbe>();}}
    IEnumerator Start(){
        yield return null;yield return null;
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));var player=FindObjectOfType<PlayerController>();var manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew))) {
            SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),c.fixture);
            using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor)) {
                string source=root.StateSignature();
                log.WriteLine(JsonUtility.ToJson(new Row {phase="start",sample=PredictionLifecycle.Read()}));log.Flush();
                for(int i=0;i<c.repeats;i++) {
                    var row=new Row {phase="search",repetition=i};var profiler=new MctsPerformance();MctsPerformance.Current=profiler;
                    try {StepPlanner.Decision d=null;using(var work=MctsPlanner.PlanFrames(player,manager,udp.planningFloor,c.settings,root))while(work.MoveNext())if(work.Current!=null)d=work.Current;row.report=d.mcts;row.selected_x=d.selected_x;row.source_unchanged=root.StateSignature()==source;}
                    catch(Exception e){row.error=e.ToString();}
                    finally{MctsPerformance.Current=null;}
                    row.profile=profiler.Results();row.sample=PredictionLifecycle.Read();log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                    if(row.error!=null){Application.Quit(2);yield break;}
                    if(row.sample.private_bytes>2500L*1024*1024){Application.Quit(3);yield break;}
                    for(int j=0;j<c.frames_between;j++)yield return null;
                    log.WriteLine(JsonUtility.ToJson(new Row {phase="after_frames",repetition=i,sample=PredictionLifecycle.Read()}));log.Flush();
                }
            }
            for(int i=0;i<8;i++)yield return null;
            log.WriteLine(JsonUtility.ToJson(new Row {phase="released",sample=PredictionLifecycle.Read()}));
            var watch=System.Diagnostics.Stopwatch.StartNew();GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
            log.WriteLine(JsonUtility.ToJson(new Row {phase="after_explicit_gc",sample=PredictionLifecycle.Read(),gc_ms=watch.Elapsed.TotalMilliseconds}));log.Flush();
        }
        Application.Quit(0);
    }
}
