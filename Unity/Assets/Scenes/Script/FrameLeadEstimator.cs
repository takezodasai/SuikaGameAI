using System;
using System.Collections.Generic;

// Predicts a scheduling deadline, never a physics tolerance or MCTS score.
// Full searches only. A missed deadline can never authorize an incomplete result.
public sealed class FrameLeadEstimator
{
    struct Sample {public int ticks,gap;}
    readonly Queue<Sample> recent=new Queue<Sample>();string key;int missedFloor,fullSinceMiss;
    public int Count {get {return recent.Count;}}
    public void SetConfiguration(string value) {if(key==value)return;key=value;recent.Clear();missedFloor=fullSinceMiss=0;}
    public void Observe(int elapsedTicks,int maxUpdateGapTicks)
    {
        if(++fullSinceMiss>=8)missedFloor=0;
        recent.Enqueue(new Sample {ticks=Math.Max(1,elapsedTicks),gap=Math.Max(1,maxUpdateGapTicks)});
        while(recent.Count>8)recent.Dequeue();
    }
    public void ObserveMiss(int reservationTicks) {missedFloor=Math.Max(missedFloor,Math.Min(500,reservationTicks*2));fullSinceMiss=0;}
    public int Suggest(int coldStartTicks)
    {
        if(recent.Count==0)return Math.Max(coldStartTicks,missedFloor);
        int duration=1,gap=1;foreach(var s in recent){duration=Math.Max(duration,s.ticks);gap=Math.Max(gap,s.gap);}
        // 25% scheduling headroom plus two observed Update/Fixed handoff gaps.
        // This is a falsifiable latency forecast, not a guarantee for a new dense board.
        return Math.Min(500,Math.Max(missedFloor,Math.Max(10,(int)Math.Ceiling(duration*1.25)+2*gap)));
    }
    public static int RetryLead(int estimated,int previousLead,bool missedDeadline)
    {return Math.Min(500,missedDeadline?Math.Max(estimated,previousLead*2):estimated);}
}
