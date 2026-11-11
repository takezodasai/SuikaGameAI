using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Measures prediction error; never changes the predictor or game's physical rules.
public sealed class SuikaPhysicsAuditProbe : MonoBehaviour {
    [Serializable] class Case {public string fixture,label;public int warm_ticks,natural_prefix;}
    [Serializable] class Config {public string output;public Case[] cases;public float[] positions;}
    [Serializable] class Row {
        public string label,fixture,source;public float x,actual_applied_x,predicted_heuristic,actual_heuristic;
        public int warm_ticks,natural_prefix,actual_drop_tick,actual_ticks,actual_score,actual_merges;
        public bool actual_go,actual_drop,mcts_first_agrees;
        public ValueSnapshot initial,actual_after;public SuikaPhysicsSimulator.Result predicted;
        public PredictionDiagnostics.Report comparison;
        public PredictionDiagnostics.Frame first_property_actual,first_property_prediction,first_contact_actual,first_contact_prediction;
    }
    static string config;PlayerController player;GameManager game;UDPCommunicatorUnity udp;SuikaCounterfactualProbe restore;
    bool driving;float targetX,applied;int tick,drop=-1;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {
        var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaPhysicsAudit");if(i>=0){config=a[i+1];new GameObject("Physical reliability audit").AddComponent<SuikaPhysicsAuditProbe>();}
    }
    void FixedUpdate() {
        if(waiting)waitTicks++;
        if(!driving)return;tick++;if(drop>=0)return;
        var range=player.GetDropRange();float x=Mathf.Lerp(range.min_x,range.max_x,targetX),nx=Mathf.MoveTowards(player.currentFruit.transform.position.x,x,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);string error;
        if(!player.TryMoveHeldTo(nx,range,out error))throw new Exception(error);
        if(nx==x&&player.CanDropFruit){long id;if(!player.TryDropAt(targetX,out applied,out id,out range,out error))throw new Exception(error);drop=tick;}
    }
    IEnumerator Execute(float x) {
        targetX=x;tick=0;drop=-1;driving=true;player.StepControlLocked=true;Time.timeScale=1;
        while(tick<200&&!game.isGameOver&&(drop<0||tick-drop<25))yield return null;
        driving=false;player.StepControlLocked=false;Time.timeScale=0;
    }
    HeuristicEvaluator.Features LiveFeatures() {
        var r=player.GetDropRange();var list=new List<HeuristicEvaluator.FruitFeature>();
        foreach(var f in FindObjectsOfType<FruitEvolution>())if(f.Simulation==null&&!f.IsPreview&&!f.IsMerging) {
            var shape=FruitColliderShape.Get(f.gameObject);var contacts=new List<ContactPoint2D>();f.GetComponent<Rigidbody2D>().GetContacts(contacts);bool touching=false;
            foreach(var c in contacts){var other=c.collider.gameObject==f.gameObject?c.otherCollider:c.collider;if(other==null||!other.enabled||other.isTrigger||!other.gameObject.activeInHierarchy)continue;var v=other.GetComponent<FruitEvolution>();if(v!=null&&(v.IsPreview||v.IsMerging))continue;if(v!=null||other.CompareTag("Wall")||other.gameObject==udp.planningFloor.gameObject)touching=true;}
            list.Add(new HeuristicEvaluator.FruitFeature {id=f.ObservationId,contacted=touching,has_collided=f.HasCollided,min_x=shape.bounds.min.x,max_x=shape.bounds.max.x,top_y=shape.bounds.max.y,center_y=f.transform.position.y});
        }
        return new HeuristicEvaluator.Features {fruits=list.ToArray(),floor_y=udp.planningFloor.bounds.max.y,go_y=game.GameOverHeight,left_x=r.left_wall_inner,right_x=r.right_wall_inner};
    }
    IEnumerator Setup(Case c) {
        PredictionDiagnostics.Stop();
        if(c.natural_prefix>0) {
            Time.timeScale=0;UnityEngine.Random.InitState(99117);game.ResetGame("natural-audit");Time.timeScale=0;yield return null;yield return null;
            for(int i=0;i<c.natural_prefix;i++){yield return Execute(i%2==0?.25f:.75f);if(game.isGameOver)throw new Exception("Natural prefix terminated");}
        } else yield return restore.RestoreForAudit(player,game,udp,c.fixture);
        if(c.warm_ticks>0) {
            driving=false;Time.timeScale=1;
            // Count actual fixed callbacks while waiting, without an input/drop.
            waiting=true;waitTicks=0;while(waitTicks<c.warm_ticks&&!game.isGameOver)yield return null;waiting=false;Time.timeScale=0;
        }
    }
    bool waiting;int waitTicks;
    IEnumerator Start() {
        yield return null;yield return null;var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));
        player=FindObjectOfType<PlayerController>();game=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        restore=gameObject.AddComponent<SuikaCounterfactualProbe>();restore.enabled=false;Application.targetFrameRate=60;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(var test in c.cases)foreach(float x in c.positions) {
            yield return Setup(test);if(game.isGameOver)throw new Exception("Source already GO");
            var row=new Row {label=test.label,fixture=test.fixture,x=x,warm_ticks=test.warm_ticks,natural_prefix=test.natural_prefix,source=test.natural_prefix>0?"natural_prefix_actual_world":"reconstructed_fixture",initial=udp.CounterfactualSnapshot()};
            SuikaDecisionCapsules.Capture(udp,player,game,test.label,Array.IndexOf(c.positions,x)+1,0,new PlanningSettings());
            PredictionDiagnostics.Recorder predicted;
            using(var root=new SuikaPhysicsSimulator.PathSession(player,game,udp.planningFloor)) {
                using(var path=root.Fork(game)){path.EnableTrace();row.predicted=path.Advance(x,25,0);predicted=row.predicted.trace;}
                StepPlanner.Decision mcts=null;using(var search=MctsPlanner.PlanFrames(player,game,root.LocalFloor,new PlanningSettings {ai_mode="mcts",mcts_iterations=32,mcts_max_depth=4},root))while(search.MoveNext())if(search.Current!=null)mcts=search.Current;
                int index=Mathf.RoundToInt(x*4);var candidate=mcts.candidates[index];
                row.mcts_first_agrees=candidate.reward==row.predicted.reward&&candidate.predicted_game_over==row.predicted.game_over&&candidate.physics_steps==row.predicted.physics_steps;
            }
            row.predicted_heuristic=HeuristicEvaluator.Evaluate(row.predicted.evaluation_features,row.predicted.reward,new PlanningSettings()).value*55;
            int initialMerges=ScoreManager.Instance.EpisodeMergeCount;PredictionDiagnostics.Begin(player,game);yield return Execute(x);
            row.actual_applied_x=drop>=0?applied:0;row.actual_drop_tick=drop;row.actual_ticks=tick;row.actual_drop=drop>=0;row.actual_score=ScoreManager.Instance.GetScore();row.actual_go=game.isGameOver;
            row.actual_merges=ScoreManager.Instance.EpisodeMergeCount-initialMerges;row.actual_after=udp.CounterfactualSnapshot();row.actual_heuristic=HeuristicEvaluator.Evaluate(LiveFeatures(),row.actual_score-row.initial.score,new PlanningSettings()).value*55;
            row.comparison=PredictionDiagnostics.Compare(predicted);row.comparison.actual_completion_game_over=game.isGameOver;row.comparison.predicted_completion_game_over=row.predicted.game_over;
            foreach(var e in row.comparison.errors) {
                if(row.first_property_actual==null&&(e.mass>1e-6||e.inertia>1e-6||e.center_of_mass>1e-6)){row.first_property_actual=PredictionDiagnostics.Live.frames[e.tick];row.first_property_prediction=predicted.frames[e.tick];}
                if(row.first_contact_actual==null&&!e.contacts_match){row.first_contact_actual=PredictionDiagnostics.Live.frames[e.tick];row.first_contact_prediction=predicted.frames[e.tick];}
            }
            PredictionDiagnostics.Stop();log.WriteLine(JsonUtility.ToJson(row));log.Flush();
        }
        Debug.Log("PHYSICS AUDIT COMPLETE");Application.Quit(0);
    }
}
