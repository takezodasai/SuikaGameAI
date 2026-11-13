using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Explicit command-line diagnostic only. No component/file scan in ordinary play.
public sealed class SuikaRuntimeProbe : MonoBehaviour
{
    public static SuikaRuntimeProbe Instance {get;private set;}
    public static long Packets;
    StreamWriter log;string fixturePath;public string LastFixtureRequest,LastSweepRequest;
    long fixedCalls,updateCalls;double lastUpdate,lastFixed,lastWrite;
    readonly List<double> updates=new List<double>(),fixedGaps=new List<double>();
    readonly List<double> captures=new List<double>(),callbacks=new List<double>(),publishes=new List<double>();
    public void RecordVideo(double capture,double callback,double publish){if(captures.Count>=4096)return;captures.Add(capture);callbacks.Add(callback);publishes.Add(publish);}
    static double Now {get{return (double)System.Diagnostics.Stopwatch.GetTimestamp()/System.Diagnostics.Stopwatch.Frequency;}}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install()
    {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaRuntimeProbe");if(i<0)return;
        if(i+1>=args.Length)throw new ArgumentException("Probe output required");
        BeginDemo(args[i+1]);var p=Instance;
        MctsPerformance.Optimized=Array.IndexOf(args,"-suikaMctsBaseline")<0;
        int j=Array.IndexOf(args,"-suikaProbeFixture");p.fixturePath=j>=0?args[j+1]:null;
    }
    public static void BeginDemo(string path){
        if(Instance!=null)throw new InvalidOperationException("Runtime probe already active");
        var obj=new GameObject("Opt-in runtime measurement");var p=obj.AddComponent<SuikaRuntimeProbe>();Instance=p;
        Directory.CreateDirectory(Path.GetDirectoryName(path));p.log=new StreamWriter(new FileStream(path,FileMode.CreateNew));
        MctsPerformance.Optimized=true;
        p.Write(new Header {evt="start",thread=System.Threading.Thread.CurrentThread.ManagedThreadId,dt=Time.fixedDeltaTime,maximum_delta=Time.maximumDeltaTime});
    }
    [Serializable] class Header {public string evt;public int thread;public float dt,maximum_delta;}
    double serializeMax,writeMax,udpMax;int serializeGc,writeGc,udpGc;
    public void Write(object row)
    {
        if(log==null)return;double t=Now;int gc=GC.CollectionCount(0);string json=JsonUtility.ToJson(row);
        double ms=(Now-t)*1000;if(ms>serializeMax){serializeMax=ms;serializeGc=GC.CollectionCount(0)-gc;}
        t=Now;gc=GC.CollectionCount(0);log.WriteLine(json);log.Flush();ms=(Now-t)*1000;
        if(ms>writeMax){writeMax=ms;writeGc=GC.CollectionCount(0)-gc;}
    }
    public struct UdpSpan : IDisposable
    {
        readonly SuikaRuntimeProbe probe;readonly double time;readonly int gc;
        public UdpSpan(SuikaRuntimeProbe p){probe=p;time=Now;gc=GC.CollectionCount(0);}
        public void Dispose(){if(probe==null)return;double ms=(Now-time)*1000;if(ms>probe.udpMax){probe.udpMax=ms;probe.udpGc=GC.CollectionCount(0)-gc;}}
    }
    public static UdpSpan MeasureUdp(){return Instance==null?default(UdpSpan):new UdpSpan(Instance);}
    void Update(){double t=Now;if(lastUpdate>0&&updates.Count<4096)updates.Add((t-lastUpdate)*1000);lastUpdate=t;updateCalls++;if(t-lastWrite>=1){Window();lastWrite=t;}}
    PlayerController observedPlayer;double previousAllowed,lastDrop=-1;
    [Serializable] class DropClock {public string evt="drop_clock";public double game_time,allowed_at,interval,wall;}
    void LateUpdate()
    {
        if(LastFixtureRequest!=null)return; // Fixture deadline restoration is not a real drop.
        if(observedPlayer==null)observedPlayer=FindObjectOfType<PlayerController>();if(observedPlayer==null)return;
        double allowed=observedPlayer.NextDropAllowedAt;
        if(allowed>0 && allowed>previousAllowed)
        {
            double at=allowed-observedPlayer.dropCooldownSeconds;
            Write(new DropClock {game_time=at,allowed_at=allowed,interval=lastDrop<0?-1:at-lastDrop,wall=Now});lastDrop=at;
        }
        if(allowed==0)lastDrop=-1;previousAllowed=allowed;
    }
    void FixedUpdate(){double t=Now;if(lastFixed>0&&fixedGaps.Count<4096)fixedGaps.Add((t-lastFixed)*1000);lastFixed=t;fixedCalls++;}
    [Serializable] class WindowRow {public string evt="window";public double max_log_serialize_ms,max_log_write_flush_ms,max_udp_snapshot_ms;public int serialize_gc,write_gc,udp_gc;public double wall,game_time,fixed_time,heap,unity_bytes;public long updates,fixed_calls,packets;public double[] update_gaps_ms,fixed_gaps_ms;public int gc0,gc1,gc2,video_frames;public double[] capture_ms,readback_callback_ms,publish_ms;}
    void Window()
    {
        Write(new WindowRow {max_log_serialize_ms=serializeMax,max_log_write_flush_ms=writeMax,max_udp_snapshot_ms=udpMax,serialize_gc=serializeGc,write_gc=writeGc,udp_gc=udpGc,wall=Now,game_time=Time.timeAsDouble,fixed_time=Time.fixedTimeAsDouble,heap=GC.GetTotalMemory(false),unity_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong(),updates=updateCalls,fixed_calls=fixedCalls,packets=Packets,
            update_gaps_ms=updates.ToArray(),fixed_gaps_ms=fixedGaps.ToArray(),gc0=GC.CollectionCount(0),gc1=GC.CollectionCount(1),gc2=GC.CollectionCount(2),video_frames=SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames,capture_ms=captures.ToArray(),readback_callback_ms=callbacks.ToArray(),publish_ms=publishes.ToArray()});updates.Clear();fixedGaps.Clear();captures.Clear();callbacks.Clear();publishes.Clear();
    }
    [Serializable] public class PlanRow
    {
        public string evt="plan",mode;public int fruits,iterations,depth,thread,frame_delta,gc0,gc1,gc2;public long fixed_delta,update_delta,packet_delta;
        public double wall,elapsed_ms,game_delta,fixed_time_delta,heap_delta,unity_delta;public int video_delta;public float selected_x;public bool success;public MctsPlanner.ActionMetric[] root_statistics;public MctsPerformance.Metric[] profile;
    }
    public sealed class Span : IDisposable
    {
        readonly SuikaRuntimeProbe p;readonly PlanRow row;readonly double start,game,fixedTime,heap,allocated;readonly long fixedCount,updates,packets;readonly int frame,gc0,gc1,gc2,video;
        public Span(SuikaRuntimeProbe probe,PlanningSettings s)
        {
            p=probe;row=new PlanRow {mode=s.ai_mode,iterations=s.mcts_iterations,depth=s.mcts_max_depth,thread=System.Threading.Thread.CurrentThread.ManagedThreadId};
            fixedCount=p.fixedCalls;updates=p.updateCalls;packets=Packets;frame=Time.frameCount;video=SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames;
            game=Time.timeAsDouble;fixedTime=Time.fixedTimeAsDouble;heap=GC.GetTotalMemory(false);allocated=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();gc0=GC.CollectionCount(0);gc1=GC.CollectionCount(1);gc2=GC.CollectionCount(2);start=Now;
        }
        public void Finish(StepPlanner.Decision d){row.success=true;row.fruits=d.source_fruits==null?0:d.source_fruits.Length;row.selected_x=d.selected_x;if(d.mcts!=null){row.root_statistics=d.mcts.nodes[0].actions;row.profile=d.mcts.profile;}}
        public void Dispose()
        {
            row.wall=start;row.elapsed_ms=(Now-start)*1000;row.frame_delta=Time.frameCount-frame;row.fixed_delta=p.fixedCalls-fixedCount;row.update_delta=p.updateCalls-updates;row.packet_delta=Packets-packets;
            row.game_delta=Time.timeAsDouble-game;row.fixed_time_delta=Time.fixedTimeAsDouble-fixedTime;row.video_delta=(SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames)-video;
            row.gc0=GC.CollectionCount(0)-gc0;row.gc1=GC.CollectionCount(1)-gc1;row.gc2=GC.CollectionCount(2)-gc2;row.heap_delta=GC.GetTotalMemory(false)-heap;row.unity_delta=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()-allocated;p.Write(row);
        }
    }
    public static Span BeginPlan(PlanningSettings s){return Instance==null?null:new Span(Instance,s);}
    [Serializable] class ActionClock {public string evt="action_clock",phase,episode;public long action_id;public double wall,game_time,fixed_time,cooldown;public float x,speed;public int score;}
    public static void ActionEvent(string phase,string episode,long action,PlayerController player)
    {
        if(Instance==null)return;
        Instance.Write(new ActionClock {phase=phase,episode=episode,action_id=action,wall=Now,game_time=Time.timeAsDouble,fixed_time=Time.fixedTimeAsDouble,
            cooldown=player.DropCooldownRemaining,x=player.currentFruit==null?0:player.currentFruit.transform.position.x,speed=player.EffectiveAIMoveSpeed,score=ScoreManager.Instance.GetScore()});
    }
    [Serializable] class Fixture {public UDPCommunicatorUnity.BoardFruit[] fruits;public int score,current_fruit_type,next_fruit_type;public float held_x,drop_cooldown_remaining,game_over_y;}
    public void LoadFixture(PlayerController player,GameManager manager,string request,string pathOverride=null)
    {
        string fixturePath=pathOverride??this.fixturePath;
        if(string.IsNullOrEmpty(fixturePath))throw new InvalidOperationException("No diagnostic fixture configured");
        var f=JsonUtility.FromJson<Fixture>(File.ReadAllText(fixturePath));if(Math.Abs(f.game_over_y-manager.GameOverHeight)>1e-4)throw new InvalidOperationException("Fixture GO geometry differs");
        manager.ResetGame(request);
        foreach(var v in f.fruits)
        {
            var fruit=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[v.type],new Vector3(v.x,v.y,0),Quaternion.Euler(0,0,v.angle));var fe=fruit.GetComponent<FruitEvolution>();fe.IsPreview=false; // Keep the actual prefab tag, including legacy lowercase apple.
            var body=fruit.GetComponent<Rigidbody2D>();if(body==null)body=fruit.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(body);body.position=new Vector2(v.x,v.y);body.rotation=v.angle;body.velocity=new Vector2(v.vx,v.vy);body.angularVelocity=v.angular_velocity;
            FruitColliderShape.Get(fruit).isTrigger=false;var danse=fruit.GetComponent<Danse>();if(danse!=null)danse.InitializePhysicsMaterial();
            typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(fe,new object[]{v.has_collided});if(v.observation_metadata_known&&v.sleeping)body.Sleep();
        }
        player.currentFruit.SetActive(false);Destroy(player.currentFruit);player.nextFruitObject.SetActive(false);Destroy(player.nextFruitObject);
        Vector3 hand=player.transform.position;hand.x=f.held_x-player.heldFruitOffset.x;player.transform.position=hand;player.GetComponent<Rigidbody2D>().position=hand;
        player.currentFruit=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[f.current_fruit_type],player.GetHeldWorldPosition(),Quaternion.identity);
        player.nextFruitObject=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[f.next_fruit_type]);
        var nextDefinition=player.nextFruitObject.GetComponent<Fruit>();if(nextDefinition==null)nextDefinition=player.nextFruitObject.AddComponent<Fruit>();nextDefinition.originalPrefab=EvolutionDatabase.Instance.evolutionPrefabs[f.next_fruit_type];
        player.currentFruit.GetComponent<FruitEvolution>().IsPreview=true;player.nextFruitObject.GetComponent<FruitEvolution>().IsPreview=true;
        PlayerController.PreparePreviewBody(player.currentFruit,false);PlayerController.PreparePreviewBody(player.nextFruitObject,true);FruitColliderShape.Get(player.currentFruit).isTrigger=true;FruitColliderShape.Get(player.nextFruitObject).isTrigger=true;
        player.currentFruit.GetComponent<SpriteRenderer>().sortingOrder=31;player.nextFruitObject.GetComponent<SpriteRenderer>().sortingOrder=30;
        typeof(PlayerController).GetField("nextDropAllowedAt",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).SetValue(player,Time.timeAsDouble+f.drop_cooldown_remaining);
        player.PositionNextFruit();ScoreManager.Instance.totalScore=f.score;Physics2D.SyncTransforms();LastFixtureRequest=request;
    }
    public void Sweep(PlayerController player,GameManager manager,Collider2D floor,string request)
    {
        foreach(int depth in new[]{3,4})foreach(int iterations in new[]{16,32,64})
        {
            var settings=new PlanningSettings {ai_mode="mcts",mcts_iterations=iterations,mcts_max_depth=depth};
            using(var span=BeginPlan(settings)){var decision=StepPlanner.Plan(player,manager,floor,settings);span.Finish(decision);}
        }
        LastSweepRequest=request;Write(new Header {evt="sweep_complete"});
    }
    void OnDestroy(){if(log!=null){Window();log.Dispose();log=null;}if(Instance==this)Instance=null;}
}

public partial class UDPCommunicatorUnity
{
    bool HandleProbeCommand(ActionMessage message)
    {
        var probe=SuikaRuntimeProbe.Instance;if((message.command!="probe_fixture"&&message.command!="probe_sweep")||probe==null)return false;
        if(message.stream_id!=streamId || string.IsNullOrEmpty(message.request_id))return true;
        if(message.command=="probe_sweep")
        {
            if(message.episode_id!=episodeId || activeStep!=null || message.request_id==probe.LastSweepRequest)return true;
            try {probe.Sweep(playerController,gameManager,planningFloor,message.request_id);SendPacket(new Observation());}catch(Exception e){Debug.LogError("Diagnostic sweep: "+e);}return true;
        }
        if(message.request_id==probe.LastFixtureRequest){SendPacket(new Observation());return true;}
        if(message.episode_id!=episodeId || activeStep!=null)return true;
        try {probe.LoadFixture(playerController,gameManager,message.request_id);BeginEpisode(message.request_id);RemoteControl=true;SendPacket(new Observation());}
        catch(Exception e){Debug.LogError("Diagnostic fixture: "+e);}
        return true;
    }
}
