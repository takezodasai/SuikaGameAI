using System;
using System.Collections;
using System.IO;
using UnityEngine;
public sealed class SuikaLearnedRolloutParity:MonoBehaviour {
    [Serializable] class Config{public string model,cases,output;}
    [Serializable] class Cases{public Case[] cases;}
    [Serializable] class Case{public ValueSnapshot state;public double[] probabilities;}
    [Serializable] class Report{public string error;public int checks;public double max_error;}
    static string path;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaRolloutParity");if(i>=0){path=a[i+1];new GameObject("Rollout policy parity").AddComponent<SuikaLearnedRolloutParity>();}}
    IEnumerator Start(){yield return null;yield return null;var cfg=JsonUtility.FromJson<Config>(File.ReadAllText(path));var report=new Report();
        try{var model=new LearnedRolloutPolicy(cfg.model);var cases=JsonUtility.FromJson<Cases>(File.ReadAllText(cfg.cases));string rng=JsonUtility.ToJson(UnityEngine.Random.state);
            foreach(var c in cases.cases){string before=JsonUtility.ToJson(c.state);var p=model.Probabilities(c.state);double sum=0;
                for(int i=0;i<5;i++){double e=Math.Abs(p[i]-c.probabilities[i]);report.max_error=Math.Max(report.max_error,e);if(e>1e-6)throw new Exception("Policy parity mismatch");sum+=p[i];report.checks++;}
                if(Math.Abs(sum-1)>1e-10||before!=JsonUtility.ToJson(c.state))throw new Exception("Mutation/normalization");report.checks++;
            }
            if(rng!=JsonUtility.ToJson(UnityEngine.Random.state))throw new Exception("Live RNG mutated");report.checks++;
            var state=cases.cases[0].state;state.geometry[1]=state.geometry[0];bool rejected=false;try{model.Probabilities(state);}catch{rejected=true;}if(!rejected)throw new Exception("Invalid geometry accepted");report.checks++;
        }catch(Exception e){report.error=e.ToString();}
        if(File.Exists(cfg.output))throw new Exception("Protect parity output");File.WriteAllText(cfg.output,JsonUtility.ToJson(report,true));Application.Quit(report.error==null?0:2);
    }
}
