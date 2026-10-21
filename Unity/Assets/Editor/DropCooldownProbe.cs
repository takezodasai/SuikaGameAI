using System;
using UnityEditor;
using UnityEngine;
using Object=UnityEngine.Object;

public static class DropCooldownProbe
{
    static PlayerController player;
    static GameManager manager;
    static GameObject waiting;
    static double firstDropAt;
    static float originalCooldown;
    static void Require(bool value,string message)
    { if(!value)throw new Exception("Cooldown regression: "+message); }
    [MenuItem("Tools/Suika/Run Drop Cooldown Probe")]
    public static void Run()
    {
        if(!Application.isPlaying || player!=null)throw new InvalidOperationException("Requires idle Play");
        player=Object.FindObjectOfType<PlayerController>();manager=Object.FindObjectOfType<GameManager>();
        originalCooldown=player.dropCooldownSeconds;
        try
        {
            player.dropCooldownSeconds=.4f;manager.ResetGame("");
            Require(player.CanDropFruit,"reset left cooldown active");
            var first=player.currentFruit;player.DropFruit();
            Require(player.currentFruit!=first,"first drop rejected");
            waiting=player.currentFruit;firstDropAt=Time.timeAsDouble;
            for(int i=0;i<20;i++)player.DropFruit();
            Require(player.currentFruit==waiting && waiting.GetComponent<FruitEvolution>().IsPreview,"same-frame repeated drop accepted");
            EditorApplication.update+=Tick;
        }
        catch { Restore();throw; }
    }
    static void Tick()
    {
        try
        {
            if(!Application.isPlaying){Restore();return;}
            double elapsed=Time.timeAsDouble-firstDropAt;
            if(elapsed<.4)
            {
                player.DropFruit();
                Require(player.currentFruit==waiting,"early drop accepted");
                return;
            }
            if(elapsed<.42)return;
            player.DropFruit();Require(player.currentFruit!=waiting,"drop after cooldown rejected");
            manager.ResetGame("");Require(player.CanDropFruit,"reset failed to clear cooldown");
            Debug.Log("PASS: 0.4s drop cooldown; 20 same-frame retries and early-frame drops blocked; delayed drop accepted; reset immediately ready");
            Restore();
        }
        catch(Exception e){Debug.LogException(e);Restore();}
    }
    static void Restore()
    {
        EditorApplication.update-=Tick;
        if(player!=null)player.dropCooldownSeconds=originalCooldown;
        if(Application.isPlaying && manager!=null)manager.ResetGame("");
        player=null;manager=null;
    }
}

// Real paired test begun inside the 0.4-second cooldown, without advancing the source for prediction.
public static class CooldownPredictionProbe
{
    static PlayerController fixturePlayer;
    static GameObject[] originalFruits;
    static UDPCommunicatorUnity udp;
    static GameManager manager;
    static double deadline;
    static readonly System.Reflection.BindingFlags Fields = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
    static object Field(string name) { return typeof(UDPCommunicatorUnity).GetField(name, Fields).GetValue(udp); }
    [MenuItem("Tools/Suika/Run Cooldown Prediction Probe")]
    public static void Run()
    {
        if (!Application.isPlaying || udp != null) throw new InvalidOperationException("Requires idle Play");
        udp = Object.FindObjectOfType<UDPCommunicatorUnity>();
        manager = Object.FindObjectOfType<GameManager>();
        var player = Object.FindObjectOfType<PlayerController>();
        try
        {
            fixturePlayer=player; originalFruits=player.fruits;
            // A deterministic test fixture only; restore the saved spawn list afterwards.
            player.fruits=new[]{EvolutionDatabase.Instance.evolutionPrefabs[0]};
            manager.ResetGame("");
            if(Mathf.Abs(player.dropCooldownSeconds-.4f)>.00001f)throw new Exception("Inspector cooldown is not 0.4 seconds");
            player.DropFruit();
            var range = player.GetDropRange();
            float x = Mathf.InverseLerp(range.min_x, range.max_x, player.currentFruit.transform.position.x);
            var command = new UDPCommunicatorUnity.ActionMessage {
                command="compare_step", stream_id=(string)Field("streamId"),
                episode_id=(string)Field("episodeId"), action_id=1, x=x, comparison_post_drop_steps=100
            };
            typeof(UDPCommunicatorUnity).GetMethod("HandleStep", Fields).Invoke(udp, new object[]{command});
            var prediction = (SuikaPhysicsSimulator.Result)Field("pendingPrediction");
            if (prediction == null || !prediction.source_unchanged || prediction.cooldown_wait_steps < 1)
                throw new Exception("Cooldown prediction did not wait or mutated source");
            foreach (var initial in prediction.initial_fruits)
                foreach (var fruit in Object.FindObjectsOfType<FruitEvolution>())
                    if (fruit.Simulation == null && fruit.ObservationId == initial.id && fruit.HasCollided != initial.has_collided)
                        throw new Exception("Contact eligibility was not copied");
            deadline=EditorApplication.timeSinceStartup+5;
            EditorApplication.update+=Tick;
        }
        catch { Restore(); throw; }
    }
    static void Tick()
    {
        try
        {
            if (!Application.isPlaying) { Restore(); return; }
            var actual=(UDPCommunicatorUnity.Observation)Field("completedStep");
            if (actual == null)
            {
                if(EditorApplication.timeSinceStartup>deadline)throw new TimeoutException("Cooldown paired prediction did not finish");
                return;
            }
            var ledger=actual.reward_accounting;
            if(ledger==null || !ledger.conserved || ledger.last_step.reward!=actual.step_result.reward || ledger.open_interval.reward!=0)
                throw new Exception("Paired merge reward ledger does not conserve score");
            var p=actual.prediction;
            if(p == null || p.merges < 1 || p.reward < 1 || p.physics_steps!=actual.actual_total_physics_steps || p.score!=actual.score || p.game_over!=actual.game_over)
                throw new Exception("Cooldown paired result differs in ticks/score/game over");
            var predictedTypes=new System.Collections.Generic.List<int>();
            var actualTypes=new System.Collections.Generic.List<int>();
            foreach(var f in p.fruits)predictedTypes.Add(f.type);
            foreach(var f in actual.fruits)actualTypes.Add(f.type);
            predictedTypes.Sort();actualTypes.Sort();
            if(string.Join(",",predictedTypes)!=string.Join(",",actualTypes))throw new Exception("Cooldown paired fruit types differ");
            string path=System.IO.Path.GetFullPath(System.IO.Path.Combine(Application.dataPath,"../../Python/cooldown_prediction_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+".json"));
            System.IO.File.WriteAllText(path,JsonUtility.ToJson(actual,true));
            Debug.Log("PASS: cooldown prediction waited "+p.cooldown_wait_steps+" ticks; source unchanged; actual/predicted physics ticks="+p.physics_steps+", score/types/game-over match; "+path);
            Restore();
        }
        catch(Exception e){Debug.LogException(e);Restore();}
    }
    static void Restore()
    {
        EditorApplication.update-=Tick;
        if(fixturePlayer!=null && originalFruits!=null)fixturePlayer.fruits=originalFruits;
        if(Application.isPlaying && manager!=null)manager.ResetGame("");
        fixturePlayer=null;originalFruits=null;udp=null;manager=null;
    }
}


public static class Step4ContractProbe
{
    static PlayerController player;
    static GameManager manager;
    static double deadline;
    [MenuItem("Tools/Suika/Run Step4 Contract Probe")]
    public static void Run()
    {
        if(!Application.isPlaying || player!=null)throw new InvalidOperationException("Requires idle Play");
        player=Object.FindObjectOfType<PlayerController>();manager=Object.FindObjectOfType<GameManager>();
        try
        {
            manager.ResetGame("");
            var range=player.GetDropRange();
            if(!player.TryMoveHeldTo(0,range,out _))throw new Exception("Cannot centre speed fixture");
            float before=player.currentFruit.transform.position.x;
            player.MoveRight();
            var tick=typeof(PlayerController).GetMethod("FixedUpdate",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic);
            for(int i=0;i<10;i++)tick.Invoke(player,null);
            float measured=(player.currentFruit.transform.position.x-before)/(10*Time.fixedDeltaTime);
            if(!player.matchKeyboardMoveSpeed || Mathf.Abs(measured-player.EffectiveAIMoveSpeed)>.0001f)
                throw new Exception("Manual/AI movement speed mismatch: "+measured+"/"+player.EffectiveAIMoveSpeed);
            Debug.Log("PASS: measured manual movement="+measured+", AI/prediction effective speed="+player.EffectiveAIMoveSpeed);
            manager.ResetGame("");
            // A short-lived near-line collision fixture; no global physics settings change.
            var prefabs=EvolutionDatabase.Instance.evolutionPrefabs;
            var a=Object.Instantiate(prefabs[0],new Vector3(0,manager.GameOverHeight+.3f,0),Quaternion.identity);
            var b=Object.Instantiate(prefabs[3],new Vector3(0,manager.GameOverHeight+.3f,0),Quaternion.identity);
            foreach(var obj in new[]{a,b})
            {
                obj.GetComponent<FruitEvolution>().IsPreview=false;
                var body=obj.GetComponent<Rigidbody2D>();if(body==null)body=obj.AddComponent<Rigidbody2D>();
                PlayerController.ReleaseFruitBody(body);
                FruitColliderShape.Get(obj).isTrigger=false;
            }
            Physics2D.SyncTransforms();
            float reach=FruitColliderShape.Get(a).bounds.extents.x+FruitColliderShape.Get(b).bounds.extents.x;
            // Prefabs have different collider offsets: align native shape centres, not pivots.
            b.transform.position+=FruitColliderShape.Get(a).bounds.center-FruitColliderShape.Get(b).bounds.center+new Vector3(reach-.02f,0,0);
            Physics2D.SyncTransforms();
            var contact=FruitColliderShape.Get(a).Distance(FruitColliderShape.Get(b));
            if(!contact.isValid || !contact.isOverlapped)throw new Exception("Near-line collision fixture shapes do not touch");
            PredictionDiagnostics.Begin(player,manager);
            deadline=EditorApplication.timeSinceStartup+3;
            EditorApplication.update+=Tick;
        }
        catch { Restore();throw; }
    }
    static void Tick()
    {
        try
        {
            if(!Application.isPlaying){Restore();return;}
            if(!manager.isGameOver)
            {
                if(EditorApplication.timeSinceStartup>deadline)throw new TimeoutException("Near-line game-over fixture did not trigger");
                return;
            }
            var first=PredictionDiagnostics.Live.FirstGameOverCandidate;
            if(first==null || !first.game_over_candidate || first.game_over)
                throw new Exception("Physics predicate / committed Update flag were not distinguished");
            Debug.Log("PASS: near-line physical collision armed game over; after-physics candidate=true, committed flag=false; following Update committed game-over=true. Physics and threshold unchanged.");
            Restore();
        }
        catch(Exception e){Debug.LogException(e);Restore();}
    }
    static void Restore()
    {
        EditorApplication.update-=Tick;PredictionDiagnostics.Stop();
        if(Application.isPlaying && manager!=null)manager.ResetGame("");
        player=null;manager=null;
    }
}
