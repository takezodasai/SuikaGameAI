using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.SceneManagement;

// Owns only prediction Scene handles. No live Scene, prefab asset or global RNG writes.
public static class PredictionLifecycle {
    static readonly HashSet<int> scenes=new HashSet<int>();
    public static long Created,Released;public static int Pending,LiveOwners,PeakScenes;
    public static double ReleaseMs;
    public static bool Legacy {get;private set;}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)] static void Init(){
        scenes.Clear();Created=Released=0;Pending=LiveOwners=PeakScenes=0;ReleaseMs=0;
        Legacy=Array.IndexOf(Environment.GetCommandLineArgs(),"-suikaLegacyPredictionCleanup")>=0;
    }
    public static void Register(Scene scene){scenes.Add(scene.handle);Created++;LiveOwners++;PeakScenes=Math.Max(PeakScenes,scenes.Count);}
    public static int RetainedScenes {get{return scenes.Count;}}
    public static void Release(Scene scene){
        LiveOwners--;
        if(!scenes.Contains(scene.handle)||!scene.name.StartsWith("SuikaPrediction_",StringComparison.Ordinal))throw new InvalidOperationException("Refusing to unload an unowned Scene");
        var clock=Stopwatch.StartNew();
        if(Legacy){
            Pending++;int handle=scene.handle;var operation=SceneManager.UnloadSceneAsync(scene);
            if(operation==null)throw new InvalidOperationException("Prediction async unload was not scheduled");
            operation.completed+=ignored=>{Pending--;scenes.Remove(handle);Released++;};
        } else {
            // 2022.3-only guarded synchronous disposal. Never called inside Simulate,
            // a collision callback, or for an actual-game Scene. Reusing a native
            // PhysicsScene could change hidden solver state, so keep fresh worlds.
#pragma warning disable 0618
            bool unloaded=SceneManager.UnloadScene(scene);
#pragma warning restore 0618
            if(!unloaded||scene.IsValid())throw new InvalidOperationException("Prediction synchronous Scene unload did not finish");
            scenes.Remove(scene.handle);Released++;
        }
        ReleaseMs+=clock.Elapsed.TotalMilliseconds;
    }
    [Serializable] public class Sample {
        public long created,released;public int retained_scenes,pending_unloads,live_owners,scene_count,objects,gc0,gc1,gc2;
        public long managed_live,managed_heap,unity_allocated,unity_reserved,unity_unused_reserved,working_set,private_bytes;
        public double release_ms;
    }
    [StructLayout(LayoutKind.Sequential)] struct MemoryCounters {
        public uint size,page_faults;
        public UIntPtr peak_working_set,working_set,peak_paged,paged,peak_nonpaged,nonpaged,pagefile,peak_pagefile,private_bytes;
    }
#if UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("psapi.dll",SetLastError=true)] static extern bool GetProcessMemoryInfo(IntPtr process,ref MemoryCounters counters,uint size);
#endif
    public static Sample Read(bool countObjects=true){
        long working=-1,committed=-1;
#if UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN
        var counters=new MemoryCounters();counters.size=(uint)Marshal.SizeOf(typeof(MemoryCounters));
        if(GetProcessMemoryInfo(GetCurrentProcess(),ref counters,counters.size)){working=(long)counters.working_set.ToUInt64();committed=(long)counters.private_bytes.ToUInt64();}
#endif
        return new Sample {
            created=Created,released=Released,retained_scenes=scenes.Count,pending_unloads=Pending,live_owners=LiveOwners,scene_count=SceneManager.sceneCount,
            objects=countObjects?Resources.FindObjectsOfTypeAll<GameObject>().Length:-1,
            gc0=GC.CollectionCount(0),gc1=GC.CollectionCount(1),gc2=GC.CollectionCount(2),managed_live=GC.GetTotalMemory(false),
            managed_heap=UnityEngine.Profiling.Profiler.GetMonoHeapSizeLong(),unity_allocated=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong(),
            unity_reserved=UnityEngine.Profiling.Profiler.GetTotalReservedMemoryLong(),unity_unused_reserved=UnityEngine.Profiling.Profiler.GetTotalUnusedReservedMemoryLong(),
            working_set=working,private_bytes=committed,release_ms=ReleaseMs};
    }
}
