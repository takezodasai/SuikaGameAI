using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.LowLevel;

// Opt-in experimental actual-world continuation of an APPROXIMATE cold fixture.
// No changes to game rules, planners, prefabs, or ordinary play.
public sealed class SuikaWatermelonLab : MonoBehaviour {
    [Serializable] class Config {
        public string fixture,output;
        public int future_seed=20261031,search_seed=8191,iterations=128,depth=4,max_drops=80;
        public float max_seconds=180,first_x=-1;
    }
    [Serializable] class Command {public int start_tick,drop_tick=-1,completion_tick=-1;public float x,applied_x;public bool forced;}
    [Serializable] class Fixture {public ValueSnapshot snapshot;public UDPCommunicatorUnity.BoardFruit[] fruits;}
    [Serializable] class Row {
        public string evt,reason,error,rng,build_guid,restoration="approximate_cold_fixture_not_historical_native_state",source="actual_experimental_continuation";
        public int tick,accepted_drops,completed_actions,initial_score,score,additional_score,initial_watermelons,new_watermelons,max_watermelons_present,double_watermelons,merges;
        public bool natural_go,truncated,second_watermelon_generated,two_watermelons_present,exact_historical_replay=false;
        public double elapsed_seconds,planning_ms;public long retained_scenes,pending_unloads,allocated_bytes;
        public ValueSnapshot state;public StepPlanner.Decision planning;public Command command;public SuikaEpisodeEvents.Snapshot raw_events;
    }
    static SuikaWatermelonLab instance;static string configPath;
    Config cfg;PlayerController player;GameManager game;UDPCommunicatorUnity udp;StreamWriter log;
    System.Diagnostics.Stopwatch wall;bool running,active;int tick,accepted,completed,initialScore,initialWatermelons,maxPresent,newCreated,doubles,baseCreated,baseDoubles,eventIndex;
    Command command;string reason;double planningMs;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaWatermelonLab");if(i>=0){configPath=a[i+1];instance=new GameObject("Watermelon continuation lab (APPROXIMATE)").AddComponent<SuikaWatermelonLab>();}}
    static void Observe(){if(instance!=null)instance.AfterPhysics();}
    static bool Insert(ref PlayerLoopSystem loop){if(loop.subSystemList==null)return false;var xs=new List<PlayerLoopSystem>(loop.subSystemList);for(int i=0;i<xs.Count;i++){if(xs[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate)){xs.Insert(i+1,new PlayerLoopSystem{type=typeof(SuikaWatermelonLab),updateDelegate=Observe});loop.subSystemList=xs.ToArray();return true;}var c=xs[i];if(Insert(ref c)){xs[i]=c;loop.subSystemList=xs.ToArray();return true;}}return false;}
    void CountEvents(){
        var e=ScoreManager.Instance.EpisodeEvents.Read();if(!e.known)throw new Exception("Actual event observation required");
        // Existing event recorder starts at zero after Reset; imported fruit is NOT a new success.
        // Apply an observer-only baseline offset, processing every callback even transient pairs.
        for(;eventIndex<e.events.Length;eventIndex++){
            var x=e.events[eventIndex];if(x.kind=="watermelon_created")newCreated++;
            if(x.kind=="double_watermelon")doubles++;
            maxPresent=Math.Max(maxPresent,initialWatermelons+newCreated-2*doubles);
        }
        if(newCreated!=e.watermelons_created-baseCreated||doubles!=e.double_watermelons-baseDoubles)throw new Exception("Event delta conservation failed");
    }
    void Write(string evt,StepPlanner.Decision planning=null,string error=null){
        CountEvents();int score=ScoreManager.Instance.GetScore();
        var row=new Row{evt=evt,reason=reason,error=error,tick=tick,accepted_drops=accepted,completed_actions=completed,initial_score=initialScore,score=score,additional_score=score-initialScore,
            initial_watermelons=initialWatermelons,new_watermelons=newCreated,max_watermelons_present=maxPresent,double_watermelons=doubles,merges=ScoreManager.Instance.EpisodeMergeCount,
            second_watermelon_generated=initialWatermelons>=1&&newCreated>=1,two_watermelons_present=maxPresent>=2,natural_go=game.isGameOver&&reason=="natural_go",truncated=evt=="end"&&reason!="natural_go",
            elapsed_seconds=wall.Elapsed.TotalSeconds,planning_ms=planningMs,state=udp.CounterfactualSnapshot(),planning=planning,command=command,raw_events=ScoreManager.Instance.EpisodeEvents.Read(),
            rng=JsonUtility.ToJson(UnityEngine.Random.state),build_guid=Application.buildGUID,retained_scenes=PredictionLifecycle.RetainedScenes,pending_unloads=PredictionLifecycle.Pending,
            allocated_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()};
        log.WriteLine(JsonUtility.ToJson(row));log.Flush();
    }
    void Fail(Exception e){reason="error";running=false;Time.timeScale=0;Write("error",null,e.ToString());}
    void Update(){
        if(!running)return;
        try{
            if(Input.GetKeyDown(KeyCode.Escape)){reason="user_stop";running=false;Time.timeScale=0;return;}
            if(game.isGameOver){reason="natural_go";running=false;Time.timeScale=0;return;}
            if(wall.Elapsed.TotalSeconds>=cfg.max_seconds){reason="wall_limit";running=false;Time.timeScale=0;return;}
            if(active)return;
            if(completed>=cfg.max_drops){reason="drop_limit";running=false;return;}
            Time.timeScale=0;string signature=SuikaPhysicsSimulator.LiveSignature(player),rng=JsonUtility.ToJson(UnityEngine.Random.state);
            Time.timeScale=1;player.StepControlLocked=false;
            var settings=new PlanningSettings{ai_mode="mcts",execution_mode="sync",candidate_count=5,post_drop_steps=25,mcts_iterations=cfg.iterations,mcts_max_depth=cfg.depth,mcts_seed=cfg.search_seed,rollout_policy="random"};
            var decision=StepPlanner.Plan(player,game,udp.planningFloor,settings);Time.timeScale=0;player.StepControlLocked=true;
            if(signature!=SuikaPhysicsSimulator.LiveSignature(player)||rng!=JsonUtility.ToJson(UnityEngine.Random.state))throw new Exception("Planning contaminated actual state or RNG");
            if(decision.selected_index<0)throw new Exception("No MCTS action");planningMs=decision.elapsed_ms;
            command=new Command{x=completed==0&&cfg.first_x>=0?cfg.first_x:decision.selected_x,forced=completed==0&&cfg.first_x>=0,start_tick=tick+1};
            Write("decision",decision);active=true;Time.timeScale=1;
        }catch(Exception e){Fail(e);}
    }
    void FixedUpdate(){
        if(!running)return;tick++;if(game.isGameOver||!active||command.drop_tick>=0)return;
        try{
            var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,command.x),nx=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
            if(!player.TryMoveHeldTo(nx,range,out error))throw new Exception(error);if(nx!=target||!player.CanDropFruit)return;
            float applied;long id;if(!player.TryDropAt(command.x,out applied,out id,out range,out error))throw new Exception(error);
            command.applied_x=applied;command.drop_tick=tick;accepted++;Write("release");
        }catch(Exception e){Fail(e);}
    }
    void AfterPhysics(){
        if(!running)return;
        try{int beforeCreated=newCreated,beforeDoubles=doubles;CountEvents();if(newCreated!=beforeCreated||doubles!=beforeDoubles)Write("milestone_post_physics");if(active&&command.drop_tick>=0&&tick-command.drop_tick==25){command.completion_tick=tick;completed++;active=false;Time.timeScale=0;Write("action");}}
        catch(Exception e){Fail(e);}
    }
    IEnumerator Restore(){
        SuikaRuntimeProbe.Instance.LoadFixture(player,game,Guid.NewGuid().ToString("N"),cfg.fixture);Time.timeScale=0;
        yield return null;yield return null;
        var f=JsonUtility.FromJson<Fixture>(File.ReadAllText(cfg.fixture));var remaining=new List<FruitEvolution>();
        foreach(var fruit in FindObjectsOfType<FruitEvolution>())if(fruit.Simulation==null&&!fruit.IsPreview&&!fruit.IsMerging)remaining.Add(fruit);
        var bodies=new List<Rigidbody2D>();
        foreach(var v in f.fruits){
            FruitEvolution best=null;float distance=float.PositiveInfinity;
            foreach(var fruit in remaining)if(fruit.fruitType==v.type){float d=Vector2.SqrMagnitude((Vector2)fruit.transform.position-new Vector2(v.x,v.y));if(d<distance){distance=d;best=fruit;}}
            if(best==null||distance>1e-8f)throw new Exception("Fixture fruit mapping shifted");remaining.Remove(best);
            var b=best.GetComponent<Rigidbody2D>();if(b==null)throw new Exception("Placed fruit missing dynamic body");b.position=new Vector2(v.x,v.y);b.rotation=v.angle;bodies.Add(b);
        }
        Physics2D.SyncTransforms();
        for(int i=0;i<bodies.Count;i++){var v=f.fruits[i];bodies[i].velocity=new Vector2(v.vx,v.vy);bodies[i].angularVelocity=v.angular_velocity;if(v.observation_metadata_known&&v.sleeping)bodies[i].Sleep();}
        if(f.snapshot!=null&&f.snapshot.current_fruit!=null&&f.snapshot.current_fruit.y_known){
            var pos=player.currentFruit.transform.position;pos.y=f.snapshot.current_fruit.y;player.currentFruit.transform.position=pos;
            // Some held prefabs have no Rigidbody until normal release. Do not change that rule.
            var heldBody=player.currentFruit.GetComponent<Rigidbody2D>();if(heldBody!=null)heldBody.position=pos;Physics2D.SyncTransforms();
        }
    }
    IEnumerator Start(){
        yield return null;yield return null;cfg=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        if(cfg.max_seconds<=0||cfg.max_seconds>600||cfg.max_drops<1||cfg.max_drops>1000||cfg.first_x>1||cfg.first_x< -1||float.IsNaN(cfg.first_x))throw new Exception("Invalid bounded lab config");
        new PlanningSettings{ai_mode="mcts",candidate_count=5,mcts_iterations=cfg.iterations,mcts_max_depth=cfg.depth,mcts_seed=cfg.search_seed}.Validate();
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        if(SuikaRuntimeProbe.Instance==null)throw new Exception("-suikaRuntimeProbe required for isolated fixture restoration");
        player.StepControlLocked=true;Time.timeScale=0;
        yield return Restore();
        Time.timeScale=0;player.StepControlLocked=true;ScoreManager.Instance.EpisodeEvents.Enabled=true;
        var root=udp.CounterfactualSnapshot();initialScore=root.score;ScoreManager.Instance.SendMessage("UpdateScoreUI",SendMessageOptions.RequireReceiver);foreach(var f in root.fruits)if(f.type==10)initialWatermelons++;
        if(initialWatermelons<1)throw new Exception("Post-watermelon fixture required");maxPresent=initialWatermelons;
        var baseline=ScoreManager.Instance.EpisodeEvents.Read();baseCreated=baseline.watermelons_created;baseDoubles=baseline.double_watermelons;eventIndex=baseline.events.Length;
        UnityEngine.Random.InitState(cfg.future_seed); // NEW experimental future, never historical RNG claim.
        var loop=PlayerLoop.GetCurrentPlayerLoop();if(!Insert(ref loop))throw new Exception("Physics observer insertion failed");PlayerLoop.SetPlayerLoop(loop);Application.targetFrameRate=60;
        using(log=new StreamWriter(new FileStream(cfg.output,FileMode.CreateNew))){wall=System.Diagnostics.Stopwatch.StartNew();Write("root");running=true;
            while(running)yield return null;
            Time.timeScale=0;Write("end");}
        Application.Quit(reason=="error"?2:0);
    }
    void OnGUI(){if(wall==null)return;GUI.Box(new Rect(8,8,600,90),"APPROXIMATE POST-WATERMELON LAB | Esc: stop\nScore "+ScoreManager.Instance.GetScore()+" | additional "+(ScoreManager.Instance.GetScore()-initialScore)+" | drops "+accepted+" | new watermelon "+newCreated+" | doubles "+doubles+"\nMCTS "+cfg.iterations+" depth "+cfg.depth+" | "+planningMs.ToString("F1")+" ms | "+wall.Elapsed.TotalSeconds.ToString("F1")+" s");}
}
