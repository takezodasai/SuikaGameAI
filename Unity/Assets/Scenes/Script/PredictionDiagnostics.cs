using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.LowLevel;

// Opt-in diagnostic observer, inserted AFTER Physics2DFixedUpdate. No simulation/control here.
public static class PredictionDiagnostics
{
    [Serializable] public class Contact { public string other; public Vector2 point, normal; public float normal_impulse, tangent_impulse; }
    [Serializable] public class FruitState
    {
        public string id; public long observation_id; public int type;
        public bool preview, merging, sleeping, has_collided; public Vector2 position, velocity, center_of_mass;
        public float angle, angular_velocity, mass, inertia, friction, bounce;
        public Contact[] contacts;
    }
    [Serializable] public class Frame
    {
        public int tick, render_frame, score; public bool game_over, game_over_candidate;
        public FruitState[] fruits; public string[] events;
    }
    [Serializable] public class Error
    {
        public int tick, actual_frame, predicted_count, actual_count;
        public bool ids_types_match = true, score_match, game_over_match, contacts_match = true, events_match, game_over_candidate_match, contact_eligibility_match = true;
        public float position, velocity, angle, angular_velocity, mass, inertia, center_of_mass;
    }
    [Serializable] public class Report
    {
        public string capture_phase = "After physics, before Update/Destroy: game_over is the committed flag; game_over_candidate is the shared geometric/contact predicate";
        public bool truncated; public int predicted_ticks, actual_ticks; public int first_numeric_tick = -1, first_tolerance_tick = -1;
        public Frame initial_actual, initial_prediction, first_actual, first_prediction;
        public Frame final_actual, final_prediction;
        public Frame first_game_over_candidate_actual, first_game_over_candidate_prediction;
        public bool actual_completion_game_over, predicted_completion_game_over;
        public bool actual_game_over_candidate_observed, predicted_game_over_candidate_observed;
        public Error[] errors; public string[] actual_events, predicted_events;
    }
    public sealed class Recorder
    {
        public readonly Dictionary<FruitEvolution,string> aliases = new Dictionary<FruitEvolution,string>();
        public readonly List<Frame> frames = new List<Frame>();
        public readonly List<string> pending = new List<string>(), history = new List<string>();
        public bool truncated, recording = true;
        readonly float? gameOverHeight;
        public Frame FirstGameOverCandidate { get; private set; }
        public Recorder(float? height = null) { gameOverHeight = height; }
        public void Watch(FruitEvolution fruit, string alias) { if (fruit != null) aliases[fruit] = alias; }
        public string Alias(FruitEvolution fruit)
        { string id; return fruit != null && aliases.TryGetValue(fruit,out id) ? id : "untracked"; }
        public void Event(string text) { if(!recording)return; pending.Add(text); history.Add(frames.Count + ":" + text); }
        public void Capture(int score, bool gameOver)
        {
            if (!recording) return;
            if (frames.Count >= 513) { truncated = true; return; }
            var values = new List<FruitState>();
            bool candidate = gameOverHeight.HasValue ? false : gameOver;
            foreach (var pair in aliases)
            {
                var fruit = pair.Key;
                if (fruit == null || !fruit.gameObject.activeInHierarchy) continue;
                if (gameOverHeight.HasValue && fruit.CompareTag("Fruit") && fruit.CanTriggerGameOver(gameOverHeight.Value)) candidate = true;
                var body = fruit.GetComponent<Rigidbody2D>();
                var shape = FruitColliderShape.Get(fruit.gameObject);
                var contacts = new List<Contact>();
                if (body != null)
                {
                    var points = new List<ContactPoint2D>(); body.GetContacts(points);
                    foreach (var p in points)
                    {
                        var other = p.collider.gameObject == fruit.gameObject ? p.otherCollider : p.collider;
                        var otherFruit = other.GetComponent<FruitEvolution>();
                        contacts.Add(new Contact { other = otherFruit != null ? Alias(otherFruit) : other.name.Replace("(Clone)",""),
                            point = p.point, normal = p.normal, normal_impulse = p.normalImpulse, tangent_impulse = p.tangentImpulse });
                    }
                }
                contacts.Sort((a,b) => { int v=String.CompareOrdinal(a.other,b.other); return v!=0?v:a.point.x.CompareTo(b.point.x); });
                var material = shape != null ? shape.sharedMaterial : null;
                values.Add(new FruitState { id=pair.Value, observation_id=fruit.Simulation==null?fruit.ObservationId:0,
                    type=fruit.fruitType, preview=fruit.IsPreview, merging=fruit.IsMerging, has_collided=fruit.HasCollided,
                    sleeping=body!=null && body.IsSleeping(), position=body!=null?body.position:(Vector2)fruit.transform.position,
                    velocity=body!=null?body.velocity:Vector2.zero, angle=body!=null?body.rotation:fruit.transform.eulerAngles.z,
                    angular_velocity=body!=null?body.angularVelocity:0, mass=body!=null?body.mass:0,
                    inertia=body!=null?body.inertia:0, center_of_mass=body!=null?body.centerOfMass:Vector2.zero,
                    friction=material!=null?material.friction:-1, bounce=material!=null?material.bounciness:-1,
                    contacts=contacts.ToArray() });
            }
            values.Sort((a,b)=>String.CompareOrdinal(a.id,b.id));
            frames.Add(new Frame { tick=frames.Count, render_frame=Time.frameCount, score=score, game_over=gameOver, game_over_candidate=candidate,
                fruits=values.ToArray(), events=pending.ToArray() });
            if (candidate && FirstGameOverCandidate == null) FirstGameOverCandidate = frames[frames.Count-1];
            pending.Clear();
        }
    }
    public static Recorder Live { get; private set; }
    static GameManager manager;
    static bool installed;
    public static void Begin(PlayerController player, GameManager game)
    {
        Stop(); manager=game; Live=new Recorder(game.GameOverHeight);
        foreach (var fruit in UnityEngine.Object.FindObjectsOfType<FruitEvolution>())
            if (fruit.Simulation==null && (!fruit.IsPreview || fruit.gameObject==player.currentFruit))
                Live.Watch(fruit,"f"+fruit.ObservationId);
        Live.Capture(ScoreManager.Instance.GetScore(),game.isGameOver);
        if (!installed)
        {
            var loop=PlayerLoop.GetCurrentPlayerLoop();
            if (!InsertAfterPhysics(ref loop)) throw new InvalidOperationException("Physics2DFixedUpdate not found");
            PlayerLoop.SetPlayerLoop(loop); installed=true;
        }
    }
    static bool InsertAfterPhysics(ref PlayerLoopSystem loop)
    {
        if (loop.subSystemList==null) return false;
        var systems=new List<PlayerLoopSystem>(loop.subSystemList);
        for(int i=0;i<systems.Count;i++)
        {
            if (systems[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate))
            {
                systems.Insert(i+1,new PlayerLoopSystem { type=typeof(PredictionDiagnostics), updateDelegate=AfterPhysics });
                loop.subSystemList=systems.ToArray(); return true;
            }
            var child=systems[i];
            if (InsertAfterPhysics(ref child)) { systems[i]=child;loop.subSystemList=systems.ToArray();return true; }
        }
        return false;
    }
    static void AfterPhysics() { if (Live!=null && manager!=null) Live.Capture(ScoreManager.Instance.GetScore(),manager.isGameOver); }
    public static void Stop() { if(Live!=null)Live.recording=false; Live=null;manager=null; }
    public static Recorder For(FruitEvolution fruit) { return fruit.Simulation!=null?fruit.Simulation.Trace:Live; }
    public static void Collision(FruitEvolution fruit, Collision2D collision)
    {
        var r=For(fruit); if(r==null)return;
        var other=collision.gameObject.GetComponent<FruitEvolution>();
        r.Event("enter:"+r.Alias(fruit)+":"+(other!=null?r.Alias(other):collision.gameObject.name.Replace("(Clone)","")));
    }
    public static void Merge(FruitEvolution a,FruitEvolution b,FruitEvolution created)
    {
        var r=For(a);if(r==null)return;
        var pair=new[]{r.Alias(a),r.Alias(b)};Array.Sort(pair,StringComparer.Ordinal);
        var alias="m("+pair[0]+","+pair[1]+")";
        if(created!=null)r.Watch(created,alias);
        r.Event("merge:"+alias+":"+a.fruitType+"->"+(created!=null?created.fruitType:-1));
        if(created!=null)r.Event("create:"+alias);
    }
    public static void Removed(FruitEvolution fruit, string phase)
    { var r=For(fruit); if(r!=null && r.aliases.ContainsKey(fruit))r.Event(phase+":"+r.Alias(fruit)); }

    public static Report Compare(Recorder predicted) { return Compare(predicted, Live); }
    // Explicit recorders also support an isolated Editor fixture without global Live capture.
    public static Report Compare(Recorder predicted, Recorder actual)
    {
        if(actual==null || predicted==null)return null;
        var report=new Report { initial_actual=actual.frames[0],initial_prediction=predicted.frames[0],
            final_actual=actual.frames[actual.frames.Count-1],final_prediction=predicted.frames[predicted.frames.Count-1],
            actual_game_over_candidate_observed=actual.FirstGameOverCandidate!=null,predicted_game_over_candidate_observed=predicted.FirstGameOverCandidate!=null,
            first_game_over_candidate_actual=actual.FirstGameOverCandidate,first_game_over_candidate_prediction=predicted.FirstGameOverCandidate,
            truncated=actual.truncated||predicted.truncated,predicted_ticks=predicted.frames.Count-1,actual_ticks=actual.frames.Count-1,actual_events=actual.history.ToArray(),predicted_events=predicted.history.ToArray() };
        var errors=new List<Error>();
        for(int i=0;i<Math.Min(actual.frames.Count,predicted.frames.Count);i++)
        {
            var a=actual.frames[i];var p=predicted.frames[i];
            var e=new Error { tick=i,actual_frame=a.render_frame,actual_count=a.fruits.Length,predicted_count=p.fruits.Length,
                score_match=a.score==p.score,game_over_match=a.game_over==p.game_over,
                game_over_candidate_match=a.game_over_candidate==p.game_over_candidate,
                events_match=String.Join("|",a.events)==String.Join("|",p.events) };
            if(a.fruits.Length!=p.fruits.Length)e.ids_types_match=false;
            var map=new Dictionary<string,FruitState>();foreach(var f in a.fruits)map[f.id]=f;
            foreach(var f in p.fruits)
            {
                FruitState other;
                if(!map.TryGetValue(f.id,out other) || other.type!=f.type || other.preview!=f.preview || other.merging!=f.merging)
                {e.ids_types_match=false;continue;}
                if(f.has_collided!=other.has_collided)e.contact_eligibility_match=false;
                e.position=Mathf.Max(e.position,Vector2.Distance(f.position,other.position));
                e.velocity=Mathf.Max(e.velocity,Vector2.Distance(f.velocity,other.velocity));
                e.angle=Mathf.Max(e.angle,Mathf.Abs(Mathf.DeltaAngle(f.angle,other.angle)));
                e.angular_velocity=Mathf.Max(e.angular_velocity,Mathf.Abs(f.angular_velocity-other.angular_velocity));
                e.mass=Mathf.Max(e.mass,Mathf.Abs(f.mass-other.mass));e.inertia=Mathf.Max(e.inertia,Mathf.Abs(f.inertia-other.inertia));
                e.center_of_mass=Mathf.Max(e.center_of_mass,Vector2.Distance(f.center_of_mass,other.center_of_mass));
                if(f.contacts.Length!=other.contacts.Length)e.contacts_match=false;
                else for(int j=0;j<f.contacts.Length;j++)if(f.contacts[j].other!=other.contacts[j].other)e.contacts_match=false;
            }
            bool numerical=!e.ids_types_match || e.position>1e-6f || e.velocity>1e-5f || e.angle>1e-4f || e.angular_velocity>1e-3f;
            bool failed=!e.ids_types_match || !e.score_match || !e.game_over_candidate_match || !e.contact_eligibility_match || e.position>1e-3f || e.velocity>1e-2f || e.angle>0.5f || e.angular_velocity>1;
            if(numerical && report.first_numeric_tick<0) {report.first_numeric_tick=i;report.first_actual=a;report.first_prediction=p;}
            if(failed && report.first_tolerance_tick<0)report.first_tolerance_tick=i;
            errors.Add(e);
        }
        report.errors=errors.ToArray();return report;
    }
}
