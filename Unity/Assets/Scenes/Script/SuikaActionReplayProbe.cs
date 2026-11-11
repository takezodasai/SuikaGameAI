using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.LowLevel;

// Opt-in actual-world reset/replay. No reconstructed body, prediction Scene or AI change.
public sealed class SuikaActionReplayProbe : MonoBehaviour {
    [Serializable] class Config {public string output;public int[] seeds;public float[] positions;public int repeats=3;}
    [Serializable] class Action {public int start_tick,drop_tick,completion_tick;public float x,applied_x;}
    [Serializable] class Row {
        public string evt,source="actual_game_from_reset",phase="after Physics2DFixedUpdate, before Update",rng,error;
        public int seed,repeat,tick,action;public bool game_over,truncated;public double relative_game_time,relative_fixed_time,wall_ms;
        public ValueSnapshot state;public PredictionDiagnostics.Frame bodies;public Action[] commands;
    }
    static SuikaActionReplayProbe instance;static string configPath;
    PlayerController player;GameManager game;UDPCommunicatorUnity udp;StreamWriter writer;Config config;
    bool running,moving;int tick,index,dropTick=-1,seed,repeat;double baseGame,baseFixed;List<Action> baseline,commands;
    Action command;System.Diagnostics.Stopwatch timer;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaActionReplay");if(i<0)return;
        configPath=args[i+1];instance=new GameObject("Opt-in actual action replay").AddComponent<SuikaActionReplayProbe>();
    }
    static void Observe(){if(instance!=null)instance.AfterPhysics();}
    static bool Insert(ref PlayerLoopSystem loop) {
        if(loop.subSystemList==null)return false;var list=new List<PlayerLoopSystem>(loop.subSystemList);
        for(int i=0;i<list.Count;i++) {
            if(list[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate)){list.Insert(i+1,new PlayerLoopSystem {type=typeof(SuikaActionReplayProbe),updateDelegate=Observe});loop.subSystemList=list.ToArray();return true;}
            var child=list[i];if(Insert(ref child)){list[i]=child;loop.subSystemList=list.ToArray();return true;}
        }return false;
    }
    void Write(Row row){row.seed=seed;row.repeat=repeat;writer.WriteLine(JsonUtility.ToJson(row));}
    void FixedUpdate() {
        if(!running)return;tick++;
        if(game.isGameOver){running=false;return;}
        if(index>=config.positions.Length)return;
        int start=repeat==0?(commands.Count==0?1:commands[commands.Count-1].completion_tick+1):baseline[index].start_tick;
        if(tick==start){moving=true;dropTick=-1;command=new Action {x=config.positions[index],start_tick=tick};}
        if(!moving||dropTick>=0)return;
        var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,command.x);
        float next=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(next,range,out error)){Fail(error);return;}
        bool scheduled=repeat==0?next==target&&player.CanDropFruit:tick==baseline[index].drop_tick;
        if(!scheduled)return;
        if(next!=target||!player.CanDropFruit){Fail("Replayed drop is not legal at original tick");return;}
        float applied;long id;if(!player.TryDropAt(command.x,out applied,out id,out range,out error)){Fail(error);return;}
        dropTick=tick;command.drop_tick=tick;command.applied_x=applied;
    }
    void Fail(string error){Write(new Row {evt="error",tick=tick,action=index,error=error});running=false;}
    void AfterPhysics() {
        if(!running)return;
        var recorder=PredictionDiagnostics.Live;
        if(player.currentFruit!=null){var f=player.currentFruit.GetComponent<FruitEvolution>();if(!recorder.aliases.ContainsKey(f))recorder.Watch(f,"d"+(dropTick>=0?index+1:index));}
        recorder.Capture(ScoreManager.Instance.GetScore(),game.isGameOver);var frame=recorder.frames[recorder.frames.Count-1];frame.tick=tick;
        Write(new Row {evt="tick",tick=tick,action=index,relative_game_time=Time.timeAsDouble-baseGame,relative_fixed_time=Time.fixedTimeAsDouble-baseFixed,state=udp.CounterfactualSnapshot(),bodies=frame,rng=JsonUtility.ToJson(UnityEngine.Random.state)});
        recorder.frames.Clear();recorder.history.Clear();
        if(dropTick>=0&&tick-dropTick==25) {
            command.completion_tick=tick;commands.Add(command);index++;moving=false;dropTick=-1;writer.Flush();
            if(index==config.positions.Length){running=false;Time.timeScale=0;}
        }
        if(tick>5000)Fail("Bounded replay tick limit");
    }
    IEnumerator Start() {
        yield return null;yield return null;config=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        if(config.repeats<1||config.repeats>3||config.positions.Length>24||config.seeds.Length>3)throw new ArgumentException("Bounded diagnostic only");
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        var loop=PlayerLoop.GetCurrentPlayerLoop();if(!Insert(ref loop))throw new Exception("No Physics2D loop");PlayerLoop.SetPlayerLoop(loop);
        Application.targetFrameRate=60;player.StepControlLocked=true;
        using(writer=new StreamWriter(new FileStream(config.output,FileMode.CreateNew)))foreach(int s in config.seeds) {
            seed=s;baseline=null;
            for(repeat=0;repeat<config.repeats;repeat++) {
                PredictionDiagnostics.Stop();Time.timeScale=0;UnityEngine.Random.InitState(seed);game.ResetGame("replay-audit");Time.timeScale=0;
                yield return null;yield return null;
                tick=0;index=0;dropTick=-1;moving=false;commands=new List<Action>();baseGame=Time.timeAsDouble;baseFixed=Time.fixedTimeAsDouble;timer=System.Diagnostics.Stopwatch.StartNew();
                PredictionDiagnostics.BeginAliases(player,game);PredictionDiagnostics.Live.aliases.Clear();PredictionDiagnostics.Live.Watch(player.currentFruit.GetComponent<FruitEvolution>(),"d0");
                Write(new Row {evt="start",state=udp.CounterfactualSnapshot(),rng=JsonUtility.ToJson(UnityEngine.Random.state)});running=true;Time.timeScale=1;
                while(running&&!game.isGameOver)yield return null;
                running=false;Time.timeScale=0;yield return null;
                Write(new Row {evt="end",tick=tick,action=index,state=udp.CounterfactualSnapshot(),game_over=game.isGameOver,truncated=index==config.positions.Length&&!game.isGameOver,wall_ms=timer.Elapsed.TotalMilliseconds,commands=commands.ToArray()});writer.Flush();
                if(repeat==0)baseline=new List<Action>(commands);
                if(commands.Count!=config.positions.Length){Application.Quit(2);yield break;}
            }
        }
        PredictionDiagnostics.Stop();Application.Quit(0);
    }
}
