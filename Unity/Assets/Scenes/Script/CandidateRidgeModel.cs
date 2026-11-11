using System;
using System.IO;
using UnityEngine;

// Public snapshot + root statistics only. No RNG, physics writes or model fitting.
public sealed class CandidateRidgeModel {
    [Serializable] public class Model {
        public string version;public string[] feature_names;public double alpha,intercept,train_weight,residual_scale,margin_scale,max_abs_z;
        public double[] mean,scale,coef,inverse;public int parameters,train_groups,train_roots;
    }
    [Serializable] public class Prediction {
        public double predicted_delta,uncertainty,max_abs_z,margin,feature_ms,inference_ms;
        public bool ood,choose_B;public string reason,model_sha256;public double[] features;
    }
    public readonly Model model;public readonly string sha256;
    public CandidateRidgeModel(string path){
        byte[] bytes=File.ReadAllBytes(path);model=JsonUtility.FromJson<Model>(System.Text.Encoding.UTF8.GetString(bytes));
        using(var h=System.Security.Cryptography.SHA256.Create())sha256=BitConverter.ToString(h.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        if(model.version!="ridge-public20-v1"||model.parameters!=21||model.feature_names.Length!=20||model.mean.Length!=20||model.scale.Length!=20||model.coef.Length!=20||model.inverse.Length!=400||model.train_weight<=0)throw new InvalidDataException("Invalid ridge model");
        foreach(var x in model.coef)Finite(x);foreach(var x in model.mean)Finite(x);foreach(var x in model.scale){Finite(x);if(x<=0)throw new InvalidDataException("Invalid ridge scale");}
        foreach(var x in model.inverse)Finite(x);Finite(model.intercept);Finite(model.residual_scale);
    }
    static void Finite(double v){if(double.IsNaN(v)||double.IsInfinity(v))throw new InvalidDataException("Nonfinite ridge value");}
    public static double[] Features(ValueSnapshot s,double ax,double bx,MctsPlanner.ActionMetric a,MctsPlanner.ActionMetric b){
        double left=s.geometry[0],width=(double)s.geometry[1]-left,bottom=s.geometry[2],height=(double)s.geometry[3]-bottom;
        if(width<=0||height<=0)throw new InvalidDataException("Invalid ridge geometry");
        var fs=s.fruits;int n=fs.Length;double top=0,y=0,speed=0,area=0,large=0,wm=0,localA=0,localB=0,matchA=1,matchB=1;
        foreach(var f in fs){
            double fx=((double)f.x-left)/width,ar=Math.PI*(double)f.half_width*f.half_height;
            top=Math.Max(top,((double)f.y+f.half_height-bottom)/height);y+=((double)f.y-bottom)/height;
            speed+=Math.Sqrt((double)f.vx*f.vx+(double)f.vy*f.vy);area+=ar;if(f.type>=8)large++;if(f.type==10)wm++;
            double da=(fx-ax)/.2,db=(fx-bx)/.2;localA+=ar*Math.Exp(-.5*da*da);localB+=ar*Math.Exp(-.5*db*db);
            if(f.type==s.current_fruit.type){matchA=Math.Min(matchA,Math.Abs(fx-ax));matchB=Math.Min(matchB,Math.Abs(fx-bx));}
        }
        double count=Math.Max(1,n);
        var v=new[]{n/40.0,top,y/count,speed/count/10,area/(width*height),large/count,wm/2,
            s.current_fruit.type/10.0,s.next_fruit_type/10.0,s.score/3000.0,ax,bx,(b.mean_points-a.mean_points)/55,
            (double)(b.visits-a.visits)/Math.Max(1,a.visits+b.visits),a.sd_points/55,b.sd_points/55,
            (double)a.terminal_returns/Math.Max(1,a.visits),(double)b.terminal_returns/Math.Max(1,b.visits),
            (localB-localA)/(width*height),matchB-matchA};
        foreach(double x in v)Finite(x);return v;
    }
    public Prediction Predict(ValueSnapshot s,double ax,double bx,MctsPlanner.ActionMetric a,MctsPlanner.ActionMetric b){
        var timer=System.Diagnostics.Stopwatch.StartNew();var x=Features(s,ax,bx,a,b);double featureMs=timer.Elapsed.TotalMilliseconds;
        var r=PredictFeatures(x);r.feature_ms=featureMs;r.inference_ms=timer.Elapsed.TotalMilliseconds-featureMs;return r;
    }
    public Prediction PredictFeatures(double[] x){
        var z=new double[20];double pred=model.intercept,h=1/model.train_weight,maxz=0;
        for(int i=0;i<20;i++){z[i]=(x[i]-model.mean[i])/model.scale[i];pred+=z[i]*model.coef[i];maxz=Math.Max(maxz,Math.Abs(z[i]));}
        for(int i=0;i<20;i++)for(int j=0;j<20;j++)h+=z[i]*model.inverse[i*20+j]*z[j];
        double uncertainty=model.residual_scale*Math.Sqrt(Math.Max(0,1+h)),margin=model.margin_scale*uncertainty;
        bool ood=maxz>model.max_abs_z,choose=pred>margin&&!ood;
        return new Prediction{predicted_delta=pred,uncertainty=uncertainty,margin=margin,max_abs_z=maxz,ood=ood,choose_B=choose,
            reason=choose?"ridge_B":ood?"out_of_distribution_keep_A":pred>0?"uncertain_keep_A":"predicted_A",features=x,model_sha256=sha256};
    }
}
