using System;
using UnityEngine;

public partial class UDPCommunicatorUnity
{
    // A bounded observation window, not a settle-until-still or offline simulation.
    const float StepSimulationSeconds = 0.5f;
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
        public bool drop_success;
        public string status;
        public float requested_x, applied_x, applied_normalized_x, min_x, max_x;
        public int reward, score_before, physics_steps;
        public float movement_start_x, target_x, current_x, movement_speed, movement_seconds;
        public int movement_steps, planned_movement_steps;
    }

    void ClearStepForReset()
    {
        activeStep = null;
        pendingPrediction = null;
        completedStep = null;
        lastActionId = 0;
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

    void HandleStep(ActionMessage message)
    {
        RemoteControl = true;
        if (message.stream_id != streamId || message.episode_id != episodeId)
        { StepError(message, "stale_episode"); return; }
        if (message.action_id <= 0 || float.IsNaN(message.x) || float.IsInfinity(message.x) || message.x < 0 || message.x > 1)
        { StepError(message, "invalid_action"); return; }
        if (message.action_id == lastActionId)
        {
            if (message.x != acceptedX) { StepError(message, "action_conflict"); return; }
            if (completedStep != null) SendSnapshot(completedStep);
            return; // Busy retry: never move/drop a second fruit.
        }
        if (activeStep != null || playerController.StepControlLocked) { StepError(message, "busy"); return; }
        if (message.action_id != lastActionId + 1) { StepError(message, "out_of_order"); return; }
        if (gameManager.isGameOver) { StepError(message, "game_over"); return; }
        if (Time.timeScale <= 0) { StepError(message, "physics_paused"); return; }

        pendingPrediction = null;
        actualTotalPhysicsSteps = 0;
        if (message.command == "compare_step")
        {
            try { pendingPrediction = SuikaPhysicsSimulator.Predict(playerController, gameManager, message.x); }
            catch (Exception e) { StepError(message, "prediction_rejected:" + e.Message); return; }
        }
        playerController.StepControlLocked = true;
        // Reserve before any mutation: even an unexpected DropFruit exception must not
        // let a retried packet execute a second drop. Reset recovers an unknown outcome.
        lastActionId = message.action_id;
        acceptedX = message.x;
        completedStep = null;
        stepScoreBefore = ScoreManager.Instance.GetScore();
        movementRange = playerController.GetDropRange();
        float speed = playerController.aiMoveSpeed;
        if (!movementRange.valid || float.IsNaN(speed) || float.IsInfinity(speed) || speed <= 0)
        {
            playerController.StepControlLocked = false;
            completedStep = StepError(message, movementRange.valid ? "invalid_movement_speed" : movementRange.error);
            return;
        }
        physicsTicks = 0;
        targetTicks = Mathf.Max(1, Mathf.CeilToInt(StepSimulationSeconds / Time.fixedDeltaTime));
        activeStep = new StepResult {
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
    }

    void FixedUpdate()
    {
        if (activeStep == null || gameManager.isGameOver) return;
        actualTotalPhysicsSteps++;
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
            activeStep.movement_steps++;
            activeStep.movement_seconds += Time.fixedDeltaTime;
        }
        if (nextX != activeStep.target_x) return;
        float applied;
        long fruitId;
        activeStep.status = "dropping"; // Reserve the internal attempt too, before DropFruit can throw.
        if (!playerController.TryDropAt(activeStep.requested_x, out applied, out fruitId, out range, out error))
        { FailMovement(error); return; }
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
        activeStep.reward = ScoreManager.Instance.GetScore() - stepScoreBefore;
        activeStep.physics_steps = physicsTicks;
        completedStep = new Observation { step_result = activeStep, prediction = pendingPrediction,
            actual_total_physics_steps = actualTotalPhysicsSteps };
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
