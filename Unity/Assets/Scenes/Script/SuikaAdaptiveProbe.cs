using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
public sealed class SuikaAdaptiveProbe:MonoBehaviour {
    [Serializable] class Search {public string name;public PlanningSettings settings;}
    [Serializable] class Config {public string output;public string[] fixtures;public Search[] searches;}
    [Serializable] class Row {public string fixture,name,error;public bool source_unchanged;public StepPlanner.Decision decision;public MctsPlanner.Report report;public double wall_ms;}
    static string config;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaAdaptiveProbe");if(i>=0){config=a[i+1];new GameObject("Adaptive diagnostic").AddComponent<SuikaAdaptiveProbe>();}}
    static void Check(bool value,string reason){if(!value)throw new Exception("Adaptive selftest: "+reason);}
    static MctsPlanner.Node Node(int id,int depth){var n=new MctsPlanner.Node(5,id,depth){visits=40,positions=MctsAdaptiveControl.InitialPositions(5)};foreach(var e in n.actions){e.visits=8;e.sum=0;e.sumSquares=0;e.min=e.max=0;e.immediate=new StepPlanner.Candidate {success=true,drop_success=true};}return n;}
    static void SelfTests(){
        MctsDepthControl.SelfTests();
        var s=new PlanningSettings {ai_mode="mcts",mcts_widening=true};s.Validate();
        var n=Node(0,0);var edge=n.actions[0];var a=MctsAdaptiveControl.TryWiden(n,s,40);Check(a!=null&&n.actions.Length==6&&a.x>0&&a.x<1,"root addition");Check(ReferenceEquals(edge,n.actions[0])&&edge.visits==8,"existing statistics preserved");Check(MctsAdaptiveControl.TryWiden(n,s,41)==null,"new action gets visits before another addition");
        var future=Node(2,2);Check(MctsAdaptiveControl.TryWiden(future,s,40).depth==2,"nonroot addition");
        var root=Node(0,0);s.mcts_widening=false;s.mcts_budget_mode="adaptive";
        Check(!MctsAdaptiveControl.Assess(root,s,32,-1,0).stable,"first checkpoint not proof of stability");
        Check(MctsAdaptiveControl.Assess(root,s,64,0,0).stable,"flat zero values can stop without arbitrary score gap");
        root.actions[0].terminal_returns=3;Check(!MctsAdaptiveControl.Assess(root,s,64,0,0).stable,"terminal samples continue search");
        root.actions[0].terminal_returns=0;root.actions[0].sum=80;root.actions[0].sumSquares=800;Check(MctsAdaptiveControl.Assess(root,s,64,0,0).reason=="value_drift","value drift continues search");
        var all=new HashSet<float>();foreach(float x in n.positions.x)Check(x>=0&&x<=1&&all.Add(x),"unique legal positions");
        Debug.Log("ADAPTIVE CONTROL SELFTESTS OK");
    }
    IEnumerator Start(){
        yield return null;yield return null;SelfTests();var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));var p=FindObjectOfType<PlayerController>();var g=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();int failures=0;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(string fixture in c.fixtures){
            SuikaRuntimeProbe.Instance.LoadFixture(p,g,Guid.NewGuid().ToString("N"),fixture);
            using(var root=new SuikaPhysicsSimulator.PathSession(p,g,udp.planningFloor)){
                string signature=root.StateSignature();foreach(var search in c.searches){var row=new Row {fixture=fixture,name=search.name};var watch=System.Diagnostics.Stopwatch.StartNew();
                    try{using(var work=MctsPlanner.PlanFrames(p,g,udp.planningFloor,search.settings,root))while(work.MoveNext())if(work.Current!=null)row.decision=work.Current;row.report=row.decision.mcts;row.source_unchanged=signature==root.StateSignature();if(!row.source_unchanged)throw new Exception("Source mutated");}
                    catch(Exception e){row.error=e.ToString();if(search.name!="zero_time")failures++;}
                    row.wall_ms=watch.Elapsed.TotalMilliseconds;log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                }
            }
        }Application.Quit(failures==0?0:2);
    }
}
