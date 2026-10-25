using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Explicit opt-in test Player only. Nothing is added to the saved Scene.
public class SuikaPathSelfTest : MonoBehaviour
{
    [Serializable] public class Report
    {
        public string status="running",error;
        public List<string> passed=new List<string>();
        public double elapsed_ms;
        public int first_ticks,second_ticks,predicted_merge_count;
        public float cooldown_after_first;
        public int prediction_scenes_after_cleanup;public long unity_allocated_after_cleanup;
        public List<TwoStepPlanner.Report> searches=new List<TwoStepPlanner.Report>();
    }
    static string destination;
    readonly Report report=new Report();
    PlayerController player;GameManager manager;UDPCommunicatorUnity udp;
    System.Diagnostics.Stopwatch timer;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Install()
    {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaPathSelfTest");
        if(i<0)return;if(i+1>=args.Length)throw new ArgumentException("Selftest output path required");
        destination=args[i+1];new GameObject("STEP8 opt-in tests").AddComponent<SuikaPathSelfTest>();
    }
    void Check(bool ok,string name) {if(!ok)throw new Exception(name);report.passed.Add(name);}
    IEnumerator Start()
    {
        yield return null;yield return null;
        timer=System.Diagnostics.Stopwatch.StartNew();player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        try {RunNative();PrepareGoFixture();}
        catch(Exception e){report.error=e.ToString();}
        if(report.error!=null){Finish();yield break;}
        yield return null;yield return null;
        for(int i=0;i<UnityEngine.SceneManagement.SceneManager.sceneCount;i++)if(UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).name.StartsWith("SuikaPrediction_"))report.prediction_scenes_after_cleanup++;
        report.unity_allocated_after_cleanup=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();
        try {Check(report.prediction_scenes_after_cleanup==0,"all prediction scenes released after asynchronous unload");Check(manager.isGameOver,"same armed above-line fruit triggers actual game over");report.status="passed";}
        catch(Exception e){report.error=e.ToString();}
        Finish();
    }
    void RunNative()
    {
        string live=SuikaPhysicsSimulator.LiveSignature(player);var random=UnityEngine.Random.state;int score=ScoreManager.Instance.GetScore();
        using(var a=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            Check(player.GetDropRange().valid,"retained prediction walls do not contaminate live movement range");
            int next=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType;
            var first=a.Advance(.5f,25,0);report.first_ticks=first.physics_steps;
            Check(!first.game_over && first.current_fruit.type==next && first.value_state.next_fruit_type==player.fruits[0].GetComponent<FruitEvolution>().fruitType,"held and hypothetical visible NEXT transition");
            Check(a.CanAcceptAction,"25 post ticks is an input boundary, not a settle requirement");
            report.cooldown_after_first=first.value_state.drop_cooldown_remaining;
            string before=a.StateSignature();
            using(var b=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
            {
                var bFirst=b.Advance(.5f,25,0);
                Check(before==a.StateSignature(),"sibling simulation does not mutate retained parent");
                var second=a.Advance(.25f,25,-1);report.second_ticks=second.physics_steps;
                var bSecond=b.Advance(.25f,25,-1);
                Check(a.StateSignature()==b.StateSignature(),"short-prefix replay equals continuous native two-action path");
                Check(second.initial_fruits.Length==first.fruits.Length,"second starts from first board without re-instantiation");
                Check(second.score-score==first.reward+second.reward,"two-action rewards conserve score");
                Check(second.current_fruit.type==player.fruits[0].GetComponent<FruitEvolution>().fruitType && second.value_state.next_fruit_type==-1,"third held fruit follows declared chance, later NEXT unknown");
                bool rejected=false;try {a.Advance(.5f);}catch(InvalidOperationException){rejected=true;}
                Check(rejected,"unknown NEXT cannot be silently sampled or read from real RNG");
            }
        }
        Check(live==SuikaPhysicsSimulator.LiveSignature(player)&&random.Equals(UnityEngine.Random.state)&&score==ScoreManager.Instance.GetScore(),"paths leave real board score and RNG unchanged");
        manager.ResetGame("native_merge_fixture");
        var c=Spawn(new Vector3(-.1f,udp.planningFloor.bounds.max.y+.5f,0),false);
        var d=Spawn(new Vector3(.1f,udp.planningFloor.bounds.max.y+.5f,0),false);
        using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            var r=path.Advance(.5f,25,0);report.predicted_merge_count=r.merges;
            Check(r.merges>=1 && r.reward>=ScoreManager.Instance.evolutionScores[0],"native same-kind merge and score use existing rules");
            Check(ScoreManager.Instance.GetScore()==0,"predicted merge cannot change real score");
        }
        foreach(var mode in new[]{"reward","heuristic","value"})
        {
            var decision=TwoStepPlanner.Plan(player,manager,udp.planningFloor,new PlanningSettings {ai_mode="two_step",search_leaf=mode,candidate_count=2});
            Check(decision.same_source_verified && decision.two_step.prefixes_match && decision.two_step.paths==4*(mode=="reward"?1:player.fruits.Length),"contact/merge root prefixes stable across siblings: "+mode);
            report.searches.Add(decision.two_step);
        }
        manager.ResetGame("native_wait_fixture");
        using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            path.Advance(.5f,1,0);var before=path.Snapshot();double time=path.GameTime;
            path.WaitTicks(3);var after=path.Snapshot();
            Check(Math.Abs(path.GameTime-time-3*Time.fixedDeltaTime)<1e-6 && after.fruits[0].y<before.fruits[0].y,"explicit wait advances clock and physical board");
            var second=path.Advance(.5f,1,-1);
            Check(second.cooldown_wait_steps>0,"second action waits for .4 second drop cooldown when needed");
        }
        var settings=new PlanningSettings();var features=new HeuristicEvaluator.Features {fruits=new HeuristicEvaluator.FruitFeature[0],left_x=0,right_x=10,floor_y=0,go_y=10};
        var terminal=new ValueSnapshot {fruits=new UDPCommunicatorUnity.BoardFruit[0],game_over=true};
        foreach(var mode in new[]{"reward","heuristic","value"})Check(TwoStepPlanner.LeafPoints(mode,55,features,terminal,settings,null)==55,"terminal leaf retains immediate reward once: "+mode);
    }
    GameObject Spawn(Vector3 position,bool collided)
    {
        var fruit=Instantiate(player.fruits[0],position,Quaternion.identity);var fe=fruit.GetComponent<FruitEvolution>();fe.IsPreview=false;fruit.tag="Fruit";
        var body=fruit.GetComponent<Rigidbody2D>();if(body==null)body=fruit.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(body);
        FruitColliderShape.Get(fruit).isTrigger=false;var danse=fruit.GetComponent<Danse>();if(danse!=null)danse.InitializePhysicsMaterial();
        typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(fe,new object[]{collided});return fruit;
    }
    void PrepareGoFixture()
    {
        using(var stale=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            manager.ResetGame("native_go_fixture");
            Check(!stale.CanAcceptAction,"live reset invalidates old native root");
        }var fruit=Spawn(new Vector3(-2,manager.GameOverHeight+1,0),false);fruit.GetComponent<Rigidbody2D>().gravityScale=0;
        using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))Check(!path.Advance(.5f,1,0).game_over,"uncontacted above-line fruit does not arm GO");
        typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(fruit.GetComponent<FruitEvolution>(),new object[]{true});
        using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            Check(path.Advance(.5f,1,0).game_over,"contacted above-line fruit triggers predicted GO");
            Check(!path.CanAcceptAction,"terminal path cannot accept second action");
        }
    }
    void Finish()
    {
        report.elapsed_ms=timer.Elapsed.TotalMilliseconds;if(report.error!=null)report.status="failed";
        Directory.CreateDirectory(Path.GetDirectoryName(destination));
        if(File.Exists(destination))throw new IOException("Refuse selftest overwrite");
        File.WriteAllText(destination,JsonUtility.ToJson(report,true));
        Debug.Log("STEP8 SELFTEST "+JsonUtility.ToJson(report));Application.Quit(report.error==null?0:1);
    }
}
