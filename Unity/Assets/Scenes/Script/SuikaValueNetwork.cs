using System;
using System.IO;
using UnityEngine;

// Same numerical schema as Python value_data.encode; no RNG, physics writes or dependencies.
[Serializable] public class ValueSnapshot
{
    public UDPCommunicatorUnity.BoardFruit[] fruits;
    public UDPCommunicatorUnity.ControlledFruit current_fruit;
    public int next_fruit_type=-1,score;
    public bool game_over;
    public float drop_cooldown_remaining,ai_move_speed,fixed_delta_time;
    public float[] geometry;
}
public sealed class SuikaValueNetwork
{
    [Serializable] public class Layer {public int inputs,outputs;public float[] weights,bias;}
    [Serializable] public class Model
    {
        public string version,input_version,checkpoint_sha256;
        public int epoch,parameters;
        public string[] fruit_names,global_names;
        public Layer[] layers;
    }
    public readonly Model model;
    public readonly string file_sha256;
    static string cachedPath;static SuikaValueNetwork cached;
    public static SuikaValueNetwork Load(string path)
    {
        path=Path.GetFullPath(string.IsNullOrEmpty(path)?Path.Combine(Application.streamingAssetsPath,"suika_value_epoch3.json"):path);
        if(cached==null || path!=cachedPath) {cached=new SuikaValueNetwork(File.ReadAllText(path));cachedPath=path;}
        return cached;
    }
    public SuikaValueNetwork(string json)
    {
        model=JsonUtility.FromJson<Model>(json);
        using(var sha=System.Security.Cryptography.SHA256.Create())
            file_sha256=BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(json))).Replace("-","").ToLowerInvariant();
        if(model.version!="value-unity-v1" || model.input_version!="value-v1-missing-aware" || model.epoch!=3 || model.parameters!=35713 || model.layers==null || model.layers.Length!=5 || model.fruit_names.Length!=30 || model.global_names.Length!=37)
            throw new InvalidDataException("Unsupported value model specification");
        int[] ins={30,64,165,128,64},outs={64,64,128,64,1};
        for(int i=0;i<5;i++)
        {
            var l=model.layers[i];
            if(l.inputs!=ins[i] || l.outputs!=outs[i] || l.weights.Length!=ins[i]*outs[i] || l.bias.Length!=outs[i]) throw new InvalidDataException("Invalid dense tensor shape");
            foreach(float v in l.weights) Finite(v);foreach(float v in l.bias) Finite(v);
        }
    }
    static void Finite(float x) {if(float.IsNaN(x)||float.IsInfinity(x)) throw new InvalidDataException("Nonfinite value input/model");}
    static float[] Dense(float[] x,Layer l,bool relu)
    {
        var y=new float[l.outputs];
        for(int o=0;o<y.Length;o++)
        {
            // FP32 accumulation like torch Linear, without architecture-dependent FMA.
            float sum=l.bias[o];int k=o*l.inputs;
            for(int j=0;j<x.Length;j++) sum+=x[j]*l.weights[k+j];
            y[o]=relu?Math.Max(0,sum):sum;
        }
        return y;
    }
    public static float[][] Encode(ValueSnapshot s,out float[] g)
    {
        bool geo=s.geometry!=null && s.geometry.Length==4;
        if(geo) foreach(float x in s.geometry) geo &= !float.IsNaN(x)&&!float.IsInfinity(x);
        geo=geo && s.geometry[1]>s.geometry[0] && s.geometry[3]>s.geometry[2];
        double left=geo?s.geometry[0]:0,width=geo?(double)s.geometry[1]-s.geometry[0]:10;
        double floor=geo?s.geometry[2]:0,height=geo?(double)s.geometry[3]-s.geometry[2]:10;
        var rows=new float[s.fruits.Length][];
        for(int i=0;i<rows.Length;i++)
        {
            var f=s.fruits[i];if(f.type<0||f.type>10) throw new InvalidDataException("Invalid value fruit type");
            var v=new float[30];v[f.type]=1;
            v[11]=(float)((f.x-left)/width);v[12]=(float)((f.y-floor)/height);
            v[13]=f.vx/10;v[14]=f.vy/10;
            double angle=f.angle*Math.PI/180;v[15]=(float)Math.Sin(angle);v[16]=(float)Math.Cos(angle);v[17]=f.angular_velocity/360;
            v[18]=f.has_collided?1:0;v[19]=1;
            if(f.collider_measurement_known && f.half_width>0 && f.half_height>0)
            {v[20]=(float)(f.half_width/width);v[21]=(float)(f.half_height/height);v[22]=1;}
            if(f.collider_measurement_known) {v[23]=(float)(f.collider_offset_x/width);v[24]=(float)(f.collider_offset_y/height);v[25]=1;}
            if(f.observation_metadata_known) {v[26]=f.touching?1:0;v[27]=1;v[28]=f.sleeping?1:0;v[29]=1;}
            foreach(float n in v) Finite(n);rows[i]=v;
        }
        g=new float[37];var held=s.current_fruit;bool present=held!=null && held.present;
        if(present)
        {
            if(held.type<0 || held.type>10) throw new InvalidDataException("Invalid held type");
            g[held.type]=1;g[22]=1;g[24]=(float)((held.x-left)/width);
            if(held.y_known) {g[25]=(float)((held.y-floor)/height);g[26]=1;}
        }
        if(s.next_fruit_type>=0 && s.next_fruit_type<11) {g[11+s.next_fruit_type]=1;g[23]=1;}
        g[27]=s.score/1000f;g[28]=s.drop_cooldown_remaining;g[29]=1;g[30]=s.ai_move_speed/10;g[31]=1;
        g[32]=s.fixed_delta_time/.02f;g[33]=1;g[34]=rows.Length/64f;g[35]=s.game_over?1:0;g[36]=geo?1:0;
        foreach(float n in g) Finite(n);return rows;
    }
    public float Predict(ValueSnapshot s)
    {float[] g;return PredictEncoded(Encode(s,out g),g);}
    public float PredictEncoded(float[][] rows,float[] g)
    {
        var joined=new float[165];var maximum=new float[64];
        foreach(var row in rows)
        {
            var z=Dense(Dense(row,model.layers[0],true),model.layers[1],true);
            for(int k=0;k<64;k++) {joined[k]+=z[k];maximum[k]=Math.Max(maximum[k],z[k]);}
        }
        for(int k=0;k<64;k++) {if(rows.Length>0) joined[k]/=rows.Length;joined[k+64]=maximum[k];}
        Array.Copy(g,0,joined,128,37);
        float x=Dense(Dense(Dense(joined,model.layers[2],true),model.layers[3],true),model.layers[4],false)[0];
        float value=(x>20?x:(float)Math.Log(1+Math.Exp(x)))*1000*(1-g[35]);Finite(value);return value;
    }
}
