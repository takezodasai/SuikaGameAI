using System;
using System.IO;
using System.Collections.Generic;
using UnityEngine;

// Opt-in lightweight imitation at rollout decision boundaries only. No live RNG.
public sealed class LearnedRolloutPolicy {
    [Serializable] public class Model {public string version;public double[] weights;public float[] grid;}
    [Serializable] public class Audit {public int rollout_calls,learned_calls,random_calls,fallback_calls;public double inference_ms;public int[] learned_by_depth,actions=new int[5];public string model_sha256;public double mixture;}
    public readonly Model model;
    public readonly string sha;
    public static LearnedRolloutPolicy Active;
    public static double Mixture;
    public static Audit Last;
    static System.Random mixer;
    public LearnedRolloutPolicy(string path){
        var bytes=File.ReadAllBytes(path);model=JsonUtility.FromJson<Model>(System.Text.Encoding.UTF8.GetString(bytes));
        if(model.version!="candidate-linear213-v1"||model.weights==null||model.weights.Length!=213||model.grid==null||model.grid.Length!=5)throw new Exception("Invalid rollout model");
        for(int i=0;i<5;i++)if(model.grid[i]!=i*.25f)throw new Exception("Model grid mismatch");
        foreach(var v in model.weights)if(double.IsNaN(v)||double.IsInfinity(v))throw new Exception("Invalid rollout weight");
        using(var h=System.Security.Cryptography.SHA256.Create())sha=BitConverter.ToString(h.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
    }
    public static void Begin(int seed,int depth){
        if(Mixture<0||Mixture>1||double.IsNaN(Mixture))throw new Exception("Invalid policy mixture");
        Last=new Audit{mixture=Mixture,model_sha256=Active==null?"":Active.sha,learned_by_depth=new int[depth]};mixer=new System.Random(unchecked(seed^0x53ac19));
    }
    public static double[][] Features(ValueSnapshot s){
        if(s==null||s.game_over||s.geometry==null||s.geometry.Length!=4||s.current_fruit==null||!s.current_fruit.present||s.current_fruit.type<0||s.current_fruit.type>10||s.next_fruit_type< -1||s.next_fruit_type>10)throw new Exception("Invalid public rollout state");
        double left=s.geometry[0],width=s.geometry[1]-left,bottom=s.geometry[2],height=s.geometry[3]-bottom;
        if(width<=0||height<=0)throw new Exception("Invalid geometry");
        int n=s.fruits.Length;var b=new double[40];b[0]=1;b[1]=n/40.0;b[2]=n==0?0:double.NegativeInfinity;
        foreach(var f in s.fruits){double y=(f.y-bottom)/height;b[2]=Math.Max(b[2],y);b[3]+=y/Math.Max(1,n);b[4]+=Math.Sqrt((double)f.vx*f.vx+(double)f.vy*f.vy)/Math.Max(1,n)/10;if(f.type<0||f.type>10)throw new Exception("Invalid board type");b[6+f.type]+=.1;}
        b[5]=s.score/3000.0;b[17+s.current_fruit.type]=1;b[29+s.next_fruit_type]=1;
        var xs=new double[5][];
        for(int i=0;i<5;i++){
            double x=i*.25;var fts=new double[213];Array.Copy(b,0,fts,i*40,40);double nearest=1,top=0;
            foreach(var f in s.fruits){double d=(f.x-left)/width-x,k=Math.Exp(-.5*(d/.2)*(d/.2));fts[200+f.type]+=k/10;if(f.type==s.current_fruit.type)nearest=Math.Min(nearest,Math.Abs(d));top=Math.Max(top,(f.y-bottom)/height*k);}
            fts[211]=nearest;fts[212]=top;
            for(int j=0;j<213;j++){if(double.IsNaN(fts[j])||double.IsInfinity(fts[j]))throw new Exception("Invalid feature");fts[j]=Math.Max(-10,Math.Min(10,fts[j]));}xs[i]=fts;
        }return xs;
    }
    public double[] Probabilities(ValueSnapshot s){var f=Features(s);var p=new double[5];double max=double.NegativeInfinity,sum=0;
        for(int i=0;i<5;i++){for(int j=0;j<213;j++)p[i]+=f[i][j]*model.weights[j];max=Math.Max(max,p[i]);}
        for(int i=0;i<5;i++){p[i]=Math.Exp(p[i]-max);sum+=p[i];}for(int i=0;i<5;i++)p[i]/=sum;return p;
    }
    public static int Choose(SuikaPhysicsSimulator.PathSession path,System.Random rng,int count,int depth){
        Last.rollout_calls++;
        if(Active==null||Mixture<=0||mixer.NextDouble()>=Mixture){Last.random_calls++;return rng.Next(count);}
        var watch=System.Diagnostics.Stopwatch.StartNew();
        try{
            if(count!=5)throw new Exception("Grid5 only");
            var p=Active.Probabilities(path.Snapshot());double u=rng.NextDouble(),sum=0;int action=4;
            for(int i=0;i<5;i++){if(double.IsNaN(p[i])||double.IsInfinity(p[i])||p[i]<0)throw new Exception("Invalid policy probability");sum+=p[i];if(u<sum){action=i;break;}}
            Last.learned_calls++;Last.learned_by_depth[depth]++;Last.actions[action]++;return action;
        }catch(InvalidOperationException){Last.fallback_calls++;return rng.Next(count);}
        catch(Exception){Last.fallback_calls++;return rng.Next(count);}
        finally{Last.inference_ms+=watch.Elapsed.TotalMilliseconds;}
    }
}
