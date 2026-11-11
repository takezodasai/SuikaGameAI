using System;
using System.Collections.Generic;
// Experimental root simple-regret allocation, never changes child UCT or reward.
public sealed class RootBudgetAllocation {
    [Serializable]public class Sample {public int index,visits;public double mean;public bool safe;}
    [Serializable]public class Audit {public int warmup_budget=40,total_budget=128,shortlist_cap=3,selected;public Sample[] initial,final;public int[] shortlist,extra_visits;public string rule="40 least-visited eligible, freeze top3 mean, 88 balanced extra, final highest mean; legacy all-GO fallback";}
    readonly Audit audit=new Audit();int[] shortlist,initialVisits;
    static bool Eligible(MctsPlanner.Edge e){return e.immediate==null||(e.immediate.drop_success&&!e.immediate.predicted_game_over);}
    static Sample[] Samples(MctsPlanner.Node root){var r=new Sample[root.actions.Length];for(int i=0;i<r.Length;i++){var e=root.actions[i];r[i]=new Sample{index=i,visits=e.visits,mean=e.Mean,safe=e.immediate!=null&&e.immediate.drop_success&&!e.immediate.predicted_game_over};}return r;}
    void Freeze(MctsPlanner.Node root){
        audit.initial=Samples(root);initialVisits=new int[root.actions.Length];var order=new List<int>();
        for(int i=0;i<root.actions.Length;i++){initialVisits[i]=root.actions[i].visits;if(root.actions[i].visits>0&&Eligible(root.actions[i]))order.Add(i);}
        order.Sort((a,b)=>{int c=root.actions[b].Mean.CompareTo(root.actions[a].Mean);if(c!=0)return c;c=root.actions[b].visits.CompareTo(root.actions[a].visits);return c!=0?c:a.CompareTo(b);});
        if(order.Count>3)order.RemoveRange(3,order.Count-3);shortlist=order.ToArray();audit.shortlist=shortlist;
    }
    public int Select(MctsPlanner.Node root,int iteration){
        if(root.depth!=0||root.actions.Length!=5)throw new ArgumentException("Root5 only");
        if(iteration<40){int best=-1;for(int i=0;i<5;i++)if(Eligible(root.actions[i])&&(best<0||root.actions[i].visits<root.actions[best].visits))best=i;return best>=0?best:MctsPlanner.Select(root,1.41421356,55);}
        if(shortlist==null)Freeze(root);int selected=-1;
        foreach(int i in shortlist)if(Eligible(root.actions[i])&&(selected<0||root.actions[i].visits-initialVisits[i]<root.actions[selected].visits-initialVisits[selected]))selected=i;
        return selected>=0?selected:MctsPlanner.Select(root,1.41421356,55);
    }
    public int Final(MctsPlanner.Node root){if(shortlist==null)Freeze(root);int best=-1;foreach(int i in shortlist)if(Eligible(root.actions[i])&&(best<0||root.actions[i].Mean>root.actions[best].Mean||(root.actions[i].Mean==root.actions[best].Mean&&root.actions[i].visits>root.actions[best].visits)))best=i;return best;}
    public Audit Finish(MctsPlanner.Node root,int selected){if(shortlist==null)Freeze(root);audit.selected=selected;audit.final=Samples(root);audit.extra_visits=new int[5];for(int i=0;i<5;i++)audit.extra_visits[i]=root.actions[i].visits-initialVisits[i];return audit;}
}
