using System;
using System.Collections.Generic;
using UnityEngine;

public partial class UDPCommunicatorUnity
{
    public partial class ActionMessage {public int path_probe_phase;public float path_second_x;}
    public partial class Observation {[NonSerialized] public PathComparisonReport path_comparison;}
    [Serializable] public class PathError
    {
        public bool types_count_match,score_match,game_over_match,held_type_match,next_type_match,next_known;
        public float max_position,max_velocity,max_angle,max_angular_velocity;
        public int history_mismatches,touching_mismatches,sleep_mismatches,unmatched_fruits;
        public int predicted_ticks,actual_ticks,predicted_score,actual_score,predicted_merges,actual_merges;
        public bool predicted_game_over,actual_game_over;
    }
    [Serializable] public class GoTimingEvidence
    {
        public int frames,max_physics_ticks_per_render,transient_candidate_ticks,first_candidate_tick=-1,merges;
        public bool truncated,completion_game_over;
    }
    [Serializable] public class PathComparisonReport
    {
        public string status,conditioning="All public spawn outcomes cloned at root; matching revealed NEXT selected only for retrospective validation";
        public int first_post_ticks,second_post_ticks,idle_physics_ticks,revealed_next_type,total_prediction_ticks;
        public int first_actual_ticks,second_actual_ticks;
        public bool root_unchanged_on_copy;
        public double elapsed_ms;
        public PathError first,second;
        public GoTimingEvidence first_timing,second_timing;
        public PredictionDiagnostics.Report first_trace_diagnostics,second_trace_diagnostics;
        public SuikaPhysicsSimulator.Result predicted_first,predicted_second;
    }
    sealed class ProbeRoot
    {
        public readonly List<SuikaPhysicsSimulator.PathSession> paths=new List<SuikaPhysicsSimulator.PathSession>();
        public float x1,x2;public long firstAction;
        public double firstComplete,secondAccept;
        public int firstPost,firstTicks,nextType;public long firstHeldId;
        public ValueSnapshot first;
        public GoTimingEvidence firstTiming;
        public bool unchanged;public PredictionDiagnostics.Recorder firstTrace;
    }
    ProbeRoot pathProbe;int pathProbePhase;
    void ClearPathProbe()
    {
        if(pathProbe!=null)foreach(var p in pathProbe.paths)p.Dispose();
        pathProbe=null;pathProbePhase=0;
    }
    void PreparePathProbe(ActionMessage message)
    {
        if(message.path_probe_phase==0){ClearPathProbe();return;}
        if(message.path_probe_phase==1)
        {
            ClearPathProbe();
            if(float.IsNaN(message.path_second_x)||float.IsInfinity(message.path_second_x)||message.path_second_x<0||message.path_second_x>1||playerController.fruits.Length>8)
                throw new ArgumentException("Invalid path probe");
            var before=SuikaPhysicsSimulator.LiveSignature(playerController);var random=UnityEngine.Random.state;
            pathProbe=new ProbeRoot {x1=message.x,x2=message.path_second_x,firstAction=message.action_id};
            try {for(int i=0;i<playerController.fruits.Length;i++){var path=new SuikaPhysicsSimulator.PathSession(playerController,gameManager,planningFloor);pathProbe.paths.Add(path);path.EnableTrace();}}
            catch {ClearPathProbe();throw;}
            pathProbe.unchanged=before==SuikaPhysicsSimulator.LiveSignature(playerController)&&random.Equals(UnityEngine.Random.state);
            if(!pathProbe.unchanged){ClearPathProbe();throw new InvalidOperationException("Probe root copy mutated source");}
        }
        else if(message.path_probe_phase==2)
        {
            if(pathProbe==null || pathProbe.first==null || message.action_id!=pathProbe.firstAction+1 || Mathf.Abs(message.x-pathProbe.x2)>1e-6f)
                throw new InvalidOperationException("Missing/mismatched probe first step");
            pathProbe.secondAccept=Time.fixedTimeAsDouble;
        }
        else throw new ArgumentException("path_probe_phase must be 0,1,2");
        pathProbePhase=message.path_probe_phase;PredictionDiagnostics.Begin(playerController,gameManager);
    }
    ValueSnapshot CaptureProbeState()
    {
        var values=new List<BoardFruit>();var contacts=new List<Collider2D>();
        foreach(var fruit in FindObjectsOfType<FruitEvolution>())
        {
            if(fruit.Simulation!=null || fruit.IsPreview || fruit.IsMerging)continue;
            var b=fruit.GetComponent<Rigidbody2D>();
            var value=new BoardFruit {id=fruit.ObservationId,type=fruit.fruitType,x=b.position.x,y=b.position.y,vx=b.velocity.x,vy=b.velocity.y,angle=b.rotation,angular_velocity=b.angularVelocity,has_collided=fruit.HasCollided};
            MeasureFruit(value,fruit,b,contacts);values.Add(value);
        }
        values.Sort((a,b)=>a.id.CompareTo(b.id));var held=playerController.currentFruit;var range=playerController.GetDropRange();
        return new ValueSnapshot {fruits=values.ToArray(),score=ScoreManager.Instance.GetScore(),game_over=gameManager.isGameOver,
            current_fruit=new ControlledFruit {present=held!=null,type=GetFruitType(held),x=held!=null?held.transform.position.x:0,y=held!=null?held.transform.position.y:0,y_known=held!=null},
            next_fruit_type=GetFruitType(playerController.nextFruitObject),drop_cooldown_remaining=playerController.DropCooldownRemaining,
            fixed_delta_time=Time.fixedDeltaTime,ai_move_speed=playerController.EffectiveAIMoveSpeed,
            geometry=new[]{range.left_wall_inner,range.right_wall_inner,planningFloor.bounds.max.y,gameManager.GameOverHeight}};
    }
    GoTimingEvidence ReadGoTiming()
    {
        var evidence=new GoTimingEvidence {completion_game_over=gameManager.isGameOver};var recorder=PredictionDiagnostics.Live;
        if(recorder==null)return evidence;evidence.frames=recorder.frames.Count;evidence.truncated=recorder.truncated;
        foreach(var line in recorder.history)if(line.Contains(":merge:"))evidence.merges++;
        var groups=new Dictionary<int,List<PredictionDiagnostics.Frame>>();
        foreach(var frame in recorder.frames)
        {
            if(!groups.ContainsKey(frame.render_frame))groups.Add(frame.render_frame,new List<PredictionDiagnostics.Frame>());
            groups[frame.render_frame].Add(frame);
            if(frame.game_over_candidate && evidence.first_candidate_tick<0)evidence.first_candidate_tick=frame.tick;
        }
        foreach(var group in groups.Values)
        {
            evidence.max_physics_ticks_per_render=Math.Max(evidence.max_physics_ticks_per_render,group.Count);
            if(!group[group.Count-1].game_over_candidate)foreach(var f in group)if(f.game_over_candidate)evidence.transient_candidate_ticks++;
        }
        return evidence;
    }
    public static PathError ComparePathState(ValueSnapshot predicted,ValueSnapshot actual,int predictedTicks,int actualTicks,int predictedMerges,int actualMerges)
    {
        var error=new PathError {types_count_match=predicted.fruits.Length==actual.fruits.Length,score_match=predicted.score==actual.score,
            game_over_match=predicted.game_over==actual.game_over,held_type_match=predicted.current_fruit.type==actual.current_fruit.type,
            next_known=predicted.next_fruit_type>=0,next_type_match=predicted.next_fruit_type>=0 && predicted.next_fruit_type==actual.next_fruit_type,
            predicted_ticks=predictedTicks,actual_ticks=actualTicks,predicted_score=predicted.score,actual_score=actual.score,
            predicted_merges=predictedMerges,actual_merges=actualMerges,predicted_game_over=predicted.game_over,actual_game_over=actual.game_over};
        // Root IDs are exact; new simulated IDs are local negatives. Match new objects
        // by type/nearest position; report missing objects instead of manufacturing IDs.
        var remaining=new List<BoardFruit>(actual.fruits);
        var ordered=new List<BoardFruit>(predicted.fruits);ordered.Sort((a,b)=>(a.id>0?0:1).CompareTo(b.id>0?0:1));
        foreach(var p in ordered)
        {
            BoardFruit best=null;float distance=float.PositiveInfinity;
            foreach(var a in remaining)
            {
                if(a.type!=p.type)continue;
                float d=(a.x-p.x)*(a.x-p.x)+(a.y-p.y)*(a.y-p.y);
                if(p.id>0){if(a.id==p.id){best=a;break;}continue;}
                if(d<distance){best=a;distance=d;}
            }
            if(best==null){error.types_count_match=false;error.unmatched_fruits++;continue;}
            remaining.Remove(best);error.max_position=Math.Max(error.max_position,Vector2.Distance(new Vector2(p.x,p.y),new Vector2(best.x,best.y)));
            error.max_velocity=Math.Max(error.max_velocity,Vector2.Distance(new Vector2(p.vx,p.vy),new Vector2(best.vx,best.vy)));
            error.max_angle=Math.Max(error.max_angle,Mathf.Abs(Mathf.DeltaAngle(p.angle,best.angle)));
            error.max_angular_velocity=Math.Max(error.max_angular_velocity,Mathf.Abs(p.angular_velocity-best.angular_velocity));
            if(p.has_collided!=best.has_collided)error.history_mismatches++;
            if(p.touching!=best.touching)error.touching_mismatches++;
            if(p.sleeping!=best.sleeping)error.sleep_mismatches++;
        }
        error.unmatched_fruits+=remaining.Count;return error;
    }
    PathComparisonReport FinishPathProbe(StepResult actual,int actualTicks)
    {
        if(pathProbe==null || pathProbePhase==0)return null;
        var state=CaptureProbeState();var timing=ReadGoTiming();
        if(pathProbePhase==1 && !state.game_over)
        {
            pathProbe.firstHeldId=playerController.currentFruit.GetComponent<FruitEvolution>().ObservationId;
            pathProbe.first=state;pathProbe.firstPost=actual.physics_steps;pathProbe.firstTicks=actualTicks;
            pathProbe.firstComplete=Time.fixedTimeAsDouble;pathProbe.nextType=state.next_fruit_type;pathProbe.firstTiming=timing;pathProbe.firstTrace=PredictionDiagnostics.Live;pathProbePhase=0;
            return new PathComparisonReport {status="awaiting_second_action",first_post_ticks=actual.physics_steps,first_timing=timing,root_unchanged_on_copy=pathProbe.unchanged};
        }
        var report=new PathComparisonReport {status=pathProbePhase==1?"actual_terminal_after_first":"completed",root_unchanged_on_copy=pathProbe.unchanged};
        if(pathProbePhase==1)
        {
            try {var predicted=pathProbe.paths[0].Advance(pathProbe.x1,Math.Max(1,actual.physics_steps),-1);
                report.predicted_first=predicted;report.first=ComparePathState(predicted.value_state,state,predicted.physics_steps,actualTicks,predicted.merges,timing.merges);
                report.first_trace_diagnostics=PredictionDiagnostics.Compare(predicted.trace,PredictionDiagnostics.Live);report.first_timing=timing;}
            catch(Exception e){report.status="comparison_failed:"+e.Message;}
            finally {ClearPathProbe();}return report;
        }
        var timer=System.Diagnostics.Stopwatch.StartNew();
        try
        {
            int slot=-1;for(int i=0;i<playerController.fruits.Length;i++)if(playerController.fruits[i].GetComponent<FruitEvolution>().fruitType==pathProbe.nextType){slot=i;break;}
            if(slot<0)throw new InvalidOperationException("Revealed NEXT not in public distribution");
            report.first_post_ticks=pathProbe.firstPost;report.second_post_ticks=actual.physics_steps;
            report.first_actual_ticks=pathProbe.firstTicks;report.second_actual_ticks=actualTicks;
            report.revealed_next_type=pathProbe.nextType;
            report.idle_physics_ticks=(int)Math.Round((pathProbe.secondAccept-pathProbe.firstComplete)/Time.fixedDeltaTime);
            var path=pathProbe.paths[slot];
            var first=path.Advance(pathProbe.x1,Math.Max(1,pathProbe.firstPost),slot);report.predicted_first=first;
            report.first_trace_diagnostics=PredictionDiagnostics.Compare(first.trace,pathProbe.firstTrace);
            report.first=ComparePathState(first.value_state,pathProbe.first,first.physics_steps,pathProbe.firstTicks,first.merges,pathProbe.firstTiming.merges);
            if(!path.GameOver)path.WaitTicks(report.idle_physics_ticks);
            if(!path.GameOver)
            {
                path.EnableContinuationTrace(pathProbe.first,pathProbe.firstHeldId);
                var second=path.Advance(pathProbe.x2,Math.Max(1,actual.physics_steps),-1);report.predicted_second=second;
                report.second_trace_diagnostics=PredictionDiagnostics.Compare(second.trace,PredictionDiagnostics.Live);
                report.second=ComparePathState(second.value_state,state,second.physics_steps,actualTicks,second.merges,timing.merges);
            }
            else {report.status="prediction_terminal_before_second";report.second=ComparePathState(path.Snapshot(),state,0,actualTicks,0,timing.merges);}
            report.total_prediction_ticks=path.TotalTicks;report.first_timing=pathProbe.firstTiming;report.second_timing=timing;
        }
        catch(Exception e) {report.status="comparison_failed:"+e.Message;}
        finally {report.elapsed_ms=timer.Elapsed.TotalMilliseconds;ClearPathProbe();}
        return report;
    }
}
