using System;
using System.Collections.Generic;

// Opt-in actual-game observer. Pure counters only: no physics, objects, RNG or rewards.
// Counts are changed atomically after a real merge, so transient coexistence is retained.
public sealed class SuikaMaterialProgress {
    public const string Version="watermelon-materials-v1";
    [Serializable] public class Entry {
        public int event_id,tick,score,drop_count,pineapples,melons,watermelons;
        public string kind;public bool initial;public double fixed_time;
    }
    [Serializable] public class Snapshot {
        public string version=Version,source="actual_game",unknown_reason;
        public bool known;public int tick,pineapples,melons,watermelons,double_count;
        public int[] counts;public Entry[] events;
    }
    readonly int[] counts=new int[11];readonly List<Entry> events=new List<Entry>();
    readonly HashSet<string> reached=new HashSet<string>();bool active,consistent;int tick,doubles;
    string unknown;
    public void Reset(){active=false;consistent=false;unknown=null;tick=doubles=0;Array.Clear(counts,0,11);events.Clear();reached.Clear();}
    public void Begin(int[] initial,int score,int drop,double time){
        Reset();active=true;consistent=initial!=null&&initial.Length==11;
        if(consistent)for(int i=0;i<11;i++){counts[i]=initial[i];if(counts[i]<0)consistent=false;}
        if(!consistent){unknown="invalid initial inventory";return;}
        Check(score,drop,time,true,false);
    }
    public void Tick(int value){if(active)tick=value;}
    void Emit(string kind,int score,int drop,double time,bool initial){
        if(reached.Add(kind))events.Add(new Entry{event_id=events.Count+1,kind=kind,tick=tick,score=score,drop_count=drop,
            fixed_time=time,initial=initial,pineapples=counts[8],melons=counts[9],watermelons=counts[10]});
    }
    void Check(int score,int drop,double time,bool initial,bool isDouble){
        if(!active||!consistent)return;
        for(int i=0;i<11;i++)if(counts[i]<0){consistent=false;unknown="inventory underflow: callback or initial-state mismatch";return;}
        if(counts[10]>=1){
            Emit("watermelon_one",score,drop,time,initial);
            if(counts[8]>=1)Emit("watermelon_pineapple",score,drop,time,initial);
            if(counts[9]>=1)Emit("watermelon_melon",score,drop,time,initial);
            if(counts[9]>=1&&counts[8]>=1)Emit("watermelon_melon_pineapple",score,drop,time,initial);
            if(counts[9]>=2)Emit("watermelon_two_melons",score,drop,time,initial);
        }
        if(counts[10]>=2)Emit("two_watermelons",score,drop,time,initial);
        if(isDouble)Emit("double_watermelon",score,drop,time,false);
    }
    public void Drop(int type,int score,int drop,double time){
        if(!active)return;
        if(type<0||type>10){consistent=false;unknown="invalid dropped type";return;}
        counts[type]++;Check(score,drop,time,false,false);
    }
    public void Merge(int from,int to,int score,int drop,double time){
        if(!active)return;
        if(from<0||from>10||to!=(from==10?-1:from+1)){consistent=false;unknown="invalid merge transition";return;}
        counts[from]-=2;if(to>=0)counts[to]++;
        bool isDouble=from==10&&to==-1;if(isDouble)doubles++;
        Check(score,drop,time,false,isDouble);
    }
    public Snapshot Read(){
        if(!active)return null;
        return new Snapshot{known=consistent,unknown_reason=unknown,tick=tick,counts=(int[])counts.Clone(),
            pineapples=counts[8],melons=counts[9],watermelons=counts[10],double_count=doubles,events=events.ToArray()};
    }
}
