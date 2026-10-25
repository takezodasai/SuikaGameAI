using System;
using UnityEngine;

public partial class UDPCommunicatorUnity
{
    // A bounded observation window, not a settle-until-still or offline simulation.
    const float StepSimulationSeconds = 0.5f;
    [Header("STEP 5 planning (existing floor collider)")]
    public Collider2D planningFloor;
    public PlanningSettings planningSettings = new PlanningSettings();
    StepPlanner.Decision activePlanning;
    MctsDepthControl.History depthHistory;
    PlanningSettings depthRequested;
    string acceptedCommandKey;
    long lastActionId;
    float acceptedX;
    int stepScoreBefore, physicsTicks, targetTicks;
    StepResult activeStep;
    SuikaPhysicsSimulator.Result pendingPrediction;
    int actualTotalPhysicsSteps;
    PlayerController.DropRange movementRange;
    Observation completedStep;

    [Serializable]
    public class StepResult
    {
        public long action_id, dropped_fruit_id;
        public long request_tick,decision_finish_tick,movement_start_tick,drop_tick,completion_tick,previous_drop_tick,next_legal_tick;
        public double request_wall,decision_start_wall,decision_finish_wall,drop_wall,drop_game_time,completion_wall;
        public bool drop_success;
        public string status;
        public float requested_x, applied_x, applied_normalized_x, min_x, max_x;
        public int reward, score_before, physics_steps;
        public int movement_reward,cooldown_wait_reward,post_drop_reward,other_in_step_reward,score_at_drop;
        public bool has_score_at_drop;
        public float movement_start_x, target_x, current_x, movement_speed, movement_seconds;
        public int movement_steps, planned_movement_steps;
    }

    void ClearStepForReset()
    {
        CancelFrameSearch();
        depthHistory=null;depthRequested=null;
        ResetDropClock();
        ClearPathProbe();
        activeStep = null;
        activePlanning = null; acceptedCommandKey = null;
        pendingPrediction = null;
        PredictionDiagnostics.Stop();
        completedStep = null;
        lastActionId = 0; rewardPhase=null;
        if (playerController != null) playerController.StepControlLocked = false;
    }

    Observation StepError(ActionMessage message, string status)
    {
        var response = new Observation { step_result = new StepResult {
            action_id = message.action_id, requested_x = message.x, status = status
        }};
        SendPacket(response);
        return response;
    }

    void HandleStep(ActionMessage message,StepPlanner.Decision prepared=null)
    {
        long receivedTick=frameTick;double receivedWall=FrameWall();
        string commandKey=JsonUtility.ToJson(message);
        RemoteControl = true;
        if (message.stream_id != streamId || message.episode_id != episodeId)
        { StepError(message, "stale_episode"); return; }
        if (message.action_id <= 0 || float.IsNaN(message.x) || float.IsInfinity(message.x) || message.x < 0 || message.x > 1)
        { StepError(message, "invalid_action"); return; }
        if (message.action_id == lastActionId)
        {
            if (commandKey != acceptedCommandKey) { StepError(message, "action_conflict"); return; }
            if (completedStep != null) SendSnapshot(completedStep);
            return; // Busy retry: never move/drop a second fruit.
        }
        if(prepared==null && FrameDuplicate(message))return;
        if (activeStep != null || playerController.StepControlLocked) { StepError(message, "busy"); return; }
        if (message.action_id != lastActionId + 1) { StepError(message, "out_of_order"); return; }
        if (gameManager.isGameOver) { StepError(message, "game_over"); return; }
        if (Time.timeScale <= 0) { StepError(message, "physics_paused"); return; }

        if(prepared==null && message.command=="plan_step" && (message.planning_settings??planningSettings).execution_mode!="sync")
        {try {BeginFrameSearch(message);}catch(Exception e){StepError(message,"frame_search_rejected:"+e.Message);}return;}
        try {PreparePathProbe(message);} catch(Exception e) {StepError(message,"path_probe_rejected:"+e.Message);return;}
        activePlanning=null;
        SuikaRuntimeProbe.ActionEvent("decision_start",episodeId,message.action_id,playerController);
        if(message.command=="plan_step")
        {
            try
            {
                using(var probe=prepared==null?SuikaRuntimeProbe.BeginPlan(message.planning_settings ?? planningSettings):null)
                {
                    depthRequested=message.planning_settings??planningSettings;
                    MctsDepthControl.Choice choice=null;
                    var resolved=depthRequested.mcts_extended_budget?MctsDepthControl.Resolve(depthRequested,depthHistory,episodeId,out choice):depthRequested;
                    activePlanning=prepared??StepPlanner.Plan(playerController,gameManager,planningFloor,resolved);
                    if(choice!=null)activePlanning.mcts.depth_selection=choice;
                    if(probe!=null)probe.Finish(activePlanning);
                }
                activePlanning.episode_id=episodeId; activePlanning.source_state_id=stateId;
                if(activePlanning.selected_index<0) { SendPacket(new Observation { planning=activePlanning,
                    step_result=new StepResult {action_id=message.action_id,status=activePlanning.status} }); return; }
                message.x=activePlanning.selected_x;
            }
            catch(Exception e) { StepError(message,"planning_rejected:"+e.Message); return; }
        }
        int comparisonTicks = message.command == "plan_step" ? activePlanning.settings.post_drop_steps :
            message.command == "compare_step" ? message.comparison_post_drop_steps : 0;
        if (comparisonTicks < 0 || comparisonTicks > 150) { StepError(message, "invalid_comparison_horizon"); return; }
        pendingPrediction = null;
        actualTotalPhysicsSteps = 0;
        if (message.command == "compare_step")
        {
            try
            {
                // Paired A/B uses the SAME live board; prediction never advances it.
                var reference = message.trace_physics
                    ? SuikaPhysicsSimulator.Predict(playerController, gameManager, message.x, comparisonTicks == 0 ? -1 : comparisonTicks) : null;
                if (message.trace_physics) PredictionDiagnostics.Begin(playerController, gameManager);
                pendingPrediction = SuikaPhysicsSimulator.Predict(playerController, gameManager, message.x, comparisonTicks == 0 ? -1 : comparisonTicks);
                if (reference != null)
                {
                    pendingPrediction.reference_elapsed_ms = reference.elapsed_ms;
                    pendingPrediction.reference_fruits = reference.fruits;
                    pendingPrediction.reference_score = reference.score;
                    pendingPrediction.reference_game_over = reference.game_over;
                }
            }
            catch (Exception e) { PredictionDiagnostics.Stop(); StepError(message, "prediction_rejected:" + e.Message); return; }
        }
        playerController.StepControlLocked = true;
        // Reserve before any mutation: even an unexpected DropFruit exception must not
        // let a retried packet execute a second drop. Reset recovers an unknown outcome.
        lastActionId = message.action_id;
        acceptedX = message.x;
        acceptedCommandKey=commandKey;
        completedStep = null;
        stepScoreBefore = ScoreManager.Instance.GetScore();
        movementRange = playerController.GetDropRange();
        float speed = playerController.EffectiveAIMoveSpeed;
        if (!movementRange.valid || float.IsNaN(speed) || float.IsInfinity(speed) || speed <= 0)
        {
            playerController.StepControlLocked = false;
            completedStep = StepError(message, movementRange.valid ? "invalid_movement_speed" : movementRange.error);
            return;
        }
        BeginRewardStep(message.action_id, stepScoreBefore);
        physicsTicks = 0;
        targetTicks = comparisonTicks > 0 ? comparisonTicks : Mathf.Max(1, Mathf.CeilToInt(StepSimulationSeconds / Time.fixedDeltaTime));
        // Prepared searches finish before their reserved commit tick. Preserve
        // that distinction; fallback includes its final synchronous evaluation.
        var preparedReport=prepared==null?null:prepared.frame_search;
        var preparedHistory=preparedReport==null?null:preparedReport.history;
        bool hasSearchHistory=preparedHistory!=null && preparedHistory.Count>0;
        var finalSearch=hasSearchHistory?preparedHistory[preparedHistory.Count-1]:null;
        activeStep = new StepResult {
            request_tick=prepared!=null&&prepared.frame_search!=null?prepared.frame_search.start_tick:receivedTick,
            request_wall=prepared!=null&&prepared.frame_search!=null?prepared.frame_search.start_wall:receivedWall,
            decision_start_wall=hasSearchHistory?preparedHistory[0].start_wall:receivedWall,
            decision_finish_wall=hasSearchHistory&&preparedReport.adopted?finalSearch.result_wall:FrameWall(),
            decision_finish_tick=hasSearchHistory&&preparedReport.adopted?finalSearch.result_tick:frameTick,movement_start_tick=frameTick,
            previous_drop_tick=lastObservedDropTick,next_legal_tick=lastObservedLegalTick,
            action_id = message.action_id, requested_x = message.x,
            min_x = movementRange.min_x, max_x = movementRange.max_x,
            status = "moving", score_before = stepScoreBefore,
            movement_start_x = playerController.currentFruit.transform.position.x,
            current_x = playerController.currentFruit.transform.position.x,
            target_x = Mathf.Lerp(movementRange.min_x, movementRange.max_x, message.x),
            movement_speed = speed
        };
        activeStep.planned_movement_steps = Mathf.CeilToInt(
            Mathf.Abs(activeStep.target_x - activeStep.movement_start_x) / (speed * Time.fixedDeltaTime));
        playerController.moveDirection = 0;
        SuikaRuntimeProbe.ActionEvent("movement_start",episodeId,message.action_id,playerController);
    }

    int phaseScore; string rewardPhase;
    void CapturePhysicsReward()
    {
        if(activeStep==null || rewardPhase==null) return;
        int delta=ScoreManager.Instance.GetScore()-phaseScore;
        if(rewardPhase=="post") activeStep.post_drop_reward+=delta;
        else if(rewardPhase=="move") activeStep.movement_reward+=delta;
        else activeStep.cooldown_wait_reward+=delta;
        rewardPhase=null;
    }
    void FixedUpdate()
    {
        FrameFixedUpdate();
        CapturePhysicsReward();
        if (activeStep == null || gameManager.isGameOver) return;
        if(actualTotalPhysicsSteps==0)activeStep.movement_start_tick=frameTick;
        actualTotalPhysicsSteps++;
        phaseScore=ScoreManager.Instance.GetScore(); rewardPhase=activeStep.drop_success?"post":"wait";
        if (activeStep.status == "dropping") return; // Unexpected exception: outcome unknown until reset.
        if (activeStep.drop_success) { physicsTicks++; return; }
        if (playerController.currentFruit == null) { FailMovement("no_current_fruit"); return; }
        PlayerController.DropRange range = playerController.GetDropRange();
        if (!range.valid || Mathf.Abs(range.min_x - movementRange.min_x) > 0.00001f ||
            Mathf.Abs(range.max_x - movementRange.max_x) > 0.00001f)
        { FailMovement("movement_range_changed"); return; }
        float oldX = playerController.currentFruit.transform.position.x;
        float nextX = Mathf.MoveTowards(oldX, activeStep.target_x, activeStep.movement_speed * Time.fixedDeltaTime);
        string error;
        if (!playerController.TryMoveHeldTo(nextX, movementRange, out error))
        { FailMovement(error); return; }
        activeStep.current_x = nextX;
        if (nextX != oldX)
        {
            rewardPhase="move";
            activeStep.movement_steps++;
            activeStep.movement_seconds += Time.fixedDeltaTime;
        }
        if (nextX != activeStep.target_x) return;
        if (!playerController.CanDropFruit) return; // Wait at the target; do not fail/repeat the reserved action.
        float applied;
        long fruitId;
        activeStep.score_at_drop=ScoreManager.Instance.GetScore(); activeStep.has_score_at_drop=true;
        rewardPhase="post";
        activeStep.status = "dropping"; // Reserve the internal attempt too, before DropFruit can throw.
        if (!playerController.TryDropAt(activeStep.requested_x, out applied, out fruitId, out range, out error))
        { FailMovement(error); return; }
        activeStep.drop_tick=frameTick;activeStep.drop_wall=FrameWall();activeStep.drop_game_time=Time.timeAsDouble;
        lastObservedDropTick=frameTick;lastObservedLegalTick=0;
        SuikaRuntimeProbe.ActionEvent("drop",episodeId,activeStep.action_id,playerController);
        activeStep.applied_x = applied;
        // Bounds can shift by a few float ULPs while translating the same polygon.
        // Report the exact final range used by TryDropAt, not the earlier estimate.
        activeStep.min_x = range.min_x;
        activeStep.max_x = range.max_x;
        activeStep.applied_normalized_x = Mathf.InverseLerp(range.min_x, range.max_x, applied);
        activeStep.dropped_fruit_id = fruitId;
        activeStep.drop_success = true;
        activeStep.status = "post_drop";
        physicsTicks = 0; // Count only AFTER the actual drop, never from movement start.
    }

    void FailMovement(string error)
    {
        activeStep.status = error;
        CompleteStep();
    }

    void CompleteStep()
    {
        activeStep.completion_tick=frameTick;activeStep.completion_wall=FrameWall();
        SuikaRuntimeProbe.ActionEvent("complete",episodeId,activeStep.action_id,playerController);
        CapturePhysicsReward();
        activeStep.reward = ScoreManager.Instance.GetScore() - stepScoreBefore;
        activeStep.physics_steps = physicsTicks;
        activeStep.other_in_step_reward=activeStep.reward-activeStep.movement_reward-activeStep.cooldown_wait_reward-activeStep.post_drop_reward;
        if(activeStep.other_in_step_reward!=0) Debug.LogWarning("STEP score occurred outside physics phase: "+activeStep.other_in_step_reward);
        if (pendingPrediction != null && pendingPrediction.trace != null)
        {
            pendingPrediction.diagnostics = PredictionDiagnostics.Compare(pendingPrediction.trace);
            pendingPrediction.diagnostics.actual_completion_game_over = gameManager.isGameOver;
            pendingPrediction.diagnostics.predicted_completion_game_over = pendingPrediction.game_over;
        }
        var pathReport=FinishPathProbe(activeStep,actualTotalPhysicsSteps);
        PredictionDiagnostics.Stop();
        EndRewardStep(ScoreManager.Instance.GetScore());
        completedStep = new Observation { step_result = activeStep, prediction = pendingPrediction,
            actual_total_physics_steps = actualTotalPhysicsSteps, planning=activePlanning,path_comparison=pathReport };
        depthHistory=MctsDepthControl.Capture(activePlanning,depthRequested??planningSettings,episodeId);
        activePlanning=null;
        pendingPrediction = null;
        activeStep = null;
        playerController.StepControlLocked = false;
        SendPacket(completedStep);
    }

    void LateUpdate()
    {
        if (activeStep != null && activeStep.status == "dropping") return;
        if (activeStep == null || (!gameManager.isGameOver && (!activeStep.drop_success || physicsTicks < targetTicks))) return;
        activeStep.status = "completed";
        CompleteStep();
    }
}
