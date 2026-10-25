using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;

// Root-only proposals. Keep all coarse anchors; future decisions remain the old five-grid.
public static class CoarseToFineCandidates {
    [Serializable] public class Report {
        public StepPlanner.Candidate[] coarse;public float[] geometry,positions,added;public int[] parents,ranking;
        public double total_ms;public int physics_ticks,physics_advances;
        public string rule="safe coarse reward/55 - 0.2R; geometry tie-break; two distinct parent neighborhoods; all five anchors retained";
    }
    public static float[] Refine(float[] values,bool[] safe,float[] geometry,float[] fineGeometry,out int[] ranking,out int[] parents) {
        if(values.Length!=5||safe.Length!=5||geometry.Length!=5||fineGeometry.Length!=4)throw new ArgumentException("Five coarse/four midpoint features required");
        var rank=new List<int>{0,1,2,3,4};
        rank.Sort((a,b)=>safe[a]!=safe[b]?(safe[a]?-1:1):values[a]!=values[b]?values[b].CompareTo(values[a]):geometry[a]!=geometry[b]?geometry[b].CompareTo(geometry[a]):a.CompareTo(b));
        var used=new HashSet<int>();var selected=new List<float>();var from=new List<int>();
        foreach(int parent in rank) {
            int best=-1;
            foreach(int j in new[]{parent-1,parent})if(j>=0&&j<4&&!used.Contains(j)&&(best<0||fineGeometry[j]>fineGeometry[best]||(fineGeometry[j]==fineGeometry[best]&&j<best)))best=j;
            if(best<0)continue;
            used.Add(best);selected.Add((best+.5f)/4);from.Add(parent);
            if(selected.Count==2)break;
        }
        if(selected.Count!=2)throw new InvalidOperationException("Incomplete refinement");
        ranking=rank.ToArray();parents=from.ToArray();return selected.ToArray();
    }
    public static Report Build(SuikaPhysicsSimulator.PathSession root,GameManager manager,PlanningSettings s) {
        var r=new Report {coarse=new StepPlanner.Candidate[5]};
        var coarse=new[]{0f,.25f,.5f,.75f,1f};var fine=new[]{.125f,.375f,.625f,.875f};
        r.geometry=root.RolloutScores(coarse);var fineGeometry=root.RolloutScores(fine);
        var values=new float[5];var safe=new bool[5];
        for(int i=0;i<5;i++)using(var path=root.Fork(manager)) {
            // Only public A is dropped. Hypothetical C is irrelevant to this one-drop reward/geometry.
            var result=path.Advance(coarse[i],s.post_drop_steps,0);
            var c=TwoStepPlanner.Candidate(i,coarse[i],result,s);r.coarse[i]=c;
            values[i]=c.evaluation.value;safe[i]=c.drop_success&&!c.predicted_game_over;
            r.physics_ticks+=path.TotalTicks;r.physics_advances++;
        }
        r.added=Refine(values,safe,r.geometry,fineGeometry,out r.ranking,out r.parents);
        var all=new List<float>(coarse);all.AddRange(r.added);all.Sort();r.positions=all.ToArray();return r;
    }
}
