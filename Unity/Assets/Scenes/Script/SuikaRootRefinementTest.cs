using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
public sealed class SuikaRootRefinementTest:MonoBehaviour {
    [Serializable] class Report{public string error;public List<string> passed=new List<string>();}
    static string output;Report report=new Report();
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaRootRefinementTest");if(i>=0){output=a[i+1];new GameObject("Root refinement tests").AddComponent<SuikaRootRefinementTest>();}}
    void Check(bool v,string name){if(!v)throw new Exception(name);report.passed.Add(name);}
    MctsPlanner.Node Root(){var n=new MctsPlanner.Node(5,0,0){visits=32,positions=MctsAdaptiveControl.InitialPositions(5)};for(int i=0;i<5;i++){n.actions[i].immediate=new StepPlanner.Candidate{drop_success=true};for(int k=0;k<6;k++)n.actions[i].Add(i*10,false);}return n;}
    void Equal(StepPlanner.Decision a,StepPlanner.Decision b,string label){
        Check(a.selected_x==b.selected_x,label+" selected");Check(a.mcts.completed_iterations==b.mcts.completed_iterations,label+" iterations");
        Check(a.mcts.nodes.Length==b.mcts.nodes.Length,label+" nodes");
        for(int i=0;i<a.mcts.nodes.Length;i++){var x=a.mcts.nodes[i];var y=b.mcts.nodes[i];Check(x.visits==y.visits&&x.actions.Length==y.actions.Length,label+" node "+i);for(int j=0;j<x.actions.Length;j++)Check(x.actions[j].visits==y.actions[j].visits&&x.actions[j].mean_points==y.actions[j].mean_points,label+" edge "+i+"/"+j);}
        for(int i=0;i<a.mcts.iterations.Length;i++)Check(string.Join(",",a.mcts.iterations[i].actions)==string.Join(",",b.mcts.iterations[i].actions)&&string.Join(",",a.mcts.iterations[i].chance_slots)==string.Join(",",b.mcts.iterations[i].chance_slots)&&a.mcts.iterations[i].reward==b.mcts.iterations[i].reward&&a.mcts.iterations[i].ticks==b.mcts.iterations[i].ticks,label+" path "+i);
    }
    IEnumerator Start(){yield return null;yield return null;
        try{
            var s=new PlanningSettings{ai_mode="mcts",mcts_iterations=128,mcts_max_depth=4,candidate_count=5};var n=Root();var old=n.actions[4];var additions=RootCandidateRefinement.Add(n,s,32);
            Check(additions.Count==2&&n.actions.Length==7,"two additions");Check(ReferenceEquals(old,n.actions[4])&&old.visits==6&&n.visits==32,"old statistics retained");
            for(int i=0;i<5;i++)Check(n.positions.x[i]==i/4f,"anchor "+i);
            Check(n.actions[5].visits==0&&n.actions[6].visits==0,"no invented visits");Check(RootCandidateRefinement.Add(n,s,32).Count==0,"no repeated insertion");
            var terminal=Root();foreach(var e in terminal.actions)e.immediate.predicted_game_over=true;Check(RootCandidateRefinement.Add(terminal,s,32).Count==0,"all GO no insertion");
            var nonroot=Root();nonroot.depth=1;Check(RootCandidateRefinement.Add(nonroot,s,32).Count==0,"nonroot untouched");
            var player=FindObjectOfType<PlayerController>();var game=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
            var a=StepPlanner.Plan(player,game,udp.planningFloor,s);var b=RootRefinedMctsPlanner.Plan(player,game,udp.planningFloor,s,false);Equal(a,b,"disabled fork parity128");
            var c=RootRefinedMctsPlanner.Plan(player,game,udp.planningFloor,s);var d=RootRefinedMctsPlanner.Plan(player,game,udp.planningFloor,s);Equal(c,d,"refined repeat128");
            Check(c.mcts.completed_iterations==128&&c.mcts.nodes[0].visits==128,"128 budget, no double backup");
            foreach(var node in c.mcts.nodes)if(node.depth>0)Check(node.actions.Length==5,"future five "+node.id);
            foreach(var addition in c.mcts.candidate_additions)Check(addition.final_visits>0,"new candidate explored "+addition.index);
            Check(c.mcts.source_unchanged&&d.mcts.source_unchanged,"live RNG and board retained");
        }catch(Exception e){report.error=e.ToString();}
        using(var f=new StreamWriter(new FileStream(output,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(report));Application.Quit(report.error==null?0:2);
    }
}
