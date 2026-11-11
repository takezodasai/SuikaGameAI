using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
public sealed class SuikaAlternativeCandidateTest:MonoBehaviour {
    [Serializable] class Report{public string error;public List<string> passed=new List<string>();}
    static string output;Report report=new Report();
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaAlternativeCandidateTest");if(i>=0){output=a[i+1];new GameObject("Alternative candidate tests").AddComponent<SuikaAlternativeCandidateTest>();}}
    void Check(bool v,string name){if(!v)throw new Exception(name);report.passed.Add(name);}
    IEnumerator Start(){yield return null;yield return null;
        try{
            var xs=new MctsPlanner.ActionMetric[5];for(int i=0;i<5;i++)xs[i]=new MctsPlanner.ActionMetric{index=i,x=i/4f,visits=10,mean_points=i,drop_success=true};
            var rng=UnityEngine.Random.state;var c=AlternativeCandidateSelection.Select(4,1,xs,true);
            Check(c.actual_index==3&&c.recommended_index==4,"exclude recommended, largest other mean");
            Check(rng.Equals(UnityEngine.Random.state),"no RNG consumption");
            Check(xs[3].visits==10&&xs[4].mean_points==4,"no root mutation");
            c=AlternativeCandidateSelection.Select(4,1,xs,false);Check(c.actual_index==4&&c.alternative_index==3,"legacy preserved and B logged");
            xs[3].immediate_go=true;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(c.actual_index==2,"immediate GO excluded");
            xs[2].drop_success=false;xs[1].visits=0;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(c.actual_index==0,"failed/unvisited excluded");
            xs[0].mean_points=4;xs[1].visits=11;xs[1].mean_points=4;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(c.actual_index==1,"mean tie then visits");
            xs[0].visits=11;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(c.actual_index==0,"visit tie then index");
            xs[0].x=1;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(!c.has_alternative&&c.actual_index==4&&c.reason=="same_coordinate_fallback_legacy","same coordinate fallback");
            for(int i=0;i<4;i++)xs[i].immediate_go=true;c=AlternativeCandidateSelection.Select(4,1,xs,true);Check(!c.has_alternative&&c.actual_index==4,"no alternative preserves legacy/all-GO fallback");
        }catch(Exception e){report.error=e.ToString();}
        File.WriteAllText(output,JsonUtility.ToJson(report,true));Application.Quit(report.error==null?0:2);
    }
}
