using System;
using UnityEditor;
using UnityEngine;
using Object=UnityEngine.Object;

// Deterministic arithmetic/selection regressions. Does not change the live game.
public static class StepPlannerProbe
{
    [MenuItem("Tools/Suika/Reload Saved Scene If Clean %&F7")]
    public static void ReloadSavedScene()
    {
        if(Application.isPlaying) throw new InvalidOperationException("Stop Play first");
        var scene=UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene();
        if(scene.isDirty) throw new InvalidOperationException("Scene has unsaved changes; reload refused");
        UnityEditor.SceneManagement.EditorSceneManager.OpenScene(scene.path);
        Debug.Log("STEP5 reloaded saved scene: "+scene.path+" floor="+Object.FindObjectOfType<UDPCommunicatorUnity>().planningFloor);
    }
    static void Check(bool ok,string message) { if(!ok) throw new Exception("STEP5 regression: "+message); }
    [MenuItem("Tools/Suika/Run STEP5 Evaluation Tests %&F5")]
    public static void Run()
    {
        var s=new PlanningSettings();
        var f=new HeuristicEvaluator.Features {floor_y=0,go_y=10,left_x=0,right_x=10,
            fruits=new HeuristicEvaluator.FruitFeature[0]};
        var b=HeuristicEvaluator.Evaluate(f,55,s);
        Check(b.height==0 && b.danger==0 && b.roughness==0 && b.value==1,"empty board/score");
        f.fruits=new[]{new HeuristicEvaluator.FruitFeature {id=1,min_x=0,max_x=10,top_y=5,center_y=4,contacted=true,has_collided=true}};
        b=HeuristicEvaluator.Evaluate(f,0,s);
        Check(b.height==.5f && b.roughness<.00001f && Mathf.Abs(b.value)<.00001f && b.height_penalty==0,"height is diagnostic only");
        s.weight_height=100;
        Check(HeuristicEvaluator.Evaluate(f,0,s).value==b.value,"legacy height weight cannot restore penalty");
        s.weight_height=0;
        f.fruits[0].contacted=false;f.fruits[0].has_collided=false;f.fruits[0].center_y=10;
        b=HeuristicEvaluator.Evaluate(f,0,s);
        Check(b.height==0 && b.roughness==0 && b.danger==.5f,"airborne remains risky");
        s.weight_danger=100;
        Check(b.value==0 && b.danger_penalty==0 && HeuristicEvaluator.Evaluate(f,0,s).value==0,"D/legacy weight diagnostic only");
        Check(s.Freeze().weight_danger==0,"legacy D weight cleared from frozen settings");
        f.fruits[0].has_collided=true;
        Check(HeuristicEvaluator.Evaluate(f,0,s).danger==1,"bounced contacted flag retained");
        var normal=new StepPlanner.Candidate {index=0,x=0,success=true,drop_success=true,
            evaluation=new HeuristicEvaluator.Breakdown {value=0},drop_tick=5};
        var tied=new StepPlanner.Candidate {index=1,x=1,success=true,drop_success=true,
            evaluation=new HeuristicEvaluator.Breakdown {value=0,danger=0},drop_tick=5};
        normal.evaluation.danger=1;
        var tieDecision=new StepPlanner.Decision {candidates=new[]{normal,tied}};
        StepPlanner.Choose(tieDecision);Check(tieDecision.selected_index==0,"D must not break normal ties");
        var go=new StepPlanner.Candidate {index=1,x=1,success=true,predicted_game_over=true,
            evaluation=new HeuristicEvaluator.Breakdown {value=100},game_over_tick=10};
        var d=new StepPlanner.Decision {candidates=new[]{normal,go}};
        StepPlanner.Choose(d);Check(d.selected_index==0,"terminal must not win via score");
        normal.predicted_game_over=true;normal.game_over_tick=20;
        d.selected_index=-1; StepPlanner.Choose(d);
        Check(d.selected_index==0 && d.all_predicted_terminal,"terminal survival fallback");
        normal.success=false;d.selected_index=-1;d.all_predicted_terminal=false;StepPlanner.Choose(d);
        Check(d.selected_index==-1 && d.status=="no_nonterminal_evaluated","unknown must not be treated terminal");
        normal.success=true;normal.predicted_game_over=false;normal.drop_success=true;
        go.success=false;StepPlanner.Choose(d);Check(d.selected_index==0 && d.partial_plan,"partial safe plan");
        Debug.Log("PASS STEP5: empty/flat/airborne/bounced features, terminal exclusion, survival fallback, failed/partial choices");
    }

    // A short isolated Play fixture for stop-at-GO client verification; reset clears it.
    [MenuItem("Tools/Suika/Arm STEP5 Game Over Fixture %&F6")]
    public static void ArmGameOverFixture()
    {
        if(!Application.isPlaying) throw new InvalidOperationException("Requires Play");
        var manager=Object.FindObjectOfType<GameManager>();
        var player=Object.FindObjectOfType<PlayerController>();
        var fruit=Object.Instantiate(player.fruits[0]);
        fruit.tag="Fruit";
        fruit.transform.position=new Vector3(0,manager.GameOverHeight+1,0);
        var body=fruit.GetComponent<Rigidbody2D>();
        if(body==null) body=fruit.AddComponent<Rigidbody2D>();
        PlayerController.ReleaseFruitBody(body);
        FruitColliderShape.Get(fruit).isTrigger=false;
        body.velocity=Vector2.zero;
        typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(fruit.GetComponent<FruitEvolution>(),new object[]{true});
        Debug.Log("STEP5 GO fixture armed; reset removes the fixture.");
    }
}
