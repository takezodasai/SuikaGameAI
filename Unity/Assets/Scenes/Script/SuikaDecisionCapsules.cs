using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Opt-in observation only. No Simulate, setters, hidden-future samples, or UDP writes.
public sealed class SuikaDecisionCapsules : MonoBehaviour {
    static StreamWriter writer;static string destination;static readonly HashSet<string> seen=new HashSet<string>();
    static int count,errors;static double maxCaptureMs,maxWriteMs;
    [Serializable] public class Capsule {
        public string version="decision-capsule-v2",phase="main-thread immediately before synchronous plan; before movement",tick_scope="Player lifetime FixedUpdate callbacks, not per-action ticks",episode,unity_rng_state,build_guid;
        public long action_id,physics_tick;public int render_frame;public double game_time,fixed_time,next_drop_allowed_at,capture_ms;
        public bool native_checkpoint_exact=false,solver_cache_known=false,native_sleep_timer_known=false,automatic_com_history_known=false,creation_order_known=false;
        public bool visible_kinematics_known=true,held_next_known=true,cooldown_known=true,rng_known=true,enumeration_order_known=true;
        public ValueSnapshot snapshot;public PredictionDiagnostics.Frame native_bodies;public int[] native_instance_order;public PlanningSettings settings;
        public RuntimeProfile[] runtime_profiles;
    }
    [Serializable] public class RuntimeProfile {public long observation_id;public int layer;public Vector3 scale;public bool active;public UDPCommunicatorUnity.PhysicsProfile profile;public bool[] collider_enabled,collider_trigger;}
    [Serializable] class Stats {public int count,errors;public double max_capture_ms,max_write_ms;}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaDecisionCapsules");if(i<0)return;
        destination=Path.GetFullPath(args[i+1]);Directory.CreateDirectory(Path.GetDirectoryName(destination));
        writer=new StreamWriter(new FileStream(destination,FileMode.CreateNew));writer.AutoFlush=true;
        // No new scene object/component: observation must not change object enumeration order.
        Application.quitting+=Close;
    }
    public static bool Enabled {get{return writer!=null;}}
    public static void Capture(UDPCommunicatorUnity udp,PlayerController player,GameManager manager,string episode,long action,long tick,PlanningSettings settings) {
        if(writer==null||!seen.Add(episode+":"+action))return;
        try {
            var timer=System.Diagnostics.Stopwatch.StartNew();var snapshot=udp.CounterfactualSnapshot();
            var recorder=new PredictionDiagnostics.Recorder(manager.GameOverHeight);var order=new List<int>();var profiles=new List<RuntimeProfile>();
            foreach(var fruit in UnityEngine.Object.FindObjectsOfType<FruitEvolution>())if(fruit.Simulation==null&&(!fruit.IsPreview||fruit.gameObject==player.currentFruit)) {
                // NEXT is deliberately not assigned an observation ID here.
                order.Add(fruit.GetInstanceID());recorder.Watch(fruit,"f"+fruit.ObservationId);
                var colliders=fruit.GetComponents<Collider2D>();var enabled=new bool[colliders.Length];var triggers=new bool[colliders.Length];
                for(int i=0;i<colliders.Length;i++){enabled[i]=colliders[i].enabled;triggers[i]=colliders[i].isTrigger;}
                profiles.Add(new RuntimeProfile {observation_id=fruit.ObservationId,layer=fruit.gameObject.layer,scale=fruit.transform.lossyScale,active=fruit.gameObject.activeInHierarchy,profile=udp.CounterfactualBodyProfile(fruit.gameObject),collider_enabled=enabled,collider_trigger=triggers});
            }
            recorder.Capture(snapshot.score,snapshot.game_over);
            var row=new Capsule {episode=episode,action_id=action,physics_tick=tick,render_frame=Time.frameCount,game_time=Time.timeAsDouble,fixed_time=Time.fixedTimeAsDouble,
                next_drop_allowed_at=player.NextDropAllowedAt,unity_rng_state=JsonUtility.ToJson(UnityEngine.Random.state),build_guid=Application.buildGUID,
                snapshot=snapshot,native_bodies=recorder.frames[0],native_instance_order=order.ToArray(),runtime_profiles=profiles.ToArray(),settings=settings};
            row.capture_ms=timer.Elapsed.TotalMilliseconds;maxCaptureMs=Math.Max(maxCaptureMs,row.capture_ms);
            string json=JsonUtility.ToJson(row);timer.Restart();writer.WriteLine(json);count++;maxWriteMs=Math.Max(maxWriteMs,timer.Elapsed.TotalMilliseconds);
            if(count==1)using(var environment=new StreamWriter(new FileStream(destination+".environment.json",FileMode.CreateNew)))environment.Write(udp.CounterfactualEnvironmentJson());
        }catch(Exception e){errors++;Debug.LogWarning("Decision observation failed; gameplay continues: "+e.Message);}
    }
    static void Close() {
        if(writer==null)return;writer.Dispose();writer=null;
        using(var stream=new StreamWriter(new FileStream(destination+".stats.json",FileMode.CreateNew)))stream.Write(JsonUtility.ToJson(new Stats {count=count,errors=errors,max_capture_ms=maxCaptureMs,max_write_ms=maxWriteMs}));
    }
}

public partial class UDPCommunicatorUnity {
    public string CounterfactualEnvironmentJson() {return JsonUtility.ToJson(CaptureTrainingEnvironment());}
    public PhysicsProfile CounterfactualBodyProfile(GameObject source) {
        var b=source.GetComponent<Rigidbody2D>();var p=new PhysicsProfile {body_known=b!=null,colliders=DescribeShapes(source)};
        if(b!=null){p.mass=b.mass;p.inertia=b.inertia;p.center_of_mass=b.centerOfMass;p.gravity_scale=b.gravityScale;p.linear_drag=b.drag;p.angular_drag=b.angularDrag;p.body_type=b.bodyType.ToString();p.collision_detection=b.collisionDetectionMode.ToString();p.interpolation=b.interpolation.ToString();p.constraints=b.constraints.ToString();p.sleep_mode=b.sleepMode.ToString();p.simulated=b.simulated;p.use_auto_mass=b.useAutoMass;}
        return p;
    }
}
