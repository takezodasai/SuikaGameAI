using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;

[Serializable] public class FrameSearchReport
{
    public string execution="frames-projected-root-v1",request_id,game_id,episode_id,final_policy,reason;
    public string validity_policy="Exact exposed-state equality at scheduled post-physics tick; canonical merge lineage; no uncalibrated tolerances. Solver cache is not observable.";
    public long action_id,start_tick,scheduled_tick,commit_tick;public int attempts,retries,fallbacks,update_frames,video_frames;
    public double wall_ms,work_ms,max_slice_ms,received_realtime,unity_bytes,managed_bytes,start_wall,commit_wall;
    public List<double> slice_ms=new List<double>();
    public int largest_slice_gc0;public bool tick_slicing;public MctsPerformance.Metric[] profile;public bool adopted;public List<Attempt> history=new List<Attempt>();
    [Serializable] public class Attempt
    {
        public long start_tick,target_tick,result_tick,validation_tick;public string rejection;
        public int lead_ticks,calibration_samples,completed_iterations,max_update_gap_ticks;
        public double start_wall,result_wall,validation_wall,search_game_seconds,search_wall_ms,ready_wait_game_seconds;
        public float initial_max_speed;public bool contacted_root;
        public int count,score,actual_score;public double work_ms;
        public long held_fruit_id,next_fruit_id;
        public PredictionDiagnostics.Frame initial,projected,live_at_result;
        public FrameStateDifference difference;
    }
}
[Serializable] public class FrameStateDifference
{
    public bool valid,ids_types=true,flags=true,contacts=true,score=true;
    public float position,velocity,angle,angular_velocity,mass,inertia,center_of_mass;
    // Exact comparison is deliberately conservative until a measured, action-safe
    // tolerance is established. Advancing ticks alone is never a rejection reason.
    public static FrameStateDifference Compare(PredictionDiagnostics.Frame expected,PredictionDiagnostics.Frame actual)
    {
        var d=new FrameStateDifference {score=expected.score==actual.score && expected.game_over==actual.game_over && expected.game_over_candidate==actual.game_over_candidate};
        var map=new Dictionary<string,PredictionDiagnostics.FruitState>();foreach(var f in actual.fruits)map.Add(f.id,f);
        d.ids_types=expected.fruits.Length==actual.fruits.Length;
        foreach(var f in expected.fruits)
        {
            PredictionDiagnostics.FruitState a;
            if(!map.TryGetValue(f.id,out a)){d.ids_types=false;continue;}
            d.ids_types &= f.type==a.type;
            d.flags &= f.preview==a.preview && f.merging==a.merging && f.sleeping==a.sleeping && f.has_collided==a.has_collided && f.tag_eligible==a.tag_eligible;
            d.contacts &= (f.contacts.Length>0)==(a.contacts.Length>0);
            // Held previews use native automatic mass properties until dropped.
            d.position=Mathf.Max(d.position,Vector2.Distance(f.position,a.position));
            if(f.preview)continue;
            d.velocity=Mathf.Max(d.velocity,Vector2.Distance(f.velocity,a.velocity));
            d.angle=Mathf.Max(d.angle,Mathf.Abs(Mathf.DeltaAngle(f.angle,a.angle)));
            d.angular_velocity=Mathf.Max(d.angular_velocity,Mathf.Abs(f.angular_velocity-a.angular_velocity));
            d.mass=Mathf.Max(d.mass,Mathf.Abs(f.mass-a.mass));d.inertia=Mathf.Max(d.inertia,Mathf.Abs(f.inertia-a.inertia));
            d.center_of_mass=Mathf.Max(d.center_of_mass,Vector2.Distance(f.center_of_mass,a.center_of_mass));
        }
        d.valid=d.ids_types&&d.flags&&d.contacts&&d.score&&d.position==0&&d.velocity==0&&d.angle==0&&d.angular_velocity==0&&d.mass==0&&d.inertia==0&&d.center_of_mass==0;
        return d;
    }
}

public partial class UDPCommunicatorUnity
{
    public partial class Observation {public long game_tick;[NonSerialized] public FrameSearchReport frame_search;}
    FrameSearchReport lastFrameSearch;
    FrameSearchReport frameReport;
    FrameSearchReport.Attempt frameAttempt;
    ActionMessage frameMessage;
    string frameCommandKey,frameConfig;
    PlanningSettings frameSettings;
    SuikaPhysicsSimulator.PathSession frameRoot;
    IEnumerator<StepPlanner.Decision> frameWork;
    StepPlanner.Decision frameDecision;
    PredictionDiagnostics.Frame frameExpected;
    long frameTick,frameHeldId,frameNextId;
    int frameStartVideo,frameStartRender;
    double frameStarted;
    bool frameReady,frameRetry,frameFallback;
    readonly FrameLeadEstimator adaptiveLead=new FrameLeadEstimator(),contactedLead=new FrameLeadEstimator();
    bool frameContacted;MctsPerformance frameProfile;
    FrameLeadEstimator CurrentLead {get {return frameContacted?contactedLead:adaptiveLead;}}
    long framePreviousUpdateTick,lastObservedDropTick,lastObservedLegalTick;
    void ResetDropClock(){lastObservedDropTick=lastObservedLegalTick=0;}
    bool AdaptiveFrame {get {return frameSettings.execution_mode=="frames_adaptive";}}

    string FrameConfiguration()
    {
        var parts=new List<string> {JsonUtility.ToJson(playerController.GetDropRange()),playerController.transform.position.ToString("R"),
            playerController.heldFruitOffset.ToString("R"),playerController.EffectiveAIMoveSpeed.ToString("R"),
            Time.fixedDeltaTime.ToString("R"),Time.timeScale.ToString("R"),gameManager.GameOverHeight.ToString("R"),
            playerController.dropCooldownSeconds.ToString("R"),Physics2D.gravity.ToString("R")};
        foreach(var c in FindObjectsOfType<Collider2D>())
            if(c.gameObject.scene==gameObject.scene && c.enabled && c.GetComponent<FruitEvolution>()==null)
                parts.Add(c.GetInstanceID()+":"+c.bounds.min.ToString("R")+":"+c.bounds.max.ToString("R"));
        parts.Sort(StringComparer.Ordinal);return String.Join("|",parts);
    }
    bool FrameDuplicate(ActionMessage m)
    {
        if(frameMessage==null)return false;
        if(m.action_id!=frameMessage.action_id)StepError(m,"busy");
        else if(JsonUtility.ToJson(m)!=frameCommandKey)StepError(m,"action_conflict");
        return true;
    }
    void BeginFrameSearch(ActionMessage m)
    {
        var settings=(m.planning_settings??planningSettings).Freeze();
        if(settings.ai_mode!="mcts"&&settings.ai_mode!="mcts_value")throw new ArgumentException("Frame prototype requires MCTS");
        frameReady=frameRetry=frameFallback=false;frameDecision=null;frameExpected=null;frameAttempt=null;
        frameSettings=settings;frameProfile=SuikaRuntimeProbe.Instance==null?null:new MctsPerformance();frameMessage=JsonUtility.FromJson<ActionMessage>(JsonUtility.ToJson(m));frameCommandKey=JsonUtility.ToJson(m);
        frameStarted=Time.realtimeSinceStartupAsDouble;frameStartRender=Time.frameCount;frameStartVideo=SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames;
        lastFrameSearch=null;
        adaptiveLead.SetConfiguration(JsonUtility.ToJson(settings));contactedLead.SetConfiguration(JsonUtility.ToJson(settings));
        frameReport=new FrameSearchReport {request_id=Guid.NewGuid().ToString("N"),game_id=SuikaWorkerOptions.GameId,episode_id=episodeId,action_id=m.action_id,start_tick=frameTick,start_wall=FrameWall()};
        frameReport.tick_slicing=settings.frame_tick_slicing;
        if(AdaptiveFrame)frameReport.execution="frames-adaptive-lead-v1";
        playerController.StepControlLocked=true;playerController.moveDirection=0;
        frameRetry=true;
    }
    void StartFrameAttempt()
    {using(MctsPerformance.Measure("frame_start_attempt"))StartFrameAttemptCore();}
    void StartFrameAttemptCore()
    {
        DisposeFrameWork();using(MctsPerformance.Measure("frame_aliases"))PredictionDiagnostics.BeginAliases(playerController,gameManager);
        var prior=frameAttempt;
        frameAttempt=new FrameSearchReport.Attempt {start_tick=frameTick,start_wall=FrameWall()};frameReport.history.Add(frameAttempt);frameReport.attempts++;
        int previousTicks=frameReport.attempts>1?(int)(frameTick-frameReport.history[frameReport.history.Count-2].start_tick):0;
        int lead=Math.Min(500,Math.Max(frameSettings.frame_lead_ticks,previousTicks*2));
        frameHeldId=playerController.currentFruit.GetComponent<FruitEvolution>().ObservationId;
        frameNextId=playerController.nextFruitObject.GetComponent<FruitEvolution>().ObservationId;
        frameAttempt.held_fruit_id=frameHeldId;frameAttempt.next_fruit_id=frameNextId;
        using(MctsPerformance.Measure("frame_configuration"))frameConfig=FrameConfiguration();
        using(MctsPerformance.Measure("frame_root_copy"))frameRoot=new SuikaPhysicsSimulator.PathSession(playerController,gameManager,planningFloor);
        using(MctsPerformance.Measure("frame_initial_capture")){frameRoot.EnableTrace();frameAttempt.initial=frameRoot.CaptureFrame();}
        foreach(var f in frameAttempt.initial.fruits)if(!f.preview)frameAttempt.initial_max_speed=Math.Max(frameAttempt.initial_max_speed,f.velocity.magnitude);
        frameContacted=false;foreach(var f in frameAttempt.initial.fruits)if(!f.preview && f.has_collided)frameContacted=true;
        frameAttempt.contacted_root=frameContacted;
        if(AdaptiveFrame)lead=FrameLeadEstimator.RetryLead(CurrentLead.Suggest(frameSettings.frame_lead_ticks),prior==null?0:prior.lead_ticks,prior!=null&&prior.rejection=="missed_scheduled_tick");
        frameAttempt.lead_ticks=lead;frameAttempt.calibration_samples=CurrentLead.Count;framePreviousUpdateTick=frameTick;
        frameAttempt.target_tick=frameTick+lead;frameReport.scheduled_tick=frameAttempt.target_tick;
        frameWork=FrameProjectionAndSearch(lead);frameDecision=null;frameExpected=null;frameReady=false;frameRetry=false;
    }
    IEnumerator<StepPlanner.Decision> FrameProjectionAndSearch(int lead)
    {
        // Projection is game time, not a sleep or a change to the actual physics clock.
        for(int i=0;i<lead;i+=frameSettings.frame_tick_slicing?1:4)
        {frameRoot.WaitTicks(Math.Min(frameSettings.frame_tick_slicing?1:4,lead-i));yield return null;if(frameRoot.GameOver)throw new InvalidOperationException("Projected waiting reaches GO");}
        frameExpected=frameRoot.CaptureFrame();frameAttempt.projected=frameExpected;frameAttempt.count=frameExpected.fruits.Length;frameAttempt.score=frameExpected.score;
        using(var work=MctsPlanner.PlanFrames(playerController,gameManager,frameRoot.LocalFloor,frameSettings,frameRoot))
            while(work.MoveNext())yield return work.Current;
    }
    void UpdateFrameSearch()
    {
        if(frameMessage==null)return;
        if(gameManager.isGameOver){var m=frameMessage;CancelFrameSearch("game_over");StepError(m,"game_over");return;}
        if(frameMessage.episode_id!=episodeId){CancelFrameSearch("episode_changed");return;}
        if(frameFallback){CommitFrameFallback();return;}
        if(Time.realtimeSinceStartupAsDouble-frameStarted>frameSettings.frame_timeout_seconds)
        {RejectFrame("wall_timeout",true);return;}
        // Bounded sampled allocation guard, never reduce configured depth/iterations.
        if(UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()>1500L*1024*1024)
        {RejectFrame("unity_allocation_guard_1500MiB",true);return;}
        if(frameAttempt!=null)frameAttempt.max_update_gap_ticks=Math.Max(frameAttempt.max_update_gap_ticks,(int)(frameTick-framePreviousUpdateTick));
        framePreviousUpdateTick=frameTick;
        var watch=Stopwatch.StartNew();
        int sliceGc=GC.CollectionCount(0);
        var updateProfile=MctsPerformance.Current;MctsPerformance.Current=frameProfile;
        try
        {
            if(frameRetry)StartFrameAttempt();
            if(!frameReady)
            {
                do {
                    var previous=MctsPerformance.Current;MctsPerformance.Current=frameProfile;
                    bool more;try {more=frameWork.MoveNext();}finally {MctsPerformance.Current=previous;}
                    if(!more){frameReady=true;frameAttempt.result_tick=frameTick;frameAttempt.result_wall=FrameWall();
                        if(SuikaRuntimeProbe.Instance!=null) {
                            PredictionDiagnostics.Live.frames.Clear();PredictionDiagnostics.Live.Capture(ScoreManager.Instance.GetScore(),gameManager.isGameOver);
                            frameAttempt.live_at_result=PredictionDiagnostics.Live.frames[0];
                        }
                        frameAttempt.search_game_seconds=(frameTick-frameAttempt.start_tick)*Time.fixedDeltaTime;
                        frameAttempt.search_wall_ms=(FrameWall()-frameAttempt.start_wall)*1000;
                        frameAttempt.completed_iterations=frameDecision==null||frameDecision.mcts==null?0:frameDecision.mcts.completed_iterations;
                        if(AdaptiveFrame && frameAttempt.completed_iterations==frameSettings.mcts_iterations)
                            CurrentLead.Observe((int)(frameTick-frameAttempt.start_tick),frameAttempt.max_update_gap_ticks);
                        frameReport.received_realtime=Time.realtimeSinceStartupAsDouble;break;}
                    if(frameWork.Current!=null)frameDecision=frameWork.Current;
                }while(watch.Elapsed.TotalMilliseconds<frameSettings.frame_budget_ms);
            }
        }
        catch(Exception e){RejectFrame("search_exception:"+e.Message,false);}
        finally
        {
            MctsPerformance.Current=updateProfile;
            double elapsed=watch.Elapsed.TotalMilliseconds;if(frameReport.slice_ms.Count<4096)frameReport.slice_ms.Add(elapsed);frameReport.work_ms+=elapsed;if(elapsed>frameReport.max_slice_ms)frameReport.largest_slice_gc0=GC.CollectionCount(0)-sliceGc;frameReport.max_slice_ms=Math.Max(frameReport.max_slice_ms,elapsed);
            if(frameAttempt!=null)frameAttempt.work_ms+=elapsed;
        }
    }
    void FrameFixedUpdate()
    {
        frameTick++;
        if(lastObservedDropTick>0 && lastObservedLegalTick==0 && playerController!=null && playerController.CanDropFruit) {
            lastObservedLegalTick=frameTick;
            if(activeStep!=null && activeStep.previous_drop_tick==lastObservedDropTick)activeStep.next_legal_tick=frameTick;
        }
        if(frameMessage==null||frameRetry||frameFallback)return;
        if(frameTick<frameAttempt.target_tick+1)return;
        frameAttempt.validation_tick=frameTick;frameAttempt.validation_wall=FrameWall();
        if(frameReady)frameAttempt.ready_wait_game_seconds=(frameTick-frameAttempt.result_tick)*Time.fixedDeltaTime;
        if(frameTick>frameAttempt.target_tick+1||!frameReady||frameDecision==null)
        {RejectFrame("missed_scheduled_tick",false);return;}
        // This FixedUpdate precedes tick T+1 physics: bodies are exactly post-T.
        if(gameManager.isGameOver){return;}
        if(playerController.currentFruit==null||playerController.nextFruitObject==null||
            playerController.currentFruit.GetComponent<FruitEvolution>().ObservationId!=frameHeldId||
            playerController.nextFruitObject.GetComponent<FruitEvolution>().ObservationId!=frameNextId||FrameConfiguration()!=frameConfig)
        {RejectFrame("held_next_or_configuration_changed",false);return;}
        PredictionDiagnostics.Live.frames.Clear();PredictionDiagnostics.Live.Capture(ScoreManager.Instance.GetScore(),gameManager.isGameOver);
        var actual=PredictionDiagnostics.Live.frames[0];frameAttempt.actual_score=actual.score;
        frameAttempt.difference=FrameStateDifference.Compare(frameExpected,actual);
        if(!frameAttempt.difference.valid||actual.game_over_candidate)
        {RejectFrame("projected_state_mismatch",false);return;}
        frameReport.adopted=true;frameReport.final_policy=frameSettings.ai_mode;
        // Use actual IDs in training/audit logs; local generated IDs are private.
        var aliases=new Dictionary<string,long>();foreach(var f in actual.fruits)aliases[f.id]=f.observation_id;
        var predictedIds=new Dictionary<long,string>();foreach(var f in frameExpected.fruits)
            if(!f.preview)foreach(var entry in frameRoot.CaptureIdAliases())if(entry.Value==f.id)predictedIds[entry.Key]=entry.Value;
        if(frameDecision.source_fruits!=null)foreach(var f in frameDecision.source_fruits)
            if(predictedIds.ContainsKey(f.id)&&aliases.ContainsKey(predictedIds[f.id]))f.id=aliases[predictedIds[f.id]];
        CommitFrameDecision(frameDecision);
    }
    void RejectFrame(string reason,bool final)
    {
        if(AdaptiveFrame && reason=="missed_scheduled_tick" && frameAttempt!=null)CurrentLead.ObserveMiss(frameAttempt.lead_ticks);
        frameReport.reason=reason;if(frameAttempt!=null)frameAttempt.rejection=reason;
        DisposeFrameWork();PredictionDiagnostics.Stop();frameReady=false;
        if(final||frameReport.attempts>=frameSettings.frame_max_attempts) {frameFallback=true;frameRetry=false;}
        else {frameReport.retries++;frameRetry=true;}
    }
    void CommitFrameFallback()
    {
        try {
            playerController.StepControlLocked=false;
            var s=frameSettings.Freeze();s.ai_mode="heuristic";s.execution_mode="sync";
            var watch=Stopwatch.StartNew();int fallbackGc=GC.CollectionCount(0);StepPlanner.Decision d;
            var previous=MctsPerformance.Current;MctsPerformance.Current=frameProfile;
            try {using(MctsPerformance.Measure("frame_fallback"))d=StepPlanner.Plan(playerController,gameManager,planningFloor,s);}
            finally {MctsPerformance.Current=previous;}
            double elapsed=watch.Elapsed.TotalMilliseconds;frameReport.work_ms+=elapsed;
            if(elapsed>frameReport.max_slice_ms){frameReport.max_slice_ms=elapsed;frameReport.largest_slice_gc0=GC.CollectionCount(0)-fallbackGc;}
            frameReport.fallbacks++;frameReport.final_policy="heuristic";CommitFrameDecision(d);
        } catch(Exception e){var m=frameMessage;CancelFrameSearch();StepError(m,"frame_fallback_rejected:"+e.Message);}
    }
    void CommitFrameDecision(StepPlanner.Decision decision)
    {
        var message=frameMessage;var report=frameReport;
        report.commit_wall=FrameWall();report.commit_tick=frameTick;report.wall_ms=(Time.realtimeSinceStartupAsDouble-frameStarted)*1000;
        report.update_frames=Time.frameCount-frameStartRender;report.video_frames=(SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames)-frameStartVideo;
        report.unity_bytes=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();report.managed_bytes=GC.GetTotalMemory(false);
        report.profile=frameProfile==null?null:frameProfile.Results();RecordFrameProbe(report);decision.frame_search=report;lastFrameSearch=report;DisposeFrameWork();PredictionDiagnostics.Stop();frameMessage=null;frameReport=null;frameReady=frameRetry=frameFallback=false;
        playerController.StepControlLocked=false;HandleStep(message,decision);
    }
    void DisposeFrameWork()
    {using(MctsPerformance.Measure("frame_dispose"))DisposeFrameWorkCore();}
    void DisposeFrameWorkCore()
    {
        try {if(frameWork!=null)frameWork.Dispose();}
        finally {frameWork=null;if(frameRoot!=null)frameRoot.Dispose();frameRoot=null;}
    }
    static double FrameWall(){return (double)Stopwatch.GetTimestamp()/Stopwatch.Frequency;}
    [Serializable] class FrameProbeRow {public string evt="frame_search";public FrameSearchReport report;}
    void RecordFrameProbe(FrameSearchReport report) {if(SuikaRuntimeProbe.Instance!=null)SuikaRuntimeProbe.Instance.Write(new FrameProbeRow {report=report});}
    public void CancelFrameSearch(string reason="reset")
    {
        if(frameMessage==null)return;
        frameReport.reason=reason;frameReport.final_policy="cancelled";frameReport.wall_ms=(Time.realtimeSinceStartupAsDouble-frameStarted)*1000;
        frameReport.update_frames=Time.frameCount-frameStartRender;frameReport.video_frames=(SuikaVideo.Instance==null?0:SuikaVideo.Instance.Frames)-frameStartVideo;
        frameReport.commit_wall=FrameWall();RecordFrameProbe(frameReport);lastFrameSearch=frameReport;
        DisposeFrameWork();PredictionDiagnostics.Stop();frameMessage=null;frameReport=null;frameDecision=null;
        frameReady=frameRetry=frameFallback=false;playerController.StepControlLocked=false;
    }
}
