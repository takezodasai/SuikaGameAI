using System;
using System.Collections.Generic;
// Pure, root-only action-set extension. No physics or random draws.
public static class RootCandidateRefinement {
    [Serializable]public class Anchor {public float x;public int visits;public double mean;public bool safe;}
    [Serializable]public class Stage {public int iteration,eligible;public string rule="safe anchors >=4 visits; descending mean, visits, index; top2 neighboring midpoints";public Anchor[] anchors;}
    public static Stage Last;
    public static List<MctsAdaptiveControl.Addition> Add(MctsPlanner.Node root,PlanningSettings settings,int iteration){
        var result=new List<MctsAdaptiveControl.Addition>();
        if(root.depth!=0||root.actions.Length!=5||root.positions==null||iteration!=32)return result;
        Last=new Stage{iteration=iteration,anchors=new Anchor[5]};for(int i=0;i<5;i++){var e=root.actions[i];Last.anchors[i]=new Anchor{x=root.positions.x[i],visits=e.visits,mean=e.Mean,safe=e.immediate!=null&&e.immediate.drop_success&&!e.immediate.predicted_game_over};}
        var ranked=new List<int>();
        for(int i=0;i<5;i++){var e=root.actions[i];if(e.visits>=4&&e.immediate!=null&&e.immediate.drop_success&&!e.immediate.predicted_game_over)ranked.Add(i);}
        Last.eligible=ranked.Count;
        ranked.Sort((a,b)=>{int c=root.actions[b].Mean.CompareTo(root.actions[a].Mean);if(c!=0)return c;c=root.actions[b].visits.CompareTo(root.actions[a].visits);return c!=0?c:a.CompareTo(b);});
        var chosen=new List<float>();var parents=new List<int>();
        // Each of the top two qualifying anchors gets one neighbor first. If only
        // one anchor is safe, its other neighbor can receive the remaining slot.
        for(int pass=0;pass<2&&chosen.Count<2;pass++)for(int r=0;r<Math.Min(2,ranked.Count)&&chosen.Count<2;r++){
            int parent=ranked[r];var sides=new List<int>();if(parent>0)sides.Add(parent-1);if(parent<4)sides.Add(parent+1);
            sides.Sort((a,b)=>{int c=Math.Abs(root.positions.x[b]-root.positions.x[parent]).CompareTo(Math.Abs(root.positions.x[a]-root.positions.x[parent]));if(c!=0)return c;return ((settings.mcts_seed^parent)&1)==0?a.CompareTo(b):b.CompareTo(a);});
            foreach(int neighbor in sides){float x=(root.positions.x[parent]+root.positions.x[neighbor])*.5f;if(chosen.Contains(x))continue;chosen.Add(x);parents.Add(parent);break;}
        }
        for(int j=0;j<chosen.Count;j++){
            int parent=parents[j],index=root.actions.Length;float x=chosen[j],anchor=root.positions.x[parent];
            double mean=root.actions[parent].Mean;int visits=root.actions[parent].visits;
            Array.Resize(ref root.actions,index+1);root.actions[index]=new MctsPlanner.Edge();
            Array.Resize(ref root.positions.x,index+1);Array.Resize(ref root.positions.sources,index+1);
            root.positions.x[index]=x;root.positions.sources[index]="root-ranked-midpoint";root.added_candidates++;
            result.Add(new MctsAdaptiveControl.Addition{iteration=iteration,node_id=root.id,depth=0,index=index,node_visits=root.visits,x=x,
                left=Math.Min(anchor,2*x-anchor),right=Math.Max(anchor,2*x-anchor),
                reason="root_top_anchor="+parent+";parent_visits="+visits+";parent_mean="+mean.ToString("R",System.Globalization.CultureInfo.InvariantCulture)+";remaining_iterations=96"});
        }
        return result;
    }
}
