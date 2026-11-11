using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.LowLevel;

// Dedicated frozen V/heuristic comparison. Ordinary game/planners are untouched.
public sealed class SuikaFrozenPairProbe : MonoBehaviour {
    [Serializable] class Config {public string output,bridge,mode="C";public int seed,max_drops=1000;public float max_seconds=540;public bool validate_heuristic;}
    [Serializable] class Command {public int start_tick,drop_tick,completion_tick;public float x,applied_x;}
    [Serializable] class Candidate {public float x,heuristic;public int reward,merges,ticks;public bool go,drop;public ValueSnapshot after;}
    [Serializable] class Request {public int id;public ValueSnapshot state;public Candidate[] candidates;public float native_x;public double native_ms,physics_ms;public int[] public_spawn_types;}
    [Serializable] class Answer {public int id;public float x;public double inference_ms;}
    [Serializable] class Row {public string evt,source="actual_frozen_v_pair",reason,error,mode;public int tick,drops,score,render_frame;public bool game_over,truncated,legacy_compatible;public double wall_ms,actor_ms,bridge_ms,physics_ms,game_time,fixed_time;public long retained_scenes,pending_unloads;public ValueSnapshot state;public Command command;public SuikaEpisodeEvents.Snapshot actual_events;public StepPlanner.Decision planning;}
    static SuikaFrozenPairProbe instance;static string configPath;
    Config cfg;PlayerController player;GameManager game;UDPCommunicatorUnity udp;StreamWriter log;
    System.Diagnostics.Stopwatch wall,bridge;bool running,active,waiting;int tick,drops,dropTick=-1;Command command;Request request;string reason;double actorMs;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaFrozenPair");if(i>=0){configPath=a[i+1];instance=new GameObject("Frozen V paired experiment").AddComponent<SuikaFrozenPairProbe>();}}
    static void Observe(){if(instance!=null)instance.AfterPhysics();}
    static bool Insert(ref PlayerLoopSystem loop){if(loop.subSystemList==null)return false;var list=new List<PlayerLoopSystem>(loop.subSystemList);for(int i=0;i<list.Count;i++){if(list[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate)){list.Insert(i+1,new PlayerLoopSystem{type=typeof(SuikaFrozenPairProbe),updateDelegate=Observe});loop.subSystemList=list.ToArray();return true;}var child=list[i];if(Insert(ref child)){list[i]=child;loop.subSystemList=list.ToArray();return true;}}return false;}
    void Write(Row r){r.tick=tick;r.drops=drops;r.score=ScoreManager.Instance.GetScore();r.render_frame=Time.frameCount;r.game_time=Time.timeAsDouble;r.fixed_time=Time.fixedTimeAsDouble;log.WriteLine(JsonUtility.ToJson(r));log.Flush();}
    void Fail(string why){reason=why;Write(new Row{evt="error",error=why,state=udp.CounterfactualSnapshot()});running=false;Time.timeScale=0;player.StepControlLocked=true;}
    void Update(){
        if(!running)return;if(wall.Elapsed.TotalSeconds>=cfg.max_seconds){reason="wall_limit";running=false;Time.timeScale=0;return;}
        if(game.isGameOver||active)return;if(drops>=cfg.max_drops){reason="drop_limit";running=false;return;}
        try{
            if(waiting){string path=Path.Combine(cfg.bridge,"answer_"+request.id+".json");if(!File.Exists(path))return;var a=JsonUtility.FromJson<Answer>(File.ReadAllText(path));if(a.id!=request.id||a.x<0||a.x>1||Mathf.Abs(a.x*4-Mathf.Round(a.x*4))>1e-5f)throw new Exception("Invalid matched five-candidate answer");
                if(cfg.mode=="D"&&a.x!=request.native_x)throw new Exception("Heuristic actor changed native selection");
                actorMs=cfg.mode=="D"?request.native_ms:request.physics_ms+a.inference_ms;
                Write(new Row{evt="decision",state=request.state,actor_ms=actorMs,bridge_ms=bridge.Elapsed.TotalMilliseconds,physics_ms=request.physics_ms,command=new Command{x=a.x}});
                command=new Command{x=a.x,start_tick=tick+1};active=true;waiting=false;dropTick=-1;Time.timeScale=1;return;
            }
            Time.timeScale=0;var source=udp.CounterfactualSnapshot();string live=SuikaPhysicsSimulator.LiveSignature(player),rng=JsonUtility.ToJson(UnityEngine.Random.state);
            // Synchronous prediction runs on the main thread, with no live tick/yield.
            Time.timeScale=1;player.StepControlLocked=false;var settings=new PlanningSettings{ai_mode="heuristic",candidate_count=5,post_drop_steps=25}.Freeze();
            var timer=System.Diagnostics.Stopwatch.StartNew();var decision=new StepPlanner.Decision{settings=settings,candidates=new StepPlanner.Candidate[5],evaluated_count=5,same_source_verified=true};var cs=new Candidate[5];
            for(int i=0;i<5;i++){
                var r=SuikaPhysicsSimulator.Predict(player,game,i/4f,25,udp.planningFloor);if(!r.source_unchanged)throw new Exception("Prediction contaminated source");
                var e=HeuristicEvaluator.Evaluate(r.evaluation_features,r.reward,settings);
                decision.candidates[i]=new StepPlanner.Candidate{index=i,x=i/4f,success=true,drop_success=r.drop_success,predicted_game_over=r.game_over,source_unchanged=r.source_unchanged,
                    evaluation=e,reward=r.reward,predicted_score=r.score,drop_tick=r.drop_tick,game_over_tick=r.game_over_tick,physics_steps=r.physics_steps,
                    selection_score_json=r.game_over||!r.drop_success?"null":e.value.ToString("R",System.Globalization.CultureInfo.InvariantCulture)};
                cs[i]=new Candidate{x=i/4f,reward=r.reward,merges=r.merges,ticks=r.physics_steps,go=r.game_over,drop=r.drop_success,after=r.value_state,heuristic=e.value};
            }
            double physicsMs=timer.Elapsed.TotalMilliseconds;StepPlanner.Choose(decision);double nativeMs=timer.Elapsed.TotalMilliseconds;if(decision.selected_index<0)throw new Exception("No native heuristic action");
            bool compatible=true;
            if(cfg.validate_heuristic){
                var legacy=StepPlanner.Plan(player,game,udp.planningFloor,settings);compatible=legacy.selected_index==decision.selected_index&&legacy.selected_x==decision.selected_x;
                for(int i=0;i<5;i++){var a=legacy.candidates[i];var b=decision.candidates[i];compatible&=a.success==b.success&&a.drop_success==b.drop_success&&a.predicted_game_over==b.predicted_game_over&&a.reward==b.reward&&a.drop_tick==b.drop_tick&&a.game_over_tick==b.game_over_tick&&a.physics_steps==b.physics_steps&&a.evaluation.value==b.evaluation.value;}
                if(!compatible)throw new Exception("Unified candidates differ from existing StepPlanner");
            }
            Time.timeScale=0;player.StepControlLocked=true;if(live!=SuikaPhysicsSimulator.LiveSignature(player)||rng!=JsonUtility.ToJson(UnityEngine.Random.state))throw new Exception("Prediction changed live state/RNG");
            Write(new Row{evt="native_plan",planning=decision,legacy_compatible=compatible});
            request=new Request{id=drops+1,state=source,candidates=cs,native_x=decision.selected_x,native_ms=nativeMs,physics_ms=physicsMs,public_spawn_types=new int[player.fruits.Length]};for(int i=0;i<player.fruits.Length;i++)request.public_spawn_types[i]=player.fruits[i].GetComponent<FruitEvolution>().fruitType;
            string dst=Path.Combine(cfg.bridge,"request_"+request.id+".json");File.WriteAllText(dst+".tmp",JsonUtility.ToJson(request));File.Move(dst+".tmp",dst);bridge=System.Diagnostics.Stopwatch.StartNew();waiting=true;
        }catch(Exception e){Fail(e.ToString());}
    }
    void FixedUpdate(){
        if(!running)return;tick++;if(game.isGameOver||!active||dropTick>=0)return;
        var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,command.x),x=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(x,range,out error)){Fail(error);return;}if(x!=target||!player.CanDropFruit)return;
        float applied;long id;if(!player.TryDropAt(command.x,out applied,out id,out range,out error)){Fail(error);return;}command.applied_x=applied;command.drop_tick=dropTick=tick;
    }
    void AfterPhysics(){if(!running||dropTick<0||tick-dropTick!=25)return;command.completion_tick=tick;drops++;active=false;dropTick=-1;Time.timeScale=0;Write(new Row{evt="action",command=command,state=udp.CounterfactualSnapshot(),actor_ms=actorMs,actual_events=ScoreManager.Instance.EpisodeEvents.Read(),retained_scenes=PredictionLifecycle.RetainedScenes,pending_unloads=PredictionLifecycle.Pending});}
    IEnumerator Start(){
        yield return null;yield return null;cfg=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));if(cfg.max_seconds<=0||cfg.max_seconds>600||!(cfg.mode=="C"||cfg.mode=="D"))throw new Exception("Bounded frozen pair config required");
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();Directory.CreateDirectory(cfg.bridge);var loop=PlayerLoop.GetCurrentPlayerLoop();if(!Insert(ref loop))throw new Exception("No physics loop");PlayerLoop.SetPlayerLoop(loop);Application.targetFrameRate=60;player.StepControlLocked=true;
        Time.timeScale=0;UnityEngine.Random.InitState(cfg.seed);for(int i=0;i<2;i++)UnityEngine.Random.Range(0,player.fruits.Length);game.ResetGame("frozen-v-pair");Time.timeScale=0;yield return null;yield return null;
        using(log=new StreamWriter(new FileStream(cfg.output,FileMode.CreateNew))){Write(new Row{evt="start",state=udp.CounterfactualSnapshot(),mode=cfg.mode});wall=System.Diagnostics.Stopwatch.StartNew();running=true;while(running&&!game.isGameOver)yield return null;
            running=false;Time.timeScale=0;yield return null;bool natural=game.isGameOver&&reason==null;Write(new Row{evt="end",state=udp.CounterfactualSnapshot(),game_over=natural,truncated=!natural,reason=natural?"natural_go":reason,wall_ms=wall.Elapsed.TotalMilliseconds,actual_events=ScoreManager.Instance.EpisodeEvents.Read(),retained_scenes=PredictionLifecycle.RetainedScenes,pending_unloads=PredictionLifecycle.Pending});}
        Application.Quit(reason!=null&&reason!="wall_limit"&&reason!="drop_limit"?2:0);
    }
}
