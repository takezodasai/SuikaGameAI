using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object=UnityEngine.Object;

// Local worlds only. Runs the production merge callback and current Circle/Capsule prefabs.
public static class MergeOverlapProbe
{
    [Serializable] public class Sample
    {
        public int mode, source_type, neighbor_type; public float neighbor_angle, hull_area_ratio; public float offset_fraction;
        public bool merged, initial_neighbor_clear, neighbor_sleeping, delaunay;
        public int neighbor_shapes, evolved_shapes, bridges;
        public float initial_depth, peak_depth, final_depth;
        public int overlap_ticks; public Vector2 neighbor_position, evolved_position;
    }
    [Serializable] public class Report
    { public string note="Production prefabs, 51 geometry stress cases, dynamic bodies, gravity=1, no walls/floor; 300 fixed ticks per case";
      public double elapsed_ms; public Sample[] samples; public bool source_unchanged; }
    static readonly BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    [MenuItem("Tools/Suika/Run Merge Overlap Probe %#F9")]
    public static void Run()
    {
        if(!Application.isPlaying)throw new InvalidOperationException("Requires Play mode");
        var game=Object.FindObjectOfType<GameManager>();
        var prefabs=EvolutionDatabase.Instance.evolutionPrefabs;
        var rng=UnityEngine.Random.state;int score=ScoreManager.Instance.GetScore();
        var samples=new List<Sample>();var timer=System.Diagnostics.Stopwatch.StartNew();
        foreach(int type in new[]{0,1,2,4,7,9})
        foreach(float fraction in new[]{0.35f,0.5f,0.65f})
        foreach(int neighborType in type==7?new[]{0,1,2,4,6,9}:new[]{type==0?2:0})
        foreach(float neighborAngle in type==7?new[]{0f,45f}:new[]{0f})
        {
            var sim=(SuikaPhysicsSimulator)Activator.CreateInstance(typeof(SuikaPhysicsSimulator),Private,null,new object[]{game},null);
            try
            {
                var copy=typeof(SuikaPhysicsSimulator).GetMethod("Copy",Private);
                var flush=typeof(SuikaPhysicsSimulator).GetMethod("FlushRemoval",Private);
                var scene=(Scene)typeof(SuikaPhysicsSimulator).GetField("scene",Private).GetValue(sim);
                Func<int,GameObject> make=t=>(GameObject)copy.Invoke(sim,new object[]{prefabs[t],true});
                var left=make(type);var right=make(type);var neighbor=make(neighborType);
                foreach(var obj in new[]{left,right,neighbor})
                { obj.transform.rotation=Quaternion.identity;obj.transform.position=Vector3.zero; }
                Physics2D.SyncTransforms();
                var lc=FruitColliderShape.Get(left);var rc=FruitColliderShape.Get(right);var nc=FruitColliderShape.Get(neighbor);
                float width=lc.bounds.size.x,height=lc.bounds.size.y;
                left.transform.position=new Vector3(-width*.495f,0,0);right.transform.position=new Vector3(width*.495f,0,0);
                neighbor.transform.position=new Vector3(0,height*fraction,0);
                neighbor.transform.rotation=Quaternion.Euler(0,0,neighborAngle);
                foreach(var obj in new[]{left,right,neighbor})
                {
                    var f=obj.GetComponent<FruitEvolution>();f.IsPreview=false;
                    if(f.HasCollided || f.CanTriggerGameOver(f.transform.position.y - 100))
                        throw new Exception("Fresh fruit must not trigger game over before contact");
                    var c=FruitColliderShape.Get(obj);c.isTrigger=false;
                    var b=obj.GetComponent<Rigidbody2D>();if(b==null)b=obj.AddComponent<Rigidbody2D>();
                    b.gravityScale=1;b.velocity=Vector2.zero;b.angularVelocity=0;
                }
                Physics2D.SyncTransforms();
                var row=new Sample {mode=10,source_type=type,neighbor_type=neighborType,neighbor_angle=neighborAngle,offset_fraction=fraction,
                    initial_neighbor_clear=!nc.Distance(lc).isOverlapped && !nc.Distance(rc).isOverlapped};
                FruitEvolution evolved=null;
                for(int tick=0;tick<300;tick++)
                {
                    if(!scene.GetPhysicsScene2D().Simulate(Time.fixedDeltaTime))throw new InvalidOperationException("Simulate failed");
                    flush.Invoke(sim,null);
                    if(evolved==null)
                        foreach(var root in scene.GetRootGameObjects())
                        {var f=root.GetComponent<FruitEvolution>();if(f!=null&&f.fruitType==type+1&&f.gameObject.activeSelf)evolved=f;}
                    if(evolved!=null&&neighbor.activeSelf)
                    {
                        if(!evolved.HasCollided || !evolved.CanTriggerGameOver(evolved.transform.position.y - .1f) ||
                            evolved.CanTriggerGameOver(evolved.transform.position.y))
                            throw new Exception("Merged fruit lost contact-based game-over eligibility");
                        evolved.IsPreview=true;
                        bool previewEligible=evolved.CanTriggerGameOver(evolved.transform.position.y - .1f);
                        evolved.IsPreview=false;
                        if(previewEligible) throw new Exception("Preview fruit must never trigger game over");
                        row.neighbor_shapes=nc.shapeCount;
                        row.evolved_shapes=FruitColliderShape.Get(evolved.gameObject).shapeCount;
                        var distance=nc.Distance(FruitColliderShape.Get(evolved.gameObject));
                        float depth=distance.isValid?Mathf.Max(0,-distance.distance):0;
                        if(!row.merged)row.initial_depth=depth;
                        row.merged=true;row.peak_depth=Mathf.Max(row.peak_depth,depth);
                        if(depth>3*Physics2D.defaultContactOffset)row.overlap_ticks++;
                        row.final_depth=depth;row.neighbor_sleeping=neighbor.GetComponent<Rigidbody2D>().IsSleeping();
                        row.neighbor_position=neighbor.transform.position;row.evolved_position=evolved.transform.position;
                    }
                }
                samples.Add(row);
            }
            finally {sim.Dispose();}
        }
        foreach(var sample in samples)
            if(!sample.merged || sample.evolved_shapes!=1 || sample.neighbor_shapes!=1 || sample.final_depth>.03f)
                throw new Exception("Production collider regression: type="+sample.source_type);
        var report=new Report {elapsed_ms=timer.Elapsed.TotalMilliseconds,samples=samples.ToArray(),
            source_unchanged=rng.Equals(UnityEngine.Random.state)&&score==ScoreManager.Instance.GetScore()};
        string path=Path.GetFullPath(Path.Combine(Application.dataPath,"../../Python/merge_overlap_probe_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+".json"));
        File.WriteAllText(path,JsonUtility.ToJson(report,true));
        Debug.Log("Merge overlap probe complete: "+path);
    }
}
