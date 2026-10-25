using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// Owned diagnostic Player only. FixedUpdate input mirrors UDP movement/drop, post-physics recorder observes.
public sealed class SuikaTimingProbe : MonoBehaviour {
    [Serializable] class Config {public string fixture,output;}
    [Serializable] public class Sample {public int elapsed_ticks,score,merges;public bool game_over;public PredictionDiagnostics.FruitState[] fruits;}
    [Serializable] public class Event {public int elapsed_tick,score,merges;}
    [Serializable] public class Alias {public string from,to;}
    [Serializable] public class Row {public Alias[] aliases;public string mode;public float x;public bool second;public int first_drop_tick,second_drop_tick=-1,first_legal_offset=-1;public float dt,cooldown;public List<Sample> samples=new List<Sample>();public List<Event> changes=new List<Event>();}
    static string config;PlayerController player;GameManager manager;Row live;int clock;bool driving;int drop0=-1;int lastScore,lastMerges;readonly List<int> targets=new List<int>{25,50,75,100};
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install() {var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaTimingProbe");if(i>=0){config=a[i+1];new GameObject("Time alignment diagnostic").AddComponent<SuikaTimingProbe>();}}
    static Alias[] Aliases(PlayerController p) {
        var fruits=new List<FruitEvolution>();foreach(var f in FindObjectsOfType<FruitEvolution>())if(f.Simulation==null&&!f.IsPreview&&!f.IsMerging)fruits.Add(f);
        fruits.Sort((a,b)=>a.fruitType!=b.fruitType?a.fruitType.CompareTo(b.fruitType):a.transform.position.x!=b.transform.position.x?a.transform.position.x.CompareTo(b.transform.position.x):a.transform.position.y.CompareTo(b.transform.position.y));
        var result=new List<Alias>();for(int i=0;i<fruits.Count;i++)result.Add(new Alias {from="f"+fruits[i].ObservationId,to="f"+i});
        result.Add(new Alias {from="f"+p.currentFruit.GetComponent<FruitEvolution>().ObservationId,to="A"});return result.ToArray();
    }
    static int MergeCount(PredictionDiagnostics.Recorder t) {int n=0;foreach(string e in t.history)if(e.Contains(":merge:"))n++;return n;}
    static void NativeSample(Row r,SuikaPhysicsSimulator.PathSession p,int elapsed,PredictionDiagnostics.Recorder trace) {
        var f=p.CaptureFrame();r.samples.Add(new Sample {elapsed_ticks=elapsed,score=p.Score,merges=MergeCount(trace),game_over=p.GameOver,fruits=f.fruits});
    }
    static Row Native(PlayerController p,GameManager g,Collider2D floor,float x,bool second) {
        var r=new Row {mode="prediction",aliases=Aliases(p),x=x,second=second,dt=Time.fixedDeltaTime,cooldown=p.dropCooldownSeconds};
        using(var path=new SuikaPhysicsSimulator.PathSession(p,g,floor)) {
            path.EnableTrace();var first=path.Advance(x,25,0);var trace=first.trace;r.first_drop_tick=first.drop_tick;
            foreach(var f in FindObjectsOfType<FruitEvolution>())if(f.Simulation!=null&&f.gameObject.scene.handle==path.SceneHandle&&f.IsPreview&&f.gameObject.activeInHierarchy)trace.Watch(f,"B");
            int elapsed=first.physics_steps-first.drop_tick;int score=path.Score,merges=MergeCount(trace);NativeSample(r,path,elapsed,trace);
            if(second&&!path.GameOver)using(var advance=path.AdvanceSearchTicks(0,25,-1,true,true,false)) {
                while(advance.MoveNext()) {
                    elapsed++;if(advance.Current!=null)r.second_drop_tick=first.physics_steps+advance.Current.drop_tick;
                    int m=MergeCount(trace);if(path.Score!=score||m!=merges){r.changes.Add(new Event {elapsed_tick=elapsed,score=path.Score,merges=m});score=path.Score;merges=m;}
                    if(elapsed==50||elapsed==75||elapsed==100)NativeSample(r,path,elapsed,trace);
                }
            }
            while(elapsed<100&&!path.GameOver) {
                path.WaitTicks(1);elapsed++;int m=MergeCount(trace);
                if(path.Score!=score||m!=merges){r.changes.Add(new Event {elapsed_tick=elapsed,score=path.Score,merges=m});score=path.Score;merges=m;}
                if(elapsed==50||elapsed==75||elapsed==100)NativeSample(r,path,elapsed,trace);
            }
        }return r;
    }
    void FixedUpdate() {
        if(!driving)return;clock++;
        if(drop0>=0&&live.first_legal_offset<0&&player.CanDropFruit)live.first_legal_offset=clock-drop0;
        bool needFirst=drop0<0;bool needSecond=live.second&&live.second_drop_tick<0&&drop0>=0&&clock-drop0>=26;
        if(!needFirst&&!needSecond)return;
        var range=player.GetDropRange();float x=needFirst?live.x:0;
        float target=Mathf.Lerp(range.min_x,range.max_x,x);float nx=Mathf.MoveTowards(player.currentFruit.transform.position.x,target,player.EffectiveAIMoveSpeed*Time.fixedDeltaTime);
        string error;if(!player.TryMoveHeldTo(nx,range,out error))throw new Exception(error);
        if(nx==target&&player.CanDropFruit) {
            float applied;long id;if(!player.TryDropAt(x,out applied,out id,out range,out error))throw new Exception(error);
            if(needFirst){drop0=clock;live.first_drop_tick=clock;PredictionDiagnostics.Live.Watch(player.currentFruit.GetComponent<FruitEvolution>(),"B");}else live.second_drop_tick=clock;
        }
    }
    IEnumerator Start() {
        yield return null;yield return null;var c=JsonUtility.FromJson<Config>(File.ReadAllText(config));player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();var udp=FindObjectOfType<UDPCommunicatorUnity>();
        var seen=new HashSet<string>();for(int i=0;i<25;i++){string key=MctsPlanner.CoverageAction(i,0)+":"+MctsPlanner.CoverageAction(i,1);if(!seen.Add(key))throw new Exception("Duplicate coverage schedule");}
        if(seen.Count!=25||MctsPlanner.CoverageAction(2,0)!=2||MctsPlanner.CoverageAction(2,1)!=0||MctsPlanner.CoverageAction(0,2)!=-1)throw new Exception("Invalid coverage schedule");
        Debug.Log("PAIR COVERAGE SCHEDULE CHECKS OK");
        Application.targetFrameRate=60;
        using(var log=new StreamWriter(new FileStream(c.output,FileMode.CreateNew)))foreach(float x in new[]{.5f,.75f})foreach(bool second in new[]{false,true}) {
            Time.timeScale=0;SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),c.fixture);Time.timeScale=0;
            yield return null;yield return null;
            var predicted=Native(player,manager,udp.planningFloor,x,second);log.WriteLine(JsonUtility.ToJson(predicted));log.Flush();
            // Loading only: retire old fixture objects while paused; do not freeze a playing trajectory.
            SuikaRuntimeProbe.Instance.LoadFixture(player,manager,Guid.NewGuid().ToString("N"),c.fixture);Time.timeScale=0;yield return null;yield return null;
            live=new Row {mode="live",aliases=Aliases(player),x=x,second=second,dt=Time.fixedDeltaTime,cooldown=player.dropCooldownSeconds};clock=0;drop0=-1;lastScore=ScoreManager.Instance.GetScore();lastMerges=ScoreManager.Instance.EpisodeMergeCount;
            PredictionDiagnostics.Begin(player,manager);player.StepControlLocked=true;driving=true;Time.timeScale=1;int read=1;
            while(driving) {
                yield return null;
                var recorder=PredictionDiagnostics.Live;
                while(read<recorder.frames.Count) {
                    var frame=recorder.frames[read++];int elapsed=frame.tick-live.first_drop_tick;
                    int merges=0;foreach(var f in recorder.frames) {if(f.tick>frame.tick)break;foreach(string e in f.events)if(e.StartsWith("merge:"))merges++;}
                    if(drop0>=0&&(frame.score!=lastScore||merges!=lastMerges)) {live.changes.Add(new Event {elapsed_tick=elapsed,score=frame.score,merges=merges});lastScore=frame.score;lastMerges=merges;}
                    if(drop0>=0&&targets.Contains(elapsed))live.samples.Add(new Sample {elapsed_ticks=elapsed,score=frame.score,merges=merges,game_over=frame.game_over,fruits=frame.fruits});
                    if(drop0>=0&&elapsed>=100)driving=false;
                }
                if(manager.isGameOver)driving=false;
                if(clock>250)throw new Exception("Timing probe exceeded bounded tick budget");
            }
            PredictionDiagnostics.Stop();player.StepControlLocked=false;Time.timeScale=0;log.WriteLine(JsonUtility.ToJson(live));log.Flush();
        }
        Application.Quit(0);
    }
}
