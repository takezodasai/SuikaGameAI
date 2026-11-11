using System;
using System.Collections.Generic;
// Observation only. Called atomically after an actual drop/merge, never by prediction.
public sealed class SuikaLearningMilestones {
    [Serializable] public class Entry {public string kind;public int score,drop_count,melons_present,watermelons_present;public double fixed_time;}
    [Serializable] public class Snapshot {public string version="learning-milestones-v1";public bool known;public int melons_present,watermelons_present;public Entry[] events;}
    int melons,watermelons;bool consistent=true;readonly HashSet<string> achieved=new HashSet<string>();readonly List<Entry> events=new List<Entry>();
    public void Reset(){melons=watermelons=0;consistent=true;achieved.Clear();events.Clear();}
    void Emit(string kind,int score,int drop,double time){if(consistent&&achieved.Add(kind))events.Add(new Entry {kind=kind,score=score,drop_count=drop,fixed_time=time,melons_present=melons,watermelons_present=watermelons});}
    void Check(int score,int drop,double time,bool isDouble){
        if(melons<0||watermelons<0)consistent=false; // External fixture spawns cannot be reconstructed; do not invent counts.
        if(watermelons>=1)Emit("watermelon_one",score,drop,time);
        if(watermelons>=1&&melons>=1)Emit("watermelon_melon_one",score,drop,time);
        if(watermelons>=1&&melons>=2)Emit("watermelon_melon_two",score,drop,time);
        if(watermelons>=2)Emit("watermelon_two",score,drop,time);
        if(isDouble)Emit("double_watermelon",score,drop,time);
    }
    public void Drop(int type,int score,int drop,double time){if(type==9)melons++;if(type==10)watermelons++;Check(score,drop,time,false);}
    public void Merge(int from,int to,int score,int drop,double time){
        if(from==9)melons-=2;if(from==10)watermelons-=2;
        if(to==9)melons++;if(to==10)watermelons++;
        Check(score,drop,time,from==10&&to==-1);
    }
    public Snapshot Read(bool enabled){return new Snapshot {known=enabled&&consistent,melons_present=melons,watermelons_present=watermelons,events=enabled?events.ToArray():new Entry[0]};}
}
