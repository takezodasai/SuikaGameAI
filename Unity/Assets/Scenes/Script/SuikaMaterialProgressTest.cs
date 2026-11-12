using System;
using System.Collections;
using System.IO;
using UnityEngine;
public sealed class SuikaMaterialProgressTest:MonoBehaviour {
    [Serializable] class Report{public string error;public int checks;}
    static string path;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaMaterialTest");if(i>=0){path=a[i+1];new GameObject("Material observation tests").AddComponent<SuikaMaterialProgressTest>();}}
    IEnumerator Start(){yield return null;var report=new Report();
        Action<bool> check=v=>{if(!v)throw new Exception("Material observer check "+report.checks);report.checks++;};
        try{
            string rng=JsonUtility.ToJson(UnityEngine.Random.state);var o=new SuikaMaterialProgress();check(o.Read()==null);
            var initial=new int[11];initial[10]=1;initial[8]=2;initial[9]=1;o.Begin(initial,100,0,0);var a=o.Read();
            check(a.known&&a.events.Length==4);foreach(var e in a.events)check(e.initial);
            initial[10]=99;check(o.Read().watermelons==1); // no retained mutable input
            o.Tick(7);o.Merge(8,9,136,1,.14);a=o.Read();check(a.melons==2&&a.pineapples==0);
            var two=Array.Find(a.events,e=>e.kind=="watermelon_two_melons");check(two!=null&&!two.initial&&two.tick==7);
            o.Merge(9,10,181,1,.14);a=o.Read();check(a.watermelons==2&&a.melons==0);check(Array.Exists(a.events,e=>e.kind=="two_watermelons"));
            // Same physics timestamp, transient coexistence survives the next merge.
            o.Merge(10,-1,236,1,.14);a=o.Read();check(a.known&&a.watermelons==0&&a.double_count==1);
            check(Array.Exists(a.events,e=>e.kind=="two_watermelons")&&Array.Exists(a.events,e=>e.kind=="double_watermelon"));
            int before=a.events.Length;o.Drop(10,236,2,.16);check(o.Read().events.Length==before);
            a.counts[10]=77;check(o.Read().watermelons==1); // snapshot cannot mutate recorder
            o.Merge(9,10,281,2,.16);check(!o.Read().known); // invalid missing fixture inventory is unknown
            o.Reset();check(o.Read()==null);o.Begin(new int[11],0,0,0);o.Drop(8,0,1,0);check(o.Read().pineapples==1);
            check(JsonUtility.ToJson(UnityEngine.Random.state)==rng);
            var enabled=new SuikaEpisodeEvents();var disabled=new SuikaEpisodeEvents();enabled.Enabled=disabled.Enabled=true;
            enabled.BeginMaterialObservation(new int[11],0,0);enabled.Drop(0,0,0);disabled.Drop(0,0,0);
            check(enabled.Read().drop_count==disabled.Read().drop_count&&disabled.Read().materials==null);
        }catch(Exception e){report.error=e.ToString();}
        using(var f=new StreamWriter(new FileStream(path,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(report,true));Application.Quit(report.error==null?0:2);
    }
}
