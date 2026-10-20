using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.LowLevel;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

// Editor-only experiment: fresh fruit + floor, no merges, no production control changes.
[InitializeOnLoad]
public static class SingleCollisionProbe
{
    const int Ticks = 120;
    sealed class World
    {
        public Scene scene;
        public PhysicsScene2D physics;
        public GameObject staging;
        public PredictionDiagnostics.Recorder recorder = new PredictionDiagnostics.Recorder();
        public PhysicsMaterial2D material;
    }
    [Serializable] sealed class Output
    {
        public string condition = "One type-2 fruit and original bottom only; identical factory, automatic default vs manual local";
        public float dt;
        public double local_same_order_ms, local_reversed_order_ms;
        public PredictionDiagnostics.Report same_order, reversed_order, local_vs_local;
        public PredictionDiagnostics.Frame[] actual_impact_window, same_order_impact_window, reversed_order_impact_window;
    }
    static readonly List<World> worlds = new List<World>();
    static readonly List<GameObject> disabledRoots = new List<GameObject>();
    static Output output;
    static int ticks;
    static bool running;
    static SingleCollisionProbe() { EditorApplication.playModeStateChanged += OnPlayMode; }
    static void OnPlayMode(PlayModeStateChange state)
    { if (state == PlayModeStateChange.ExitingPlayMode) Cleanup(); }

    [MenuItem("Tools/Suika/Run Single Collision Probe %#F8")]
    public static void Run()
    {
        if (!Application.isPlaying || running) throw new InvalidOperationException("Requires idle Play mode");
        var player = Object.FindObjectOfType<PlayerController>();
        if (player == null || player.StepControlLocked || Time.timeScale != 1)
            throw new InvalidOperationException("Requires idle game, timeScale=1");
        foreach (var fruit in Object.FindObjectsOfType<FruitEvolution>())
            if (!fruit.IsPreview) throw new InvalidOperationException("Start on an empty board (fresh Play or reset)");
        Collider2D floor = null;
        foreach (var c in Object.FindObjectsOfType<Collider2D>())
            if (c.name == "bottom") { if(floor!=null)throw new InvalidOperationException("Ambiguous floor"); floor=c; }
        if (floor == null) throw new InvalidOperationException("Original bottom collider not found");
        var prefab = EvolutionDatabase.Instance.evolutionPrefabs[2];
        var position = player.currentFruit.transform.position;
        output = new Output { dt=Time.fixedDeltaTime };
        ticks=0;
        try
        {
            // Disable originals only on an empty board. No asset/physics setting is edited.
            for (int s=0;s<SceneManager.sceneCount;s++)
                foreach(var root in SceneManager.GetSceneAt(s).GetRootGameObjects())
                    if(root.activeSelf) {disabledRoots.Add(root);root.SetActive(false);}
            worlds.Add(Build(floor.gameObject,prefab,position,false,false));
            worlds.Add(Build(floor.gameObject,prefab,position,true,false));
            worlds.Add(Build(floor.gameObject,prefab,position,true,true));
            Physics2D.SyncTransforms();
            foreach(var world in worlds)world.recorder.Capture(0,false);
            for(int index=1;index<worlds.Count;index++)
            {
                var timer=System.Diagnostics.Stopwatch.StartNew();
                for(int tick=0;tick<Ticks;tick++)
                {
                    if(!worlds[index].physics.Simulate(output.dt))throw new InvalidOperationException("Local simulate failed");
                    worlds[index].recorder.Capture(0,false);
                }
                if(index==1)output.local_same_order_ms=timer.Elapsed.TotalMilliseconds;
                else output.local_reversed_order_ms=timer.Elapsed.TotalMilliseconds;
            }
            var loop=PlayerLoop.GetCurrentPlayerLoop();
            if(!Insert(ref loop))throw new InvalidOperationException("Physics2DFixedUpdate missing");
            running=true;PlayerLoop.SetPlayerLoop(loop);
        }
        catch { Cleanup();throw; }
    }
    static World Build(GameObject floor,GameObject prefab,Vector3 position,bool local,bool reverse)
    {
        var world=new World();
        world.scene=SceneManager.CreateScene("SingleCollisionProbe_"+Guid.NewGuid().ToString("N"),
            new CreateSceneParameters(local?LocalPhysicsMode.Physics2D:LocalPhysicsMode.None));
        world.physics=world.scene.GetPhysicsScene2D();
        world.staging=new GameObject("Probe inactive staging");world.staging.SetActive(false);
        SceneManager.MoveGameObjectToScene(world.staging,world.scene);
        try
        {
            GameObject fruit;
            if(reverse) { fruit=Clone(prefab,world,position,true,local);Clone(floor,world,floor.transform.position,false,local); }
            else { Clone(floor,world,floor.transform.position,false,local);fruit=Clone(prefab,world,position,true,local); }
            world.recorder.Watch(fruit.GetComponent<FruitEvolution>(),"fruit");
            return world;
        }
        catch { SceneManager.UnloadSceneAsync(world.scene);throw; }
    }
    static GameObject Clone(GameObject source,World world,Vector3 position,bool dynamic,bool hide)
    {
        var clone=Object.Instantiate(source,world.staging.transform);
        clone.transform.position=position;clone.transform.rotation=source.transform.rotation;
        clone.transform.localScale=source.transform.lossyScale;
        foreach(var script in clone.GetComponents<MonoBehaviour>())script.enabled=false;
        if(hide)foreach(var renderer in clone.GetComponents<Renderer>())renderer.enabled=false;
        if(dynamic)
        {
            var danse=clone.GetComponent<Danse>();
            if(danse==null)throw new InvalidOperationException("Expected inspected Danse material initializer");
            world.material=danse.InitializePhysicsMaterial();
            var shape=clone.GetComponent<PolygonCollider2D>();shape.enabled=true;shape.isTrigger=false;
            var body=clone.GetComponent<Rigidbody2D>();if(body==null)body=clone.AddComponent<Rigidbody2D>();
            body.gravityScale=1;
            clone.GetComponent<FruitEvolution>().IsPreview=false;
        }
        clone.transform.SetParent(null,true);clone.SetActive(true);
        if(dynamic)
        {
            var body=clone.GetComponent<Rigidbody2D>();body.position=position;body.rotation=source.transform.eulerAngles.z;
            body.velocity=Vector2.zero;body.angularVelocity=0;body.WakeUp();
        }
        return clone;
    }
    static bool Insert(ref PlayerLoopSystem loop)
    {
        if(loop.subSystemList==null)return false;
        var list=new List<PlayerLoopSystem>(loop.subSystemList);
        for(int i=0;i<list.Count;i++)
        {
            if(list[i].type==typeof(UnityEngine.PlayerLoop.FixedUpdate.Physics2DFixedUpdate))
            {list.Insert(i+1,new PlayerLoopSystem {type=typeof(SingleCollisionProbe),updateDelegate=AfterPhysics});loop.subSystemList=list.ToArray();return true;}
            var child=list[i];if(Insert(ref child)){list[i]=child;loop.subSystemList=list.ToArray();return true;}
        }
        return false;
    }
    static void Remove(ref PlayerLoopSystem loop)
    {
        if(loop.subSystemList==null)return;
        var list=new List<PlayerLoopSystem>();
        foreach(var item in loop.subSystemList)
        {if(item.type==typeof(SingleCollisionProbe))continue;var child=item;Remove(ref child);list.Add(child);}
        loop.subSystemList=list.ToArray();
    }
    static void AfterPhysics()
    {
        if(!running)return;
        try
        {
            worlds[0].recorder.Capture(0,false);
            if(++ticks<Ticks)return;
            output.actual_impact_window=ImpactWindow(worlds[0].recorder);
            output.same_order_impact_window=ImpactWindow(worlds[1].recorder);
            output.reversed_order_impact_window=ImpactWindow(worlds[2].recorder);
            output.same_order=PredictionDiagnostics.Compare(worlds[1].recorder,worlds[0].recorder);
            output.reversed_order=PredictionDiagnostics.Compare(worlds[2].recorder,worlds[0].recorder);
            output.local_vs_local=PredictionDiagnostics.Compare(worlds[2].recorder,worlds[1].recorder);
            string path=Path.GetFullPath(Path.Combine(Application.dataPath,"../../Python/single_collision_probe.json"));
            File.WriteAllText(path,JsonUtility.ToJson(output,true));
            Debug.Log("Single collision probe complete: first differing ticks same="+output.same_order.first_numeric_tick+
                ", reversed="+output.reversed_order.first_numeric_tick+", local-vs-local="+output.local_vs_local.first_numeric_tick+"; "+path);
            Cleanup();
        }
        catch(Exception e){Cleanup();Debug.LogException(e);}
    }
    static PredictionDiagnostics.Frame[] ImpactWindow(PredictionDiagnostics.Recorder recorder)
    {
        int impact=recorder.frames.FindIndex(f=>f.fruits.Length>0 && f.fruits[0].contacts.Length>0);
        if(impact<0)return new[]{recorder.frames[0],recorder.frames[recorder.frames.Count-1]};
        return new[]{recorder.frames[0],recorder.frames[Math.Max(0,impact-1)],recorder.frames[impact],
            recorder.frames[Math.Min(impact+1,recorder.frames.Count-1)],recorder.frames[recorder.frames.Count-1]};
    }
    static void Cleanup()
    {
        running=false;
        var loop=PlayerLoop.GetCurrentPlayerLoop();Remove(ref loop);PlayerLoop.SetPlayerLoop(loop);
        foreach(var world in worlds)
        {
            world.recorder.recording=false;
            if(world.scene.IsValid())
            {
                foreach(var root in world.scene.GetRootGameObjects())root.SetActive(false);
                SceneManager.UnloadSceneAsync(world.scene);
            }
            if(world.material!=null)Object.Destroy(world.material);
        }
        worlds.Clear();
        foreach(var root in disabledRoots)if(root!=null)root.SetActive(true);
        disabledRoots.Clear();
    }
}
