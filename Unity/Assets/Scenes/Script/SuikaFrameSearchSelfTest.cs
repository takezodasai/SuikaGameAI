using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Owned diagnostic Player only. No scene/prefab/physics-setting writes.
public sealed class SuikaFrameSearchSelfTest : MonoBehaviour
{
    [Serializable] class Report {public string status="running",error;public List<string> passed=new List<string>();public List<double> elapsed_ms=new List<double>();public List<MassParity> next_mass_parity=new List<MassParity>();public int scenes_after;}
    [Serializable] class MassParity {public int slot;public float mass_error,inertia_error,center_error;public bool bit_exact;}
    [Serializable] class Tree {public MctsPlanner.NodeMetric[] nodes;}
    static string destination;readonly Report report=new Report();
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install()
    {
        var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaFrameSelfTest");if(i<0)return;
        destination=a[i+1];new GameObject("Frame execution tests").AddComponent<SuikaFrameSearchSelfTest>();
    }
    static Rigidbody2D ReleasedBody(SuikaPhysicsSimulator.PathSession path,long id)
    {
        var binding=System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance;
        var owner=typeof(SuikaPhysicsSimulator.PathSession).GetField("owner",binding).GetValue(path);
        var ids=(Dictionary<FruitEvolution,long>)typeof(SuikaPhysicsSimulator).GetField("ids",binding).GetValue(owner);
        foreach(var pair in ids)if(pair.Value==id)return pair.Key.GetComponent<Rigidbody2D>();return null;
    }
    void Check(bool value,string label){if(!value)throw new Exception(label);report.passed.Add(label);}
    IEnumerator Start()
    {
        yield return null;yield return null;
        var player=FindObjectOfType<PlayerController>();var manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        try {
            var estimator=new FrameLeadEstimator();estimator.SetConfiguration("32-depth4");
            Check(estimator.Suggest(150)==150,"adaptive cold start retains old lead");
            estimator.Observe(20,2);Check(estimator.Suggest(150)==29,"adaptive lead uses full-search ticks and measured frame gaps");
            Check(FrameLeadEstimator.RetryLead(29,30,true)==60,"missed deadline grows reservation, never trims search");
            Check(FrameLeadEstimator.RetryLead(29,150,false)==29,"state mismatch does not double wait by itself");
            estimator.ObserveMiss(40);Check(estimator.Suggest(150)>=80,"misses update the next reservation instead of causing permanent repeated undershoot");
            estimator.SetConfiguration("64-depth6");Check(estimator.Count==0 && estimator.Suggest(150)==150,"different depth/iterations require new calibration");
            var frame=new PredictionDiagnostics.Frame {fruits=new[]{new PredictionDiagnostics.FruitState {id="f1",type=0,contacts=new PredictionDiagnostics.Contact[0]}}};
            Check(FrameStateDifference.Compare(frame,frame).valid,"identical exposed state accepted");
            var other=JsonUtility.FromJson<PredictionDiagnostics.Frame>(JsonUtility.ToJson(frame));other.fruits[0].position.x=.0000001f;
            Check(!FrameStateDifference.Compare(frame,other).valid,"nonzero position error not silently accepted");
            other=JsonUtility.FromJson<PredictionDiagnostics.Frame>(JsonUtility.ToJson(frame));other.fruits[0].id="f2";
            Check(!FrameStateDifference.Compare(frame,other).valid,"different identity rejected despite matching type/position");
            other=JsonUtility.FromJson<PredictionDiagnostics.Frame>(JsonUtility.ToJson(frame));other.fruits[0].has_collided=true;
            Check(!FrameStateDifference.Compare(frame,other).valid,"GO contact eligibility mismatch rejected");
        }catch(Exception e){report.error=e.ToString();}
        // Native disabled-body getters may be zero, especially grape NEXT. Test
        // every public spawn slot through a frozen-root fork and two releases.
        for(int slot=0;slot<player.fruits.Length && report.error==null;slot++)
        {
            manager.ResetGame("preview_fork");yield return null;yield return null;
            try {
                player.nextFruitObject.SetActive(false);Destroy(player.nextFruitObject);
                player.nextFruitObject=Instantiate(player.fruits[slot]);
                player.nextFruitObject.GetComponent<FruitEvolution>().IsPreview=true;
                PlayerController.PreparePreviewBody(player.nextFruitObject,true);FruitColliderShape.Get(player.nextFruitObject).isTrigger=true;
                using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
                using(var fork=root.Fork(manager)) {
                    // Compare the extra fork against the existing native PathSession
                    // at identical spawn/movement coordinates. A fresh body at x=100
                    // has different float shape construction and is not a valid control.
                    using(var baseline=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor)) {
                        baseline.Advance(0,25,0);baseline.Advance(1,25,0);
                        var firstResult=fork.Advance(0,25,0);var secondResult=fork.Advance(1,25,0);
                        var actual=ReleasedBody(fork,-2);var expected=ReleasedBody(baseline,-2);
                        Check(actual!=null && expected!=null && actual.mass==expected.mass && actual.inertia>0 && expected.inertia>0 &&
                            !float.IsNaN(actual.inertia) && !float.IsInfinity(actual.inertia) && !float.IsNaN(actual.centerOfMass.x) && !float.IsNaN(actual.centerOfMass.y),
                            "frozen NEXT mass exact and automatic shape properties finite slot "+slot);
                        report.next_mass_parity.Add(new MassParity {slot=slot,mass_error=Mathf.Abs(actual.mass-expected.mass),
                            inertia_error=Mathf.Abs(actual.inertia-expected.inertia),center_error=Vector2.Distance(actual.centerOfMass,expected.centerOfMass),
                            bit_exact=actual.inertia==expected.inertia && actual.centerOfMass==expected.centerOfMass});
                        Check(firstResult.drop_success && secondResult.drop_success,"inactive NEXT slot "+slot+" survives frozen fork and second drop");
                    }
                }
            }catch(Exception e){report.error=e.ToString();}
        }
        foreach(int depth in new[]{3,4,5,6})
        {
            if(report.error!=null)break;
            manager.ResetGame("frame_fixture");yield return null;yield return null;
            IEnumerator<StepPlanner.Decision> work=null;SuikaPhysicsSimulator.PathSession root=null;StepPlanner.Decision synchronous=null,result=null;
            var watch=System.Diagnostics.Stopwatch.StartNew();double fixedStart=Time.fixedTimeAsDouble;
            try {
                var settings=new PlanningSettings {ai_mode="mcts",mcts_iterations=32,mcts_max_depth=depth};
                for(int kind=0;kind<2;kind++) {
                    var fruit=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[kind],new Vector3(kind==0?-.3f:.3f,udp.planningFloor.bounds.max.y+.3f,0),Quaternion.identity);
                    fruit.GetComponent<FruitEvolution>().IsPreview=false;var body=fruit.GetComponent<Rigidbody2D>();if(body==null)body=fruit.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(body);FruitColliderShape.Get(fruit).isTrigger=false;
                    var danse=fruit.GetComponent<Danse>();if(danse!=null)danse.InitializePhysicsMaterial();
                }
                Physics2D.SyncTransforms();
                synchronous=MctsPlanner.Plan(player,manager,udp.planningFloor,settings);
                root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor);
                using(var fork=root.Fork(manager))Check(root.StateSignature()==fork.StateSignature(),"frozen native root copy exact at depth "+depth);
                work=MctsPlanner.PlanFrames(player,manager,root.LocalFloor,settings,root);
            }catch(Exception e){report.error=e.ToString();}
            bool more=work!=null;
            while(more && report.error==null)
            {
                try {more=work.MoveNext();if(more&&work.Current!=null)result=work.Current;}
                catch(Exception e){report.error=e.ToString();}
                yield return null;
            }
            try {
                if(report.error==null){
                    Check(synchronous.selected_index==result.selected_index,"sync/sliced selected action exact at depth "+depth);
                    Check(JsonUtility.ToJson(new Tree {nodes=synchronous.mcts.nodes})==JsonUtility.ToJson(new Tree {nodes=result.mcts.nodes}),"sync/sliced full UCT tree exact at depth "+depth);
                    Check(result.mcts.completed_iterations==32,"requested iterations preserved at depth "+depth);
                    Check(Time.fixedTimeAsDouble>fixedStart,"live fixed clock advanced while frozen-root search yielded at depth "+depth);
                }
            }catch(Exception e){report.error=e.ToString();}
            if(work!=null)work.Dispose();if(root!=null)root.Dispose();report.elapsed_ms.Add(watch.Elapsed.TotalMilliseconds);
            yield return null;yield return null;
        }
        // Request lifecycle tests use the existing UDP handler without actual I/O
        // injection. Forced GO is a cancellation fixture, not a GO accuracy test.
        foreach(bool tickSlicing in new[]{false,true})
        foreach(bool forceGO in new[]{false,true})
        {
            if(report.error!=null)break;
            manager.ResetGame("frame_cancel_fixture");yield return null;yield return null;
            long held=player.currentFruit.GetComponent<FruitEvolution>().ObservationId;
            try {
                var binding=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic;
                var type=typeof(UDPCommunicatorUnity);
                var m=new UDPCommunicatorUnity.ActionMessage {command="plan_step",x=.5f,action_id=1,
                    stream_id=(string)type.GetField("streamId",binding).GetValue(udp),episode_id=(string)type.GetField("episodeId",binding).GetValue(udp),
                    planning_settings=new PlanningSettings {ai_mode="mcts",execution_mode="frames",frame_tick_slicing=tickSlicing,mcts_iterations=32,mcts_max_depth=6}};
                var method=type.GetMethod("HandleStep",binding);method.Invoke(udp,new object[]{m,null});
                var first=(FrameSearchReport)type.GetField("frameReport",binding).GetValue(udp);
                method.Invoke(udp,new object[]{m,null});
                Check(object.ReferenceEquals(first,type.GetField("frameReport",binding).GetValue(udp)),"duplicate packet preserves single in-flight request GO="+forceGO);
            }catch(Exception e){report.error=e.ToString();}
            yield return null;yield return null;yield return null;
            try {
                if(forceGO)typeof(GameManager).GetMethod("GameOver",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).Invoke(manager,null);
                else manager.ResetGame("cancel_during_search");
            }catch(Exception e){report.error=e.ToString();}
            yield return null;yield return null;
            try {
                var binding=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic;
                var ended=(FrameSearchReport)typeof(UDPCommunicatorUnity).GetField("lastFrameSearch",binding).GetValue(udp);
                Check(ended!=null && ended.final_policy=="cancelled" && ended.reason==(forceGO?"game_over":"reset"),"GO/reset cancellation audited GO="+forceGO);
                Check(!player.StepControlLocked,"cancel unlocks held input GO="+forceGO);
                Check(forceGO?held==player.currentFruit.GetComponent<FruitEvolution>().ObservationId:held!=player.currentFruit.GetComponent<FruitEvolution>().ObservationId,"cancel never drops stale held fruit GO="+forceGO);
            }catch(Exception e){report.error=e.ToString();}
        }
        manager.ResetGame("after_lifecycle_tests");yield return null;yield return null;
        // Disposing an unfinished search must also release its active trajectory.
        if(report.error==null)try {
            using(var root=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
            using(var work=MctsPlanner.PlanFrames(player,manager,root.LocalFloor,new PlanningSettings {ai_mode="mcts"},root))
                Check(work.MoveNext(),"partially executed search can be cancelled");
        }catch(Exception e){report.error=e.ToString();}
        yield return null;yield return null;yield return null;
        for(int i=0;i<UnityEngine.SceneManagement.SceneManager.sceneCount;i++)if(UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).name.StartsWith("SuikaPrediction_"))report.scenes_after++;
        if(report.error==null)try {Check(report.scenes_after==0,"all retained roots and cancelled trajectories released");}catch(Exception e){report.error=e.ToString();}
        report.status=report.error==null?"passed":"failed";
        if(File.Exists(destination))throw new IOException("Refuse overwrite");File.WriteAllText(destination,JsonUtility.ToJson(report,true));Application.Quit(report.error==null?0:1);
    }
}
