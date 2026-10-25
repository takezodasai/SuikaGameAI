using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Owned diagnostic Player only, explicitly opt-in. Never edits/saves the Scene.
public class SuikaMctsSelfTest : MonoBehaviour
{
    [Serializable] class Report
    {
        public string status="running",error;public List<string> passed=new List<string>();
        public List<MctsPlanner.Report> searches=new List<MctsPlanner.Report>();
        public List<TwoStepPlanner.Report> two_step=new List<TwoStepPlanner.Report>();
        public int prediction_scenes_after_cleanup;public double elapsed_ms;
    }
    static string destination;readonly Report report=new Report();
    PlayerController player;GameManager manager;UDPCommunicatorUnity udp;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install()
    {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaMctsSelfTest");if(i<0)return;
        if(i+1>=args.Length)throw new ArgumentException("Output path required");destination=args[i+1];
        new GameObject("MCTS opt-in tests").AddComponent<SuikaMctsSelfTest>();
    }
    void Check(bool ok,string name){if(!ok)throw new Exception(name);report.passed.Add(name);}
    IEnumerator Start()
    {
        yield return null;yield return null;var clock=System.Diagnostics.Stopwatch.StartNew();
        player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        try {MathTests();PreviewMass();RewardCollapse();}catch(Exception e){report.error=e.ToString();}
        yield return null;yield return null;
        var random=UnityEngine.Random.state;
        foreach(int depth in new[]{2,3,4}) foreach(int count in new[]{16,32,64})
        {
            if(report.error!=null)break;
            try
            {
                UnityEngine.Random.state=random;manager.ResetGame("mcts_fixture");Spawn(new Vector3(-.1f,udp.planningFloor.bounds.max.y+.5f,0));Spawn(new Vector3(.1f,udp.planningFloor.bounds.max.y+.5f,0));
                var d=MctsPlanner.Plan(player,manager,udp.planningFloor,new PlanningSettings {ai_mode="mcts",candidate_count=5,mcts_iterations=count,mcts_max_depth=depth});
                Verify(d);report.searches.Add(d.mcts);
            }catch(Exception e){report.error=e.ToString();}
            yield return null;yield return null;
        }
        if(report.error==null)
        {
            try
            {
                manager.ResetGame("mcts_value_fixture");
                var settings=new PlanningSettings {ai_mode="mcts_value",candidate_count=5,mcts_iterations=16,mcts_max_depth=3};
                var d=MctsPlanner.Plan(player,manager,udp.planningFloor,settings);Verify(d);report.searches.Add(d.mcts);
                var again=MctsPlanner.Plan(player,manager,udp.planningFloor,settings);
                var savedRandom=UnityEngine.Random.state;UnityEngine.Random.InitState(190388);
                var hiddenChanged=MctsPlanner.Plan(player,manager,udp.planningFloor,settings);UnityEngine.Random.state=savedRandom;
                Check(JsonUtility.ToJson(new Rows {nodes=d.mcts.nodes})==JsonUtility.ToJson(new Rows {nodes=hiddenChanged.mcts.nodes}),"changing hidden live RNG does not change search");
                Check(d.selected_index==again.selected_index && JsonUtility.ToJson(new Rows {nodes=d.mcts.nodes})==JsonUtility.ToJson(new Rows {nodes=again.mcts.nodes}),"seeded tree replay deterministic and branches isolated");
                manager.ResetGame("mcts_go_fixture");var fruit=Spawn(new Vector3(-2,manager.GameOverHeight+1,0));fruit.GetComponent<Rigidbody2D>().gravityScale=0;
                typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(fruit.GetComponent<FruitEvolution>(),new object[]{true});
                var go=MctsPlanner.Plan(player,manager,udp.planningFloor,new PlanningSettings {ai_mode="mcts",mcts_iterations=16});
                Check(go.all_predicted_terminal && go.selected_index>=0,"all immediate GO uses original survival fallback");
                foreach(var it in go.mcts.iterations)Check(it.depth==1 && it.leaf_points==0,"terminal search stops without fabricated future reward");
            }catch(Exception e){report.error=e.ToString();}
        }
        yield return null;yield return null;
        for(int i=0;i<UnityEngine.SceneManagement.SceneManager.sceneCount;i++)if(UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).name.StartsWith("SuikaPrediction_"))report.prediction_scenes_after_cleanup++;
        if(report.error==null)try {Check(report.prediction_scenes_after_cleanup==0,"prediction scenes asynchronously released");Check(manager.isGameOver,"same GO fixture triggers real game GO");report.status="passed";}catch(Exception e){report.error=e.ToString();}
        if(report.error!=null)report.status="failed";report.elapsed_ms=clock.Elapsed.TotalMilliseconds;
        if(File.Exists(destination))throw new IOException("Refuse output overwrite");Directory.CreateDirectory(Path.GetDirectoryName(destination));File.WriteAllText(destination,JsonUtility.ToJson(report,true));
        Debug.Log("MCTS SELFTEST "+report.status+" "+report.error);Application.Quit(report.error==null?0:1);
    }
    [Serializable] class Rows {public MctsPlanner.NodeMetric[] nodes;}
    void MathTests()
    {
        var predicted=new ValueSnapshot {fruits=new[]{new UDPCommunicatorUnity.BoardFruit {id=1,type=0}},current_fruit=new UDPCommunicatorUnity.ControlledFruit()};
        var actual=new ValueSnapshot {fruits=new[]{new UDPCommunicatorUnity.BoardFruit {id=2,type=0}},current_fruit=new UDPCommunicatorUnity.ControlledFruit()};
        Check(!UDPCommunicatorUnity.ComparePathState(predicted,actual,0,0,0,0).types_count_match,"missing original fruit ID cannot be replaced by nearest same-type fruit");
        predicted.fruits[0].id=-1;
        Check(UDPCommunicatorUnity.ComparePathState(predicted,actual,0,0,0,0).types_count_match,"new local fruit ID can match actual new fruit geometrically");
        var n=new MctsPlanner.Node(2,0,0);Check(MctsPlanner.Select(n,1,55)==0,"unvisited action explored");
        n.actions[0].Add(55,false);n.visits=1;Check(MctsPlanner.Select(n,1,55)==1,"all actions covered before UCT");
        n.actions[1].Add(110,false);n.visits=2;Check(MctsPlanner.Select(n,0,55)==1,"UCT exploits point mean");
        n.actions[1].immediate=new StepPlanner.Candidate {success=true,drop_success=true,predicted_game_over=true};
        Check(MctsPlanner.Select(n,0,55)==0,"known immediate GO excluded despite large reward");
        var bandit=new MctsPlanner.Node(2,0,0);
        for(int t=0;t<64;t++){int action=MctsPlanner.Select(bandit,Math.Sqrt(2),55);bandit.actions[action].Add(action==0?0:110,false);bandit.visits++;}
        Check(bandit.actions[1].visits>bandit.actions[0].visits*4,"UCT concentrates visits on better deterministic return");
        var e=new MctsPlanner.Edge();e.Add(55,false);e.Add(165,true);Check(e.visits==2 && e.Mean==110 && e.terminal_returns==1,"backed-up point mean and terminal count");
    }
    void PreviewMass()
    {
        manager.ResetGame("preview_mass_probe");player.currentFruit.SetActive(false);Destroy(player.currentFruit);
        player.currentFruit=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[2],player.GetHeldWorldPosition(),Quaternion.identity);
        var held=player.currentFruit;held.GetComponent<FruitEvolution>().IsPreview=true;PlayerController.PreparePreviewBody(held,false);FruitColliderShape.Get(held).isTrigger=true;
        using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            path.EnableTrace();var predicted=path.Advance(.5f,1,0);PredictionDiagnostics.FruitState dropped=null;
            foreach(var fruit in predicted.trace.frames[predicted.trace.frames.Count-1].fruits)if(!fruit.preview&&fruit.type==2)dropped=fruit;
            player.DropFruit();var body=held.GetComponent<Rigidbody2D>();
            Check(dropped!=null && Math.Abs(dropped.inertia-body.inertia)<1e-6 && Vector2.Distance(dropped.center_of_mass,body.centerOfMass)<1e-6,"held grape recomputes solid COM/inertia identically to real DropFruit");
        }
    }
    void RewardCollapse()
    {
        manager.ResetGame("mcts_collapse_fixture");Spawn(new Vector3(-.1f,udp.planningFloor.bounds.max.y+.5f,0));Spawn(new Vector3(.1f,udp.planningFloor.bounds.max.y+.5f,0));
        var settings=new PlanningSettings {ai_mode="two_step",candidate_count=2};
        var shortPlan=TwoStepPlanner.Plan(player,manager,udp.planningFloor,settings);settings.two_step_exhaustive_reward=true;
        var full=TwoStepPlanner.Plan(player,manager,udp.planningFloor,settings);
        Check(shortPlan.two_step.paths==4 && full.two_step.paths==4*player.fruits.Length,"reward leaf skips duplicate undropped C paths");
        Check(shortPlan.selected_index==full.selected_index,"collapsed reward selects same root action");
        foreach(var a in shortPlan.two_step.outcomes)foreach(var b in full.two_step.outcomes)
            if(a.first_index==b.first_index&&a.second_index==b.second_index)Check(a.total_reward==b.total_reward&&a.game_over==b.game_over&&a.total_ticks==b.total_ticks&&a.merges==b.merges,"all public C give same two-drop reward GO ticks merges");
        // Stronger physical check: C changes the held preview, not the board.
        string reference=null;
        for(int slot=0;slot<player.fruits.Length;slot++)using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
        {
            path.Advance(.25f,25,slot);var last=path.Advance(.75f,25,-1);
            string sig=JsonUtility.ToJson(new Board {fruits=last.fruits,score=last.score,go=last.game_over});
            if(reference==null)reference=sig;else Check(reference==sig,"undropped C does not alter two-action board kinematics");
        }
        report.two_step.Add(shortPlan.two_step);report.two_step.Add(full.two_step);
    }
    [Serializable] class Board {public UDPCommunicatorUnity.BoardFruit[] fruits;public int score;public bool go;}
    void Verify(StepPlanner.Decision d)
    {
        Check(d.same_source_verified&&d.mcts.prefixes_match,"live source RNG and native prefixes unchanged");
        int count=0;double sum=0;foreach(var a in d.mcts.nodes[0].actions){count+=a.visits;sum+=a.mean_points*a.visits;Check(a.visits>0,"root candidate covered");}
        double returns=0;foreach(var it in d.mcts.iterations){returns+=it.total_points;Check(it.depth<=d.settings.mcts_max_depth&&it.depth>=1,"bounded rollout depth");if(!it.game_over)Check(it.chance_slots[it.depth-1]==-1,"leaf future NEXT remains unknown");}
        Check(count==d.mcts.completed_iterations&&Math.Abs(sum-returns)<.02,"root visit conservation and no duplicate reward");
        Check(d.selected_index>=0&&d.selected_x>=0&&d.selected_x<=1,"selected safe normalized action");
        Check(d.mcts.nodes[0].actions[d.selected_index].visits>0,"final choice visited");
        int physical=0,logical=0;foreach(var it in d.mcts.iterations){physical+=it.simulated_ticks;logical+=it.ticks;}
        Check(physical==d.mcts.total_physics_ticks && logical-physical==d.mcts.skipped_physics_ticks,"cached leaf logical and simulated ticks accounted separately");
        if(d.settings.mcts_max_depth==2 && d.settings.mcts_iterations==64)Check(d.mcts.leaf_cache_hits>0,"duplicate terminal-horizon physics reused without restoring intermediate cache");
    }
    GameObject Spawn(Vector3 position)
    {
        var fruit=Instantiate(player.fruits[0],position,Quaternion.identity);fruit.tag="Fruit";fruit.GetComponent<FruitEvolution>().IsPreview=false;
        var body=fruit.GetComponent<Rigidbody2D>();if(body==null)body=fruit.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(body);FruitColliderShape.Get(fruit).isTrigger=false;
        var danse=fruit.GetComponent<Danse>();if(danse!=null)danse.InitializePhysicsMaterial();return fruit;
    }
}
