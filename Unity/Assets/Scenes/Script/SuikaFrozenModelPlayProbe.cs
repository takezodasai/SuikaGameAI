using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.LowLevel;

// Opt-in experiment only. Normal UDP/planner/game paths are untouched.
public sealed class SuikaFrozenModelPlayProbe : MonoBehaviour {
    [Serializable] class Config {public string output,bridge,mode="Q",reference="",prefix_mode="B";public int seed,prefix_drops,future_seed,max_drops=600;public float candidate_x=-1,max_seconds=450;public bool prefix_only,replay_shadow;}
    [Serializable] public class Command {public int start_tick,drop_tick,completion_tick;public float x,applied_x;}
    [Serializable] class Candidate {public float x,heuristic;public int reward,merges,ticks;public bool go,drop;public ValueSnapshot after;}
    [Serializable] class Request {public int id;public ValueSnapshot state;public Candidate[] candidates;public float native_x;public double native_ms,physics_ms;public int[] public_spawn_types;}
    [Serializable] class Answer {public int id;public float x;public double inference_ms;}
    [Serializable] class Signature {public PredictionDiagnostics.Frame frame;public int held,next;public float held_x,held_y,cooldown;public string rng;}
    [Serializable] class Row {public string evt,source="actual_frozen_model_game",hash,rng,reason,error,mode;public int tick,drops,score,merges;public bool game_over,truncated,prefix_verified;public double wall_ms,actor_ms,bridge_ms,physics_ms;public long retained_scenes,pending_unloads;public ValueSnapshot state;public PredictionDiagnostics.Frame bodies;public Command command;public SuikaEpisodeEvents.Snapshot actual_events;public StepPlanner.Decision planning;public MctsPlanner.Report mcts;}
    static SuikaFrozenModelPlayProbe instance;static string configPath;
    Config cfg;PlayerController player;GameManager game;UDPCommunicatorUnity udp;StreamWriter log;SHA256 sha;System.Diagnostics.Stopwatch wall,bridge;
    bool running,active,waiting;int tick,drops,dropTick=-1;Command command;Answer answer;Request request;string reason;double actorMs,physicsMs;
    readonly List<Command> schedule=new List<Command>();readonly Dictionary<int,string> expected=new Dictionary<int,string>();
    bool Replaying {get{return drops<cfg.prefix_drops;}}
    bool Verified {get{return cfg.reference!=""&&drops>=cfg.prefix_drops;}}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaFrozenModelPlay");if(i>=0){configPath=args[i+1];instance=new GameObject("Frozen model actual experiment").AddComponent<SuikaFrozenModelPlayProbe>();}}
    static void Observe(){if(instance!=null)instance.AfterPhysics();}
    static bool Insert(ref PlayerLoopSystem loop){if(loop.subSystemList==null)return false;var list=new List<PlayerLoopSystem>(loop.subSystemList);for(int i=0;i<list.Count;i++){if(list[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate)){list.Insert(i+1,new PlayerLoopSystem{type=typeof(SuikaFrozenModelPlayProbe),updateDelegate=Observe});loop.subSystemList=list.ToArray();return true;}var child=list[i];if(Insert(ref child)){list[i]=child;loop.subSystemList=list.ToArray();return true;}}return false;}
    void Write(Row r){r.tick=tick;r.drops=drops;r.score=ScoreManager.Instance.GetScore();r.prefix_verified=Verified;log.WriteLine(JsonUtility.ToJson(r));log.Flush();}
    void Fail(string why){reason=why;Write(new Row{evt="error",error=why});running=false;Time.timeScale=0;}
    void Activate(float x){command=new Command{x=x,start_tick=tick+1};active=true;waiting=false;dropTick=-1;Time.timeScale=1;}
    void Update(){
        if(!running)return;
        if(wall.Elapsed.TotalSeconds>=cfg.max_seconds){reason="wall_limit";running=false;Time.timeScale=0;return;}
        if(game.isGameOver||active)return;
        if(Replaying&&!cfg.replay_shadow){Time.timeScale=1;return;}
        if(drops>=cfg.max_drops){reason="drop_limit";running=false;return;}
        try{
            if(waiting){string p=Path.Combine(cfg.bridge,"answer_"+request.id+".json");if(!File.Exists(p))return;answer=JsonUtility.FromJson<Answer>(File.ReadAllText(p));if(answer.id!=request.id||answer.x<0||answer.x>1||Mathf.Abs(answer.x*4-Mathf.Round(answer.x*4))>1e-5f)throw new Exception("Invalid matched fixed-five answer");
                actorMs=(cfg.mode=="A"||cfg.mode=="D")?request.native_ms:answer.inference_ms+(cfg.mode=="C"?physicsMs:0);
                if(Replaying&&cfg.replay_shadow){if(tick+1!=schedule[drops].start_tick)throw new Exception("prefix_action_start_tick_mismatch");answer.x=schedule[drops].x;}
                Write(new Row{evt="decision",state=request.state,actor_ms=actorMs,bridge_ms=bridge.Elapsed.TotalMilliseconds,physics_ms=physicsMs,command=new Command{x=answer.x}});Activate(answer.x);return;}
            Time.timeScale=0;
            if(cfg.reference!=""&&drops==cfg.prefix_drops&&cfg.candidate_x>=0){float x=cfg.candidate_x;cfg.candidate_x=-1;actorMs=0;Activate(x);return;}
            var source=udp.CounterfactualSnapshot();string rng=JsonUtility.ToJson(UnityEngine.Random.state),live=SuikaPhysicsSimulator.LiveSignature(player);
            // Predict requires an idle scale=1 clock. These synchronous main-thread
            // calls cannot run live physics; pause again before yielding to Python.
            Time.timeScale=1;player.StepControlLocked=false;
            float nativeX=0;double nativeMs=0;StepPlanner.Decision plan=null;
            string currentMode=Replaying&&cfg.replay_shadow?cfg.prefix_mode:cfg.mode;
            if(currentMode=="A"||currentMode=="D"){
                plan=StepPlanner.Plan(player,game,udp.planningFloor,new PlanningSettings{ai_mode=currentMode=="A"?"mcts":"heuristic",candidate_count=5,post_drop_steps=25,mcts_iterations=128,mcts_max_depth=4,mcts_seed=8191});
                if(plan.selected_index<0)throw new Exception("No native action");nativeX=plan.selected_x;nativeMs=plan.elapsed_ms;
            }
            var cs=new List<Candidate>();var sw=System.Diagnostics.Stopwatch.StartNew();
            for(int i=0;i<5;i++){var r=SuikaPhysicsSimulator.Predict(player,game,i/4f,25,udp.planningFloor);if(!r.source_unchanged)throw new Exception("Prediction changed live source");cs.Add(new Candidate{x=i/4f,reward=r.reward,merges=r.merges,ticks=r.physics_steps,go=r.game_over,drop=r.drop_success,after=r.value_state,heuristic=HeuristicEvaluator.Evaluate(r.evaluation_features,r.reward,new PlanningSettings()).value});}
            physicsMs=sw.Elapsed.TotalMilliseconds;Time.timeScale=0;player.StepControlLocked=true;
            if(live!=SuikaPhysicsSimulator.LiveSignature(player)||rng!=JsonUtility.ToJson(UnityEngine.Random.state))throw new Exception("Shadow prediction contaminated live state/RNG");
            request=new Request{id=drops+1,state=source,candidates=cs.ToArray(),native_x=nativeX,native_ms=nativeMs,physics_ms=physicsMs,public_spawn_types=new int[player.fruits.Length]};for(int i=0;i<player.fruits.Length;i++)request.public_spawn_types[i]=player.fruits[i].GetComponent<FruitEvolution>().fruitType;
            if(plan!=null)Write(new Row{evt="native_plan",planning=plan,mcts=plan.mcts});
            string path=Path.Combine(cfg.bridge,"request_"+request.id+".json");File.WriteAllText(path+".tmp",JsonUtility.ToJson(request));File.Move(path+".tmp",path);bridge=System.Diagnostics.Stopwatch.StartNew();waiting=true;
        }catch(Exception e){player.StepControlLocked=true;Fail(e.ToString());}
    }
    void FixedUpdate(){
        if(!running)return;tick++;if(game.isGameOver)return;
        if(Replaying&&!active&&tick==schedule[drops].start_tick){Activate(schedule[drops].x);command.start_tick=tick;}
        if(!active||dropTick>=0)return;
        var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,command.x),x=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(x,range,out error)){Fail(error);return;}
        bool release=Replaying?tick==schedule[drops].drop_tick:x==target&&player.CanDropFruit;
        if(!release)return;if(x!=target||!player.CanDropFruit){Fail("recorded_drop_not_legal");return;}
        float applied;long id;if(!player.TryDropAt(command.x,out applied,out id,out range,out error)){Fail(error);return;}command.applied_x=applied;command.drop_tick=dropTick=tick;
    }
    void AfterPhysics(){
        if(!running)return;var rec=PredictionDiagnostics.Live;
        if(player.currentFruit!=null){var f=player.currentFruit.GetComponent<FruitEvolution>();if(!rec.aliases.ContainsKey(f))rec.Watch(f,"d"+(dropTick>=0?drops+1:drops));}
        rec.Capture(ScoreManager.Instance.GetScore(),game.isGameOver);var frame=rec.frames[0];frame.tick=tick;frame.render_frame=0;foreach(var f in frame.fruits)f.observation_id=0;
        string rng=JsonUtility.ToJson(UnityEngine.Random.state);var held=player.currentFruit;var sig=new Signature{frame=frame,held=held.GetComponent<FruitEvolution>().fruitType,next=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType,held_x=held.transform.position.x,held_y=held.transform.position.y,cooldown=player.DropCooldownRemaining,rng=rng};string digest=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(JsonUtility.ToJson(sig)))).Replace("-","");
        Write(new Row{evt="tick",hash=digest});
        if(Replaying&&(!expected.ContainsKey(tick)||expected[tick]!=digest)){Fail("prefix_mismatch");rec.frames.Clear();rec.history.Clear();return;}
        if(dropTick>=0&&tick-dropTick==25){command.completion_tick=tick;drops++;active=false;dropTick=-1;Time.timeScale=0;Write(new Row{evt="action",command=command,state=udp.CounterfactualSnapshot(),bodies=frame,rng=rng,actor_ms=actorMs,actual_events=ScoreManager.Instance.EpisodeEvents.Read(),retained_scenes=PredictionLifecycle.RetainedScenes,pending_unloads=PredictionLifecycle.Pending});
            if(cfg.reference!=""&&drops==cfg.prefix_drops){Write(new Row{evt="branch_root",state=udp.CounterfactualSnapshot(),bodies=frame,rng=rng});if(cfg.prefix_only){reason="prefix_complete";running=false;}else UnityEngine.Random.InitState(cfg.future_seed);}}
        rec.frames.Clear();rec.history.Clear();
    }
    IEnumerator Start(){
        yield return null;yield return null;cfg=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));if(cfg.max_seconds<=0||cfg.max_seconds>1200||!(cfg.mode=="A"||cfg.mode=="B"||cfg.mode=="C"||cfg.mode=="D"))throw new Exception("Bounded experiment configuration required");
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        if(cfg.reference!="")foreach(var line in File.ReadLines(cfg.reference)){var r=JsonUtility.FromJson<Row>(line);if(r.evt=="tick")expected[r.tick]=r.hash;if(r.evt=="action")schedule.Add(r.command);}if(cfg.prefix_drops>schedule.Count)throw new Exception("Insufficient prefix schedule");
        Directory.CreateDirectory(cfg.bridge);var loop=PlayerLoop.GetCurrentPlayerLoop();if(!Insert(ref loop))throw new Exception("No physics loop");PlayerLoop.SetPlayerLoop(loop);Application.targetFrameRate=60;player.StepControlLocked=true;
        Time.timeScale=0;UnityEngine.Random.InitState(cfg.seed);for(int i=0;i<2;i++)UnityEngine.Random.Range(0,player.fruits.Length);game.ResetGame("frozen-model-experiment");Time.timeScale=0;yield return null;yield return null;
        using(log=new StreamWriter(new FileStream(cfg.output,FileMode.CreateNew)))using(sha=SHA256.Create()){
            PredictionDiagnostics.BeginAliases(player,game);PredictionDiagnostics.Live.aliases.Clear();PredictionDiagnostics.Live.Watch(player.currentFruit.GetComponent<FruitEvolution>(),"d0");Write(new Row{evt="start",state=udp.CounterfactualSnapshot(),rng=JsonUtility.ToJson(UnityEngine.Random.state),mode=cfg.mode});wall=System.Diagnostics.Stopwatch.StartNew();running=true;
            while(running&&!game.isGameOver)yield return null;
            running=false;Time.timeScale=0;yield return null;bool natural=game.isGameOver&&reason==null;
            Write(new Row{evt="end",state=udp.CounterfactualSnapshot(),game_over=natural,truncated=!natural,reason=natural?"natural_go":reason,wall_ms=wall.Elapsed.TotalMilliseconds,actual_events=ScoreManager.Instance.EpisodeEvents.Read(),merges=ScoreManager.Instance.EpisodeMergeCount,retained_scenes=PredictionLifecycle.RetainedScenes,pending_unloads=PredictionLifecycle.Pending});
        }
        PredictionDiagnostics.Stop();Application.Quit(reason!=null&&reason!="wall_limit"&&reason!="drop_limit"&&reason!="prefix_complete"?2:0);
    }
}
