using System;
using System.Collections.Generic;
// Observation only: no object, RNG, physics or score mutations. Actual-game callers only.
public sealed class SuikaEpisodeEvents {
    [Serializable] public class Entry {
        public int event_id,score,drop_count,watermelons_created,watermelons_present,double_watermelons;
        public string kind; public double fixed_time;
    }
    [Serializable] public class Snapshot {
        public string source="actual_game",version="step8u-events-v1";
        public bool known;public int drop_count,watermelons_created,watermelons_present,double_watermelons;
        public Entry[] events;
    }
    public bool Enabled {get;set;}
    int drops,created,present,doubles; readonly List<Entry> events=new List<Entry>();
    public void Reset(){drops=created=present=doubles=0;events.Clear();}
    void Emit(string kind,int score,double time){events.Add(new Entry {event_id=events.Count+1,kind=kind,score=score,drop_count=drops,fixed_time=time,watermelons_created=created,watermelons_present=present,double_watermelons=doubles});}
    void Created(int score,double time){int before=present;created++;present++;
        Emit("watermelon_created",score,time);
        if(created==1)Emit("first_watermelon",score,time);
        if(created==2)Emit("second_watermelon",score,time);
        if(before<2&&present>=2)Emit("two_watermelons_present",score,time);
    }
    public void Drop(int type,int score,double time){if(!Enabled)return;drops++;if(type==10)Created(score,time);}
    public void Merge(int from,int to,int score,double time){if(!Enabled)return;
        if(to==10)Created(score,time);
        if(from==10&&to==-1){present-=2;doubles++;Emit("watermelon_pair_disappeared",score,time);Emit("double_watermelon",score,time);}
    }
    public Snapshot Read(){return new Snapshot {known=Enabled,drop_count=drops,watermelons_created=created,watermelons_present=present,double_watermelons=doubles,events=Enabled?events.ToArray():new Entry[0]};}
}
