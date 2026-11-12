using System;
using System.Collections.Generic;
using UnityEngine;
// Observation only: no object, RNG, physics or score mutations. Actual-game callers only.
public sealed class SuikaEpisodeEvents {
    [Serializable] public class Entry {
        public int event_id,score,drop_count,watermelons_created,watermelons_present,double_watermelons;
        public string kind; public double fixed_time;
        public Location location;
    }
    [Serializable] public class Location {
        public string version="step8ae-location-v1";
        public bool position_known,collider_known;public float x,y,half_width,half_height;
    }
    public static Location Observe(Vector2 position,FruitEvolution fruit=null) {
        var result=new Location {position_known=true,x=position.x,y=position.y};
        var c=fruit==null?null:FruitColliderShape.Get(fruit.gameObject);
        if(c!=null&&c.enabled){var b=c.bounds;if(b.extents.x>0&&b.extents.y>0){result.collider_known=true;result.x=b.center.x;result.y=b.center.y;result.half_width=b.extents.x;result.half_height=b.extents.y;}}
        return result;
    }
    [Serializable] public class Snapshot {
        public string source="actual_game",version="step8u-events-v1";
        public bool known;public int drop_count,watermelons_created,watermelons_present,double_watermelons;
        public Entry[] events;
        public SuikaLearningMilestones.Snapshot learning;
        public SuikaMaterialProgress.Snapshot materials;
    }
    public bool Enabled {get;set;}
    int drops,created,present,doubles; readonly List<Entry> events=new List<Entry>();
    readonly SuikaLearningMilestones learning=new SuikaLearningMilestones();
    readonly SuikaMaterialProgress materials=new SuikaMaterialProgress();
    public void BeginMaterialObservation(int[] initial,int score,double time){materials.Begin(initial,score,drops,time);}
    public void MaterialTick(int tick){materials.Tick(tick);}
    public void Reset(){drops=created=present=doubles=0;events.Clear();learning.Reset();materials.Reset();}
    void Emit(string kind,int score,double time,Location location=null){events.Add(new Entry {event_id=events.Count+1,kind=kind,location=location,score=score,drop_count=drops,fixed_time=time,watermelons_created=created,watermelons_present=present,double_watermelons=doubles});}
    void Created(int score,double time,Location location){int before=present;created++;present++;
        Emit("watermelon_created",score,time,location);
        if(created==1)Emit("first_watermelon",score,time,location);
        if(created==2)Emit("second_watermelon",score,time,location);
        if(before<2&&present>=2)Emit("two_watermelons_present",score,time,location);
    }
    public void Drop(int type,int score,double time,Location location=null){if(!Enabled)return;drops++;if(type==10)Created(score,time,location);learning.Drop(type,score,drops,time);materials.Drop(type,score,drops,time);}
    public void Merge(int from,int to,int score,double time,Location location=null){if(!Enabled)return;
        if(to==10)Created(score,time,location);
        if(from==10&&to==-1){present-=2;doubles++;Emit("watermelon_pair_disappeared",score,time,location);Emit("double_watermelon",score,time,location);}
        learning.Merge(from,to,score,drops,time);
        materials.Merge(from,to,score,drops,time);
    }
    public Snapshot Read(){return new Snapshot {known=Enabled,drop_count=drops,watermelons_created=created,watermelons_present=present,double_watermelons=doubles,events=Enabled?events.ToArray():new Entry[0],learning=learning.Read(Enabled),materials=Enabled?materials.Read():null};}
}
