using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using UnityEngine;
using UnityEngine.LowLevel;

// Separate, opt-in actual-world reference/replay. No changes to game or planners.
public sealed class SuikaFreshBranchProbe : MonoBehaviour {
    [Serializable] class Config {public string output,reference;public int seed,startup_draws=2,max_ticks=25000,max_drops=600,future_seed;public float[] positions;public bool continue_after_prefix,abort_on_mismatch=true;public float candidate_x=.5f,max_seconds=300;}
    [Serializable] class Action {public int start_tick,drop_tick,completion_tick;public float x,applied_x;public double planning_ms;}
    [Serializable] class Row {public string evt,source="actual_fresh_process_game",hash,rng,error,reason,build_guid;public string[] events;public int tick,drops,score,fruit_count,merges,watermelons;public bool prefix_verified,prefix_complete,game_over,truncated,mc_return_known,go_candidate;public float max_y,armed_max_y;public double wall_ms;public ValueSnapshot state;public PredictionDiagnostics.Frame bodies;public Action[] commands;}
    [Serializable] class Signature {public PredictionDiagnostics.Frame frame;public int held,next;public float held_x,held_y,cooldown;public string rng;}
    static SuikaFreshBranchProbe instance;static string path;
    Config cfg;PlayerController player;GameManager game;UDPCommunicatorUnity udp;StreamWriter writer;SHA256 sha;System.Diagnostics.Stopwatch timer;
    int tick,drops,dropTick=-1,mismatches;bool running,active,prefixComplete;Action command;readonly List<Action> commands=new List<Action>();readonly Dictionary<int,string> expected=new Dictionary<int,string>();Action[] schedule;string reason;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaFreshBranch");if(i<0)return;path=a[i+1];instance=new GameObject("Opt-in fresh actual branch").AddComponent<SuikaFreshBranchProbe>();}
    static void Observe(){if(instance!=null)instance.AfterPhysics();}
    static bool Insert(ref PlayerLoopSystem loop){if(loop.subSystemList==null)return false;var list=new List<PlayerLoopSystem>(loop.subSystemList);for(int i=0;i<list.Count;i++){if(list[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate)){list.Insert(i+1,new PlayerLoopSystem {type=typeof(SuikaFreshBranchProbe),updateDelegate=Observe});loop.subSystemList=list.ToArray();return true;}var child=list[i];if(Insert(ref child)){list[i]=child;loop.subSystemList=list.ToArray();return true;}}return false;}
    bool Verified {get{return !String.IsNullOrEmpty(cfg.reference)&&mismatches==0&&prefixComplete;}}
    void Write(Row row){row.tick=tick;row.drops=drops;row.score=ScoreManager.Instance.GetScore();row.prefix_verified=Verified;row.prefix_complete=prefixComplete;writer.WriteLine(JsonUtility.ToJson(row));}
    void Fail(string why){reason=why;Write(new Row {evt="error",error=why,state=udp.CounterfactualSnapshot()});running=false;}
    void Activate(float x,double ms=0){command=new Action {x=x,start_tick=tick+1,planning_ms=ms};active=true;dropTick=-1;}
    void Update(){
        if(!running)return;
        if(timer.Elapsed.TotalSeconds>=cfg.max_seconds){reason="wall_limit";running=false;return;}
        if(!prefixComplete||active||game.isGameOver)return;
        if(drops>=cfg.max_drops){reason="drop_limit";running=false;return;}
        try{var d=StepPlanner.Plan(player,game,udp.planningFloor,new PlanningSettings {ai_mode="heuristic",candidate_count=5,post_drop_steps=25});if(d.selected_index<0){Fail("no_planner_action");return;}Activate(d.selected_x,d.elapsed_ms);}catch(Exception e){Fail("planner:"+e.Message);}
    }
    void FixedUpdate(){
        if(!running)return;tick++;if(game.isGameOver)return;
        if(tick>cfg.max_ticks){Fail("tick_limit");return;}
        if(!prefixComplete&&!active){int start=schedule==null?(commands.Count==0?1:commands[commands.Count-1].completion_tick+1):schedule[drops].start_tick;if(tick==start){Activate(cfg.positions[drops]);command.start_tick=tick;}}
        if(!active||dropTick>=0)return;
        var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,command.x),x=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(x,range,out error)){Fail(error);return;}
        bool release=!prefixComplete&&schedule!=null?tick==schedule[drops].drop_tick:x==target&&player.CanDropFruit;
        if(!release)return;
        if(x!=target||!player.CanDropFruit){Fail("recorded_drop_not_legal");return;}
        float applied;long id;if(!player.TryDropAt(command.x,out applied,out id,out range,out error)){Fail(error);return;}command.applied_x=applied;command.drop_tick=dropTick=tick;
    }
    void AfterPhysics(){
        if(!running)return;var rec=PredictionDiagnostics.Live;
        if(player.currentFruit!=null){var f=player.currentFruit.GetComponent<FruitEvolution>();if(!rec.aliases.ContainsKey(f))rec.Watch(f,"d"+(dropTick>=0?drops+1:drops));}
        rec.Capture(ScoreManager.Instance.GetScore(),game.isGameOver);var frame=rec.frames[0];frame.tick=tick;frame.render_frame=0;foreach(var f in frame.fruits)f.observation_id=0;
        string rng=JsonUtility.ToJson(UnityEngine.Random.state);string digest=null;
        if(!prefixComplete){
            var h=player.currentFruit;var sig=new Signature {frame=frame,held=h.GetComponent<FruitEvolution>().fruitType,next=player.nextFruitObject.GetComponent<FruitEvolution>().fruitType,held_x=h.transform.position.x,held_y=h.transform.position.y,cooldown=player.DropCooldownRemaining,rng=rng};
            digest=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(JsonUtility.ToJson(sig)))).Replace("-","");
            int count=0,wm=0;float top=-999,armed=-999;foreach(var f in frame.fruits)if(!f.preview&&!f.merging){count++;if(f.type==10)wm++;top=Mathf.Max(top,f.position.y);if(f.has_collided&&f.tag_eligible)armed=Mathf.Max(armed,f.position.y);}
            Write(new Row {evt="prefix_tick",hash=digest,rng=rng,events=frame.events,fruit_count=count,watermelons=wm,max_y=top,armed_max_y=armed,go_candidate=frame.game_over_candidate});
            if(!String.IsNullOrEmpty(cfg.reference)&&(!expected.ContainsKey(tick)||expected[tick]!=digest)){
                mismatches++;if(mismatches==1)Write(new Row {evt="prefix_mismatch",hash=digest,rng=rng,state=udp.CounterfactualSnapshot(),bodies=frame});
                if(cfg.abort_on_mismatch){Fail("prefix_mismatch");rec.frames.Clear();return;}
            }
        }
        if(dropTick>=0&&tick-dropTick==25){
            command.completion_tick=tick;commands.Add(command);drops++;active=false;dropTick=-1;var state=udp.CounterfactualSnapshot();float maxY=-999;foreach(var f in state.fruits)maxY=Mathf.Max(maxY,f.y);
            Write(new Row {evt="action",state=state,bodies=frame,rng=rng,merges=ScoreManager.Instance.EpisodeMergeCount,fruit_count=state.fruits.Length,max_y=maxY,commands=new[]{command}});writer.Flush();
            if(!prefixComplete&&drops==cfg.positions.Length){
                prefixComplete=true;Write(new Row {evt="root",state=state,bodies=frame,rng=rng,commands=commands.ToArray(),fruit_count=state.fruits.Length,max_y=maxY});writer.Flush();
                if(!cfg.continue_after_prefix){reason="prefix_complete";running=false;Time.timeScale=0;}
                else if(!Verified||frame.game_over_candidate){Fail("unverified_or_unsafe_root");}
                else{UnityEngine.Random.InitState(cfg.future_seed);Activate(cfg.candidate_x);}
            }
        }
        rec.frames.Clear();rec.history.Clear();
    }
    IEnumerator Start(){
        yield return null;yield return null;cfg=JsonUtility.FromJson<Config>(File.ReadAllText(path));
        if(cfg.positions==null||cfg.positions.Length<24||cfg.positions.Length>400||cfg.max_seconds<=0||cfg.max_seconds>420)throw new ArgumentException("Bounded fresh prefix required");
        if(cfg.continue_after_prefix&&String.IsNullOrEmpty(cfg.reference))throw new ArgumentException("Verified reference required for continuation");
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        if(!String.IsNullOrEmpty(cfg.reference))foreach(var line in File.ReadLines(cfg.reference)){var r=JsonUtility.FromJson<Row>(line);if(r.evt=="prefix_tick")expected[r.tick]=r.hash;if((r.evt=="root"||r.evt=="end")&&r.commands!=null&&r.commands.Length>=cfg.positions.Length){schedule=new Action[cfg.positions.Length];Array.Copy(r.commands,schedule,schedule.Length);}}
        if(!String.IsNullOrEmpty(cfg.reference)&&schedule==null)throw new Exception("Reference does not contain requested prefix");
        var loop=PlayerLoop.GetCurrentPlayerLoop();if(!Insert(ref loop))throw new Exception("Physics loop missing");PlayerLoop.SetPlayerLoop(loop);Application.targetFrameRate=60;player.StepControlLocked=true;
        Time.timeScale=0;UnityEngine.Random.InitState(cfg.seed);for(int i=0;i<cfg.startup_draws;i++)UnityEngine.Random.Range(0,player.fruits.Length);game.ResetGame("fresh-branch");Time.timeScale=0;yield return null;yield return null;
        using(writer=new StreamWriter(new FileStream(cfg.output,FileMode.CreateNew)))using(sha=SHA256.Create()){
            PredictionDiagnostics.BeginAliases(player,game);PredictionDiagnostics.Live.aliases.Clear();PredictionDiagnostics.Live.Watch(player.currentFruit.GetComponent<FruitEvolution>(),"d0");
            Write(new Row {evt="start",state=udp.CounterfactualSnapshot(),rng=JsonUtility.ToJson(UnityEngine.Random.state),build_guid=Application.buildGUID});timer=System.Diagnostics.Stopwatch.StartNew();running=true;Time.timeScale=1;
            while(running&&!game.isGameOver)yield return null;
            running=false;Time.timeScale=0;yield return null;bool limited=reason=="wall_limit"||reason=="drop_limit"||reason=="tick_limit";bool natural=game.isGameOver&&!limited;
            Write(new Row {evt="end",state=udp.CounterfactualSnapshot(),game_over=natural,truncated=!natural,mc_return_known=natural&&Verified&&cfg.continue_after_prefix,reason=natural?"natural_go":reason,wall_ms=timer.Elapsed.TotalMilliseconds,commands=commands.ToArray(),merges=ScoreManager.Instance.EpisodeMergeCount});writer.Flush();
        }
        PredictionDiagnostics.Stop();Application.Quit(reason!=null&&(reason.StartsWith("prefix_mismatch")||reason=="recorded_drop_not_legal")?2:0);
    }
}
