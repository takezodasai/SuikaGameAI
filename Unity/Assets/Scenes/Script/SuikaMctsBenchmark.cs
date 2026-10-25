using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

// Bounded, opt-in native A/B benchmark. Never installed during ordinary play.
public sealed class SuikaMctsBenchmark : MonoBehaviour
{
    [Serializable] public class Config {public string output;public string[] fixtures;public int repeats=2;public bool verify=true;public string mode="mcts";}
    [Serializable] class Row
    {
        public string fixture,variant,mode;public int repeat,fruits,iterations,depth,selected;
        public bool warmup,source_unchanged;public double wall_ms,cleanup_window_ms;public int gc0,gc1,gc2,scenes_after;
        public MctsPlanner.Report report;public StepPlanner.Candidate[] candidates;
    }
    [Serializable] class Pair {public string fixture,evt="pair";public int repeat,iterations,depth;public bool equal;}
    [Serializable] class Quality {public int selected;public MctsPlanner.NodeMetric[] nodes;public MctsPlanner.IterationMetric[] iterations;public StepPlanner.Candidate[] candidates;}
    static string configPath;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install()
    {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaMctsBenchmark");if(i<0)return;
        configPath=args[i+1];new GameObject("Opt-in fixed root benchmark").AddComponent<SuikaMctsBenchmark>();
    }
    static string QualityOf(StepPlanner.Decision d)
    {
        foreach(var it in d.mcts.iterations)it.elapsed_ms=0;
        foreach(var c in d.candidates)c.elapsed_ms=0;
        return JsonUtility.ToJson(new Quality {selected=d.selected_index,nodes=d.mcts.nodes,iterations=d.mcts.iterations,candidates=d.candidates});
    }
    IEnumerator Start()
    {
        yield return null;yield return null;
        var config=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        if(config.repeats<1||config.repeats>5||config.fixtures.Length>4)throw new ArgumentException("Bounded benchmark only");
        var player=FindObjectOfType<PlayerController>();var manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        using(var log=new StreamWriter(new FileStream(config.output,FileMode.CreateNew)))
        {
            foreach(var fixture in config.fixtures)
            for(int repeat=-1;repeat<config.repeats;repeat++)
            foreach(var spec in new[]{new[]{16,3},new[]{32,3},new[]{32,4},new[]{64,4}})
            {
                string error=null;string[] qualities=new string[2];double cleanupStart=0;
                try
                {
                    SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),fixture);
                    MctsPerformance.VerifyStates=config.verify;
                    MctsPerformance.SuppressProfiler=!config.verify;
                    // Both variants see the SAME native live root in this frame.
                    // Reverse order every repeat to balance queued-scene/cache costs.
                    for(int order=0;order<2;order++)
                    {
                        bool optimized=(order+(repeat<0?0:repeat))%2!=0;
                        MctsPerformance.Optimized=optimized;
                        int g0=GC.CollectionCount(0),g1=GC.CollectionCount(1),g2=GC.CollectionCount(2);
                        var settings=new PlanningSettings {ai_mode=config.mode,mcts_iterations=spec[0],mcts_max_depth=spec[1]};
                        var sw=System.Diagnostics.Stopwatch.StartNew();
                        var d=StepPlanner.Plan(player,manager,udp.planningFloor,settings);double wall=sw.Elapsed.TotalMilliseconds;
                        var row=new Row {fixture=fixture,variant=optimized?"optimized":"baseline",mode=config.mode,repeat=repeat,warmup=repeat<0,
                            fruits=d.source_fruits.Length,iterations=spec[0],depth=spec[1],selected=d.selected_index,source_unchanged=d.same_source_verified,
                            wall_ms=wall,gc0=GC.CollectionCount(0)-g0,gc1=GC.CollectionCount(1)-g1,gc2=GC.CollectionCount(2)-g2,report=d.mcts,candidates=d.candidates};
                        log.WriteLine(JsonUtility.ToJson(row));log.Flush();qualities[optimized?1:0]=QualityOf(d);
                    }
                    bool equal=qualities[0]==qualities[1];
                    log.WriteLine(JsonUtility.ToJson(new Pair {fixture=fixture,repeat=repeat,iterations=spec[0],depth=spec[1],equal=equal}));log.Flush();
                    if(!equal)throw new InvalidOperationException("A/B search/physical state mismatch");
                    cleanupStart=Time.realtimeSinceStartupAsDouble;
                }catch(Exception e){error=e.ToString();Debug.LogError(error);log.WriteLine(JsonUtility.ToJson(new Failure {error=error}));log.Flush();}
                finally {MctsPerformance.Optimized=true;MctsPerformance.VerifyStates=false;MctsPerformance.SuppressProfiler=false;}
                if(error!=null){Application.Quit(1);yield break;}
                // Let deferred unload actually finish outside the timed search. This
                // includes two render frames and is not a pure CPU destruction timer.
                int scenes=0;
                for(int frame=0;frame<120;frame++)
                {
                    yield return null;
                    scenes=0;for(int i=0;i<SceneManager.sceneCount;i++)if(SceneManager.GetSceneAt(i).name.StartsWith("SuikaPrediction_"))scenes++;
                    if(scenes==0)break;
                }
                log.WriteLine(JsonUtility.ToJson(new Row {fixture=fixture,variant="cleanup",repeat=repeat,iterations=spec[0],depth=spec[1],scenes_after=scenes,cleanup_window_ms=(Time.realtimeSinceStartupAsDouble-cleanupStart)*1000}));log.Flush();
                if(scenes!=0){Debug.LogError("Prediction scene leak after benchmark");Application.Quit(1);yield break;}
            }
        }
        Application.Quit(0);
    }
    [Serializable] class Failure {public string evt="error",error;}
}
