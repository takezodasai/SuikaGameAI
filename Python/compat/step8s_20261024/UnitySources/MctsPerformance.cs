using System;
using System.Collections.Generic;
using System.Diagnostics;

// Opt-in, main-thread measurement. Inclusive categories overlap; exclusive ones do not.
public sealed class MctsPerformance
{
    [Serializable] public class Metric { public string name; public int calls; public double inclusive_ms,exclusive_ms,max_ms,min_ms; }
    public static MctsPerformance Current;
    // Internal A/B diagnostic switch, never a gameplay/physics setting.
    internal static bool Optimized=true;
    internal static bool VerifyStates;
    internal static bool SuppressProfiler;

    public readonly Dictionary<string,Metric> metrics=new Dictionary<string,Metric>();
    readonly Stack<Frame> stack=new Stack<Frame>();
    sealed class Frame {public string name;public long start,children;}
    public struct Scope : IDisposable
    {
        readonly MctsPerformance owner;
        internal Scope(MctsPerformance p,string name){owner=p;if(p!=null)p.stack.Push(new Frame {name=name,start=Stopwatch.GetTimestamp()});}
        public void Dispose(){if(owner==null)return;var f=owner.stack.Pop();long elapsed=Stopwatch.GetTimestamp()-f.start;if(owner.stack.Count>0)owner.stack.Peek().children+=elapsed;Metric m;if(!owner.metrics.TryGetValue(f.name,out m)){m=new Metric {name=f.name};owner.metrics.Add(f.name,m);}if(m.calls==0)m.min_ms=elapsed*1000.0/Stopwatch.Frequency;else m.min_ms=Math.Min(m.min_ms,elapsed*1000.0/Stopwatch.Frequency);m.max_ms=Math.Max(m.max_ms,elapsed*1000.0/Stopwatch.Frequency);m.calls++;m.inclusive_ms+=elapsed*1000.0/Stopwatch.Frequency;m.exclusive_ms+=(elapsed-f.children)*1000.0/Stopwatch.Frequency;}
    }
    public static Scope Measure(string name){return new Scope(Current,name);}
    public Metric[] Results(){var result=new List<Metric>(metrics.Values);result.Sort((a,b)=>string.CompareOrdinal(a.name,b.name));return result.ToArray();}
}
