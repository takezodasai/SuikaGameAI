using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
public sealed class SuikaCandidateRidgeParity:MonoBehaviour {
    [Serializable] class Config{public string model,cases,output;}
    [Serializable] class Cases{public Case[] cases;}
    [Serializable] class Case{public ValueSnapshot state;public double[] coordinates,features;public MctsPlanner.ActionMetric[] stats;public CandidateRidgeModel.Prediction prediction;}
    [Serializable] class Report{public string error;public int checks;public double max_feature_error,max_prediction_error,max_uncertainty_error;}
    static string configPath;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaRidgeParity");if(i>=0){configPath=a[i+1];new GameObject("Ridge parity tests").AddComponent<SuikaCandidateRidgeParity>();}}
    IEnumerator Start(){yield return null;yield return null;var report=new Report();var cfg=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        try{
            var model=new CandidateRidgeModel(cfg.model);var cases=JsonUtility.FromJson<Cases>(File.ReadAllText(cfg.cases));var rng=UnityEngine.Random.state;
            foreach(var c in cases.cases){
                string before=JsonUtility.ToJson(c.state);var pred=model.Predict(c.state,c.coordinates[0],c.coordinates[1],c.stats[0],c.stats[1]);
                for(int i=0;i<20;i++){double err=Math.Abs(pred.features[i]-c.features[i]);report.max_feature_error=Math.Max(report.max_feature_error,err);if(err>1e-6)throw new Exception("Feature parity "+i+" "+err);report.checks++;}
                double pe=Math.Abs(pred.predicted_delta-c.prediction.predicted_delta),ue=Math.Abs(pred.uncertainty-c.prediction.uncertainty);
                report.max_prediction_error=Math.Max(report.max_prediction_error,pe);report.max_uncertainty_error=Math.Max(report.max_uncertainty_error,ue);
                if(pe>1e-3||ue>1e-3||pred.choose_B!=c.prediction.choose_B||pred.ood!=c.prediction.ood)throw new Exception("Ridge prediction parity");report.checks++;
                if(before!=JsonUtility.ToJson(c.state))throw new Exception("Model mutated source");report.checks++;
            }
            if(!rng.Equals(UnityEngine.Random.state))throw new Exception("Ridge consumed RNG");report.checks++;
            var extreme=(double[])model.model.mean.Clone();extreme[0]+=100*model.model.scale[0];var guard=model.PredictFeatures(extreme);
            if(!guard.ood||guard.choose_B)throw new Exception("OOD did not keep A");report.checks++;
        }catch(Exception e){report.error=e.ToString();}
        if(File.Exists(cfg.output))throw new IOException("Protect existing parity result");File.WriteAllText(cfg.output,JsonUtility.ToJson(report,true));Application.Quit(report.error==null?0:2);
    }
}
