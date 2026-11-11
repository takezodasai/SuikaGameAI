using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
public sealed class SuikaStagedAllocationTest:MonoBehaviour {
    [Serializable]class Report{public string error;public List<string> passed=new List<string>();}Report r=new Report();static string path;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaStagedAllocationTest");if(i>=0){path=a[i+1];new GameObject("Staged tests").AddComponent<SuikaStagedAllocationTest>();}}
    void Check(bool v,string name){if(!v)throw new Exception(name);r.passed.Add(name);}
    IEnumerator Start(){yield return null;yield return null;try{
        var n=new MctsPlanner.Node(5,0,0);foreach(var e in n.actions)e.immediate=new StepPlanner.Candidate{drop_success=true};var allocation=new RootBudgetAllocation();
        for(int k=0;k<128;k++){int i=allocation.Select(n,k);n.visits++;n.actions[i].Add(i*10,false);}
        var audit=allocation.Finish(n,allocation.Final(n));foreach(var x in audit.initial)Check(x.visits==8,"warmup eight "+x.index);
        Check(audit.shortlist.Length==3&&audit.selected==4,"top3 and maxmean");int extras=0;for(int i=0;i<5;i++)extras+=audit.extra_visits[i];Check(extras==88,"exact88 extra");Check(audit.extra_visits[0]==0&&audit.extra_visits[1]==0,"eliminated no extra");
        int lo=999,hi=0;foreach(int i in audit.shortlist){lo=Math.Min(lo,audit.extra_visits[i]);hi=Math.Max(hi,audit.extra_visits[i]);}Check(hi-lo<=1,"balanced shortlist");
        var player=FindObjectOfType<PlayerController>();var game=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();var s=new PlanningSettings{ai_mode="mcts",candidate_count=5,mcts_iterations=128,mcts_max_depth=4};
        var a=StepPlanner.Plan(player,game,udp.planningFloor,s);var b=StagedRootMctsPlanner.Plan(player,game,udp.planningFloor,s,false);
        Check(a.selected_x==b.selected_x&&a.mcts.nodes.Length==b.mcts.nodes.Length,"disabled legacy parity");
        for(int i=0;i<a.mcts.nodes.Length;i++)for(int j=0;j<a.mcts.nodes[i].actions.Length;j++){var x=a.mcts.nodes[i].actions[j];var y=b.mcts.nodes[i].actions[j];Check(x.visits==y.visits&&x.mean_points==y.mean_points,"legacy edge "+i+"/"+j);}
        var c=StagedRootMctsPlanner.Plan(player,game,udp.planningFloor,s);var d=StagedRootMctsPlanner.Plan(player,game,udp.planningFloor,s);Check(c.selected_x==d.selected_x,"staged repeat selected");
        for(int i=0;i<c.mcts.iterations.Length;i++)Check(string.Join(",",c.mcts.iterations[i].actions)==string.Join(",",d.mcts.iterations[i].actions)&&c.mcts.iterations[i].reward==d.mcts.iterations[i].reward,"staged repeat path "+i);
        Check(c.mcts.completed_iterations==128&&c.mcts.nodes[0].visits==128,"128 no double backup");foreach(var node in c.mcts.nodes)Check(node.actions.Length==5,"five actions node "+node.id);
        Check(c.mcts.source_unchanged&&d.mcts.source_unchanged,"source and RNG unchanged");
    }catch(Exception e){r.error=e.ToString();}using(var f=new StreamWriter(new FileStream(path,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(r));Application.Quit(r.error==null?0:2);}
}
