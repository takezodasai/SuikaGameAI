using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class SuikaValueProbe
{
    [Serializable] public class Row {public float[] values;}
    [Serializable] public class Case {public ValueSnapshot state;public Row[] fruits;public float[] global_features;public float expected;}
    [Serializable] public class Fixtures {public Case[] cases;}
    [MenuItem("Tools/Suika/Test Value Parity And Build %&F10")]
    public static void TestAndBuild()
    {Run();SuikaWorkerBuild.Build();}
    [MenuItem("Tools/Suika/Test Value Parity")]
    public static void Run()
    {
        var network=SuikaValueNetwork.Load("");
        var fixtures=JsonUtility.FromJson<Fixtures>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"suika_value_parity.json")));
        float maxFeature=0,maxPoints=0;
        var watch=System.Diagnostics.Stopwatch.StartNew();int count=0;
        foreach(var c in fixtures.cases)
        {
            float[] g;var rows=SuikaValueNetwork.Encode(c.state,out g);
            if(rows.Length!=c.fruits.Length) throw new Exception("Value fruit count mismatch");
            for(int i=0;i<rows.Length;i++) for(int j=0;j<30;j++) maxFeature=Math.Max(maxFeature,Math.Abs(rows[i][j]-c.fruits[i].values[j]));
            for(int j=0;j<37;j++) maxFeature=Math.Max(maxFeature,Math.Abs(g[j]-c.global_features[j]));
            float actual=network.PredictEncoded(rows,g);maxPoints=Math.Max(maxPoints,Math.Abs(actual-c.expected));count++;
        }
        if(maxFeature>0.00001f || maxPoints>0.02f) throw new Exception("Value parity failed: features="+maxFeature+" points="+maxPoints);
        var report=new Report {cases=count,max_feature_error=maxFeature,max_points_error=maxPoints,total_ms=watch.Elapsed.TotalMilliseconds,model_sha256=network.file_sha256};
        Directory.CreateDirectory("../Python/outputs/value_7c_parity");
        // Never replace an earlier diagnostic report when rebuilding a Player.
        string output=Path.Combine("../Python/outputs/value_7c_parity","unity_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N")+".json");
        using(var stream=new StreamWriter(new FileStream(output,FileMode.CreateNew)))stream.Write(JsonUtility.ToJson(report,true));
        StepPlannerProbe.Run();
        var a=new StepPlanner.Candidate {index=0,x=0,success=true,drop_success=true,value_evaluated=true,q_points=100,
            evaluation=new HeuristicEvaluator.Breakdown {value=999},drop_tick=2};
        var b=new StepPlanner.Candidate {index=1,x=1,success=true,drop_success=true,value_evaluated=true,q_points=101,
            evaluation=new HeuristicEvaluator.Breakdown {value=-999},drop_tick=3};
        var d=new StepPlanner.Decision {candidates=new[]{a,b}};StepPlanner.Choose(d);
        if(d.selected_index!=1) throw new Exception("Value selection must use point Q, not heuristic");
        b.predicted_game_over=true;StepPlanner.Choose(d);
        if(d.selected_index!=0) throw new Exception("Value cannot override GO exclusion");
        a.predicted_game_over=true;a.game_over_tick=10;b.game_over_tick=20;StepPlanner.Choose(d);
        if(d.selected_index!=1 || !d.all_predicted_terminal) throw new Exception("Existing terminal survival fallback changed");
        var permutation=fixtures.cases[0];float v1=network.Predict(permutation.state);
        Array.Reverse(permutation.state.fruits);float v2=network.Predict(permutation.state);
        if(Math.Abs(v1-v2)>.02f) throw new Exception("Fruit order sensitivity");
        Debug.Log("VALUE PARITY OK "+JsonUtility.ToJson(report));
    }
    [Serializable] class Report {public int cases;public float max_feature_error,max_points_error;public double total_ms;public string model_sha256;}
}
