using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Explicit, bounded diagnostic process only. Never installed in ordinary play.
public sealed class SuikaCounterfactualProbe : MonoBehaviour {
    [Serializable] class Config {public string[] fixtures;public string output;public float[] positions;public int[] seeds;public int horizon=6,repeats=2;public bool live;}
    [Serializable] class Fixture {public ValueSnapshot snapshot;public UDPCommunicatorUnity.BoardFruit[] fruits;public string category;}
    [Serializable] public class Row {
        public string source,fixture,policy="one-step heuristic, cold probes; actual continuation in one native path",error,root_signature,final_signature;
        public int seed,repeat,horizon,initial_score,total_reward,total_merges,total_ticks,completed_actions;
        public float x;public bool game_over,root_unchanged,random_unchanged,trace_truncated;
        public float actual_applied_x;public bool actual_drop_success;public int actual_drop_tick=-1;
        public int[] future_slots,public_spawn_types;public float[] continuation_x;
        public double elapsed_ms,diagnostic_game_time,diagnostic_fixed_time;public ValueSnapshot actual_initial,initial,after_first,final;
        public SuikaPhysicsSimulator.Result first;
        public PredictionDiagnostics.Frame immediately_after_release;
        public string[] merge_events;public PredictionDiagnostics.Report comparison;
        public long retained_scenes,pending_unloads;
        public string unity_random_state,clock_note="Relative ticks from recreated root; original solver cache, native sleep timer and original RNG are not restored";
    }
    static string config;PlayerController player;GameManager manager;UDPCommunicatorUnity udp;
    bool driving;float liveX,liveApplied;int clock,drop=-1;UnityEngine.Random.State dropRng;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaCounterfactualProbe");
        if(i>=0){config=args[i+1];new GameObject("Counterfactual diagnostic").AddComponent<SuikaCounterfactualProbe>();}
    }
    static int[] Sequence(int seed,int length,int slots,out UnityEngine.Random.State before) {
        var saved=UnityEngine.Random.state;UnityEngine.Random.InitState(seed);before=UnityEngine.Random.state;
        var a=new int[length];for(int i=0;i<length;i++)a[i]=UnityEngine.Random.Range(0,slots);
        UnityEngine.Random.state=saved;return a;
    }
    static int SelectContinuation(SuikaPhysicsSimulator.PathSession path,GameManager game) {
        // Uses the current board and currently held fruit only. No future stream is passed here.
        int best=0;float value=float.NegativeInfinity;bool haveSafe=false;
        for(int a=0;a<5;a++)using(var probe=path.Fork(game)) {
            var r=probe.Advance(a/4f,25,-1);bool safe=r.drop_success&&!r.game_over;
            var b=HeuristicEvaluator.Evaluate(r.evaluation_features,r.reward,new PlanningSettings());
            if((safe&&!haveSafe)||(safe==haveSafe&&b.value>value)){best=a;value=b.value;haveSafe=safe;}
        }
        return best;
    }
    Row Predict(string fixture,float x,int seed,int repeat,int horizon,SuikaPhysicsSimulator.PathSession root) {
        var row=new Row {source="prediction_scene",fixture=fixture,x=x,seed=seed,repeat=repeat,horizon=horizon,initial=root.Snapshot(),initial_score=root.Score,root_signature=root.StateSignature()};
        row.actual_initial=udp.CounterfactualSnapshot();row.diagnostic_game_time=Time.timeAsDouble;row.diagnostic_fixed_time=Time.fixedTimeAsDouble;row.unity_random_state=JsonUtility.ToJson(UnityEngine.Random.state);
        var live=SuikaPhysicsSimulator.LiveSignature(player);var rng=UnityEngine.Random.state;
        UnityEngine.Random.State unused;row.future_slots=Sequence(seed,horizon,player.fruits.Length,out unused);
        row.public_spawn_types=new int[player.fruits.Length];for(int i=0;i<player.fruits.Length;i++)row.public_spawn_types[i]=player.fruits[i].GetComponent<FruitEvolution>().fruitType;
        var watch=System.Diagnostics.Stopwatch.StartNew();var xs=new List<float>();
        using(var path=root.Fork(manager)) {
            path.EnableTrace();row.first=path.Advance(x,25,row.future_slots[0]);row.after_first=path.Snapshot();row.total_merges=row.first.merges;row.completed_actions=1;
            if(row.first.drop_success && row.first.drop_tick<row.first.trace.frames.Count)row.immediately_after_release=row.first.trace.frames[row.first.drop_tick];
            for(int depth=1;depth<horizon&&!path.GameOver;depth++) {
                int action=SelectContinuation(path,manager);float nextX=action/4f;xs.Add(nextX);
                var result=path.Advance(nextX,25,row.future_slots[depth]);row.total_merges+=result.merges;row.completed_actions++;
            }
            row.final=path.Snapshot();row.final_signature=path.StateSignature();row.total_reward=path.Score-root.Score;row.total_ticks=path.TotalTicks;row.game_over=path.GameOver;
            row.merge_events=row.first.trace.history.FindAll(e=>e.Contains(":merge:")).ToArray();row.trace_truncated=row.first.trace.truncated;
        }
        row.continuation_x=xs.ToArray();row.root_unchanged=root.StateSignature()==row.root_signature&&live==SuikaPhysicsSimulator.LiveSignature(player);
        row.random_unchanged=JsonUtility.ToJson(rng)==JsonUtility.ToJson(UnityEngine.Random.state);row.elapsed_ms=watch.Elapsed.TotalMilliseconds;
        row.retained_scenes=PredictionLifecycle.RetainedScenes;row.pending_unloads=PredictionLifecycle.Pending;
        if(!row.root_unchanged||!row.random_unchanged)throw new Exception("Branch contaminated root/live RNG");
        if(row.first.reward!=row.after_first.score-row.initial_score||row.total_reward!=row.final.score-row.initial_score)throw new Exception("Score conservation failed");
        return row;
    }
    void FixedUpdate() {
        if(!driving)return;clock++;if(drop>=0)return;
        var range=player.GetDropRange();float target=Mathf.Lerp(range.min_x,range.max_x,liveX);
        float nx=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(nx,range,out error))throw new Exception(error);
        if(nx==target&&player.CanDropFruit) {
            // Predeclared hypothetical stream; never copies the source episode's hidden future.
            UnityEngine.Random.state=dropRng;float applied;long id;
            if(!player.TryDropAt(liveX,out applied,out id,out range,out error))throw new Exception(error);drop=clock;liveApplied=applied;
        }
    }
    IEnumerator Load(string fixture) {
        Time.timeScale=0;PredictionDiagnostics.Stop();
        SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),fixture);Time.timeScale=0;
        yield return null;yield return null;
        var f=JsonUtility.FromJson<Fixture>(File.ReadAllText(fixture));
        // Collider/Start initialization can change COM and thereby adjust linear
        // velocity. Apply recorded kinematics only AFTER that initialization.
        // This restores visible fields, not native solver/sleep history.
        var remaining=new List<FruitEvolution>();
        foreach(var fruit in FindObjectsOfType<FruitEvolution>())if(fruit.Simulation==null&&!fruit.IsPreview&&!fruit.IsMerging)remaining.Add(fruit);
        var bodies=new List<Rigidbody2D>();
        foreach(var v in f.fruits) {
            FruitEvolution best=null;float distance=float.PositiveInfinity;
            foreach(var fruit in remaining)if(fruit.fruitType==v.type) {
                float d=Vector2.SqrMagnitude((Vector2)fruit.transform.position-new Vector2(v.x,v.y));if(d<distance){distance=d;best=fruit;}
            }
            if(best==null||distance>1e-8f)throw new Exception("Fixture fruit mapping is ambiguous or shifted");
            remaining.Remove(best);var b=best.GetComponent<Rigidbody2D>();b.position=new Vector2(v.x,v.y);b.rotation=v.angle;bodies.Add(b);
        }
        Physics2D.SyncTransforms();
        for(int i=0;i<bodies.Count;i++) {var v=f.fruits[i];bodies[i].velocity=new Vector2(v.vx,v.vy);bodies[i].angularVelocity=v.angular_velocity;}
        if(f.snapshot!=null&&f.snapshot.current_fruit!=null&&f.snapshot.current_fruit.y_known) {
            var pos=player.currentFruit.transform.position;pos.y=f.snapshot.current_fruit.y;
            player.currentFruit.transform.position=pos;player.currentFruit.GetComponent<Rigidbody2D>().position=pos;Physics2D.SyncTransforms();
        }
    }
    // Shared diagnostic restoration; disabled helper component never runs Start/FixedUpdate.
    public IEnumerator RestoreForAudit(PlayerController p,GameManager g,UDPCommunicatorUnity u,string fixture) {
        player=p;manager=g;udp=u;return Load(fixture);
    }
    IEnumerator Start() {
        yield return null;yield return null;var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));
        if(c.horizon<1||c.horizon>8||c.repeats<1||c.repeats>3||c.seeds.Length>8)throw new Exception("Diagnostic budget out of bounds");
        foreach(float x in c.positions)if(float.IsNaN(x)||x<0||x>1)throw new Exception("Illegal x");
        player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        Application.targetFrameRate=60;int failures=0;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(string fixture in c.fixtures) {
            yield return Load(fixture);
            using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
                foreach(int seed in c.seeds)foreach(float x in c.positions)for(int repeat=0;repeat<c.repeats;repeat++) {
                    Row row;
                    try {row=Predict(fixture,x,seed,repeat,c.horizon,root);}catch(Exception e){failures++;row=new Row {source="prediction_scene",fixture=fixture,x=x,seed=seed,repeat=repeat,error=e.ToString()};}
                    log.WriteLine(JsonUtility.ToJson(row));log.Flush();
                }
            if(c.live)foreach(float x in new[]{.5f,.37f}) {
                yield return Load(fixture);UnityEngine.Random.State before;var sequence=Sequence(c.seeds[0],c.horizon,player.fruits.Length,out before);
                PredictionDiagnostics.Recorder predicted;Row row;
                using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))using(var path=root.Fork(manager)) {
                    path.EnableTrace();var result=path.Advance(x,25,sequence[0]);predicted=result.trace;
                    row=new Row {source="actual_game_reconstructed_fixture",fixture=fixture,x=x,seed=c.seeds[0],initial=udp.CounterfactualSnapshot(),first=result,after_first=path.Snapshot(),future_slots=sequence};
                }
                row.unity_random_state=JsonUtility.ToJson(before);
                PredictionDiagnostics.Begin(player,manager);player.StepControlLocked=true;liveX=x;clock=0;drop=-1;dropRng=before;driving=true;Time.timeScale=1;
                while(clock<200&&!manager.isGameOver&&(drop<0||clock-drop<25))yield return null;
                driving=false;Time.timeScale=0;player.StepControlLocked=false;
                row.comparison=PredictionDiagnostics.Compare(predicted);row.final=udp.CounterfactualSnapshot();
                row.actual_drop_success=drop>=0;row.actual_drop_tick=drop;row.actual_applied_x=drop>=0?liveApplied:0;
                if(row.actual_drop_success&&row.first.drop_success&&Mathf.Abs(row.actual_applied_x-row.first.applied_x)>1e-5f)throw new Exception("Actual selected X mismatch");
                row.total_ticks=clock;row.initial_score=row.initial.score;row.total_reward=row.final.score-row.initial.score;row.game_over=manager.isGameOver;
                row.merge_events=PredictionDiagnostics.Live.history.FindAll(e=>e.Contains(":merge:")).ToArray();
                row.comparison.actual_completion_game_over=manager.isGameOver;row.comparison.predicted_completion_game_over=row.first.game_over;
                PredictionDiagnostics.Stop();log.WriteLine(JsonUtility.ToJson(row));log.Flush();
            }
        }
        Debug.Log("COUNTERFACTUAL PROBE COMPLETE failures="+failures);Application.Quit(failures==0?0:2);
    }
}

public partial class UDPCommunicatorUnity {
    // Observer only: no packet, state counter, reward ledger or live RNG changes.
    public ValueSnapshot CounterfactualSnapshot() {
        var fruits=new List<BoardFruit>();var held=playerController.currentFruit;
        foreach(var fruit in FindObjectsOfType<FruitEvolution>())if(fruit.Simulation==null&&!fruit.IsPreview&&!fruit.IsMerging) {
            var b=fruit.GetComponent<Rigidbody2D>();var v=new BoardFruit {id=fruit.ObservationId,type=fruit.fruitType,x=b.position.x,y=b.position.y,vx=b.velocity.x,vy=b.velocity.y,angle=b.rotation,angular_velocity=b.angularVelocity,has_collided=fruit.HasCollided};
            MeasureFruit(v,fruit,b,new List<Collider2D>());fruits.Add(v);
        }
        fruits.Sort((a,b)=>a.id.CompareTo(b.id));var r=playerController.GetDropRange();
        return new ValueSnapshot {fruits=fruits.ToArray(),current_fruit=new ControlledFruit {present=held!=null,type=held.GetComponent<FruitEvolution>().fruitType,x=held.transform.position.x,y=held.transform.position.y,y_known=true},
            next_fruit_type=playerController.nextFruitObject.GetComponent<FruitEvolution>().fruitType,score=ScoreManager.Instance.GetScore(),game_over=gameManager.isGameOver,drop_cooldown_remaining=playerController.DropCooldownRemaining,
            ai_move_speed=playerController.EffectiveAIMoveSpeed,fixed_delta_time=Time.fixedDeltaTime,geometry=new[]{r.left_wall_inner,r.right_wall_inner,planningFloor.bounds.max.y,gameManager.GameOverHeight}};
    }
}
