using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

public partial class UDPCommunicatorUnity
{
    // A stream lasts for this component's lifetime; state_id never rewinds on reset.
    private readonly string streamId = Guid.NewGuid().ToString("N");
    private string episodeId;
    private long stateId;
    private string resetRequestId = "";
    public bool RemoteControl { get; private set; }

    public void BeginEpisode(string requestId)
    {
        episodeId = Guid.NewGuid().ToString("N");
        resetRequestId = requestId;
        ClearStepForReset();
        ResetRewardAccounting();
    }

    void HandleCommand(ActionMessage message)
    {
        if (message.command == "observe")
        {
            RemoteControl = true;
        }
        else if ((message.command == "step" || message.command == "compare_step"))
        {
            HandleStep(message);
        }
        else if (message.command == "reset")
        {
            if (string.IsNullOrEmpty(message.request_id) || message.request_id.Length > 128)
            {
                Debug.LogWarning("reset requires a request_id of 1..128 characters.");
                return;
            }
            RemoteControl = true;
            // Retry of the last completed reset is acknowledged by subsequent snapshots.
            // An old episode's delayed request must never reset a newer episode.
            if (message.request_id == resetRequestId) return;
            if (message.episode_id != episodeId) return;
            gameManager.ResetGame(message.request_id);
        }
        else if (string.IsNullOrEmpty(message.command))
        {
            ProcessAction(message.action); // Existing {"action": n} protocol.
        }
        else Debug.LogWarning("Unknown UDP command: " + message.command);
    }

    int GetFruitType(GameObject fruit)
    {
        if (fruit == null) return -1;
        FruitEvolution evolution = fruit.GetComponent<FruitEvolution>();
        return evolution != null ? evolution.fruitType : -1;
    }

    void SendPacket(Observation observation)
    {
        if (udpSender == null) return;
        observation.protocol_version = 2;
        observation.stream_id = streamId;
        observation.episode_id = episodeId;
        observation.state_id = ++stateId;
        observation.reset_request_id = resetRequestId;
        observation.game_over = gameManager.isGameOver;
        observation.done = observation.game_over;
        observation.score = ScoreManager.Instance.GetScore();
        observation.reward_accounting = ReadRewardAccounting(observation.score);
        observation.previous_episode_reward_accounting = previousEpisodeRewards;
        GameObject held = playerController.currentFruit;
        observation.current_fruit = new ControlledFruit {
            present = held != null, type = GetFruitType(held),
            x = held != null ? held.transform.position.x : 0
        };
        observation.next_fruit_type = GetFruitType(playerController.nextFruitObject);
        observation.drop_range = playerController.GetDropRange();
        observation.ai_move_speed = playerController.EffectiveAIMoveSpeed;
        observation.fixed_delta_time = Time.fixedDeltaTime;
        observation.time_scale = Time.timeScale;
        observation.drop_cooldown_seconds = playerController.dropCooldownSeconds;
        observation.drop_cooldown_remaining = playerController.DropCooldownRemaining;
        observation.step_progress = activeStep;
        var fruits = new List<BoardFruit>();
        foreach (FruitEvolution fruit in FindObjectsOfType<FruitEvolution>())
        {
            if (fruit.IsPreview || fruit.IsMerging || fruit.gameObject == held ||
                fruit.gameObject == playerController.nextFruitObject) continue;
            Rigidbody2D body = fruit.GetComponent<Rigidbody2D>();
            if (body == null)
                throw new InvalidOperationException("Board fruit has no Rigidbody2D.");
            fruits.Add(new BoardFruit {
                id = fruit.ObservationId, type = fruit.fruitType,
                x = body.position.x, y = body.position.y,
                vx = body.velocity.x, vy = body.velocity.y,
                angle = body.rotation, angular_velocity = body.angularVelocity, has_collided = fruit.HasCollided
            });
        }
        fruits.Sort((a, b) => a.id.CompareTo(b.id));
        observation.fruits = fruits.ToArray();
        SendSnapshot(observation);
    }

    void SendSnapshot(Observation observation)
    {
        if (udpSender == null) return;
        byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(observation));
        if (bytes.Length <= 60000)
        {
            udpSender.Send(bytes, bytes.Length, remoteEndPoint);
            return;
        }
        // Never truncate a large board. Reassemble only complete snapshots in Python.
        const int chunkSize = 42000;
        int count = (bytes.Length + chunkSize - 1) / chunkSize;
        for (int index = 0; index < count; index++)
        {
            var fragment = new StateFragment {
                stream_id = streamId, state_id = observation.state_id, count = count, index = index,
                data = Convert.ToBase64String(bytes, index * chunkSize,
                    Math.Min(chunkSize, bytes.Length - index * chunkSize))
            };
            byte[] packet = Encoding.UTF8.GetBytes(JsonUtility.ToJson(fragment));
            udpSender.Send(packet, packet.Length, remoteEndPoint);
        }
    }

    [Serializable]
    public class BoardFruit
    {
        public long id;
        public bool has_collided;
        public int type;
        public float x, y, vx, vy, angle, angular_velocity;
    }
    [Serializable]
    public class ControlledFruit { public bool present; public int type; public float x;
        public int prediction_post_drop_steps; }

    public partial class ActionMessage
    {
        public string command, request_id, episode_id;
        public string stream_id;
        public long action_id;
        public bool trace_physics;
        public int comparison_post_drop_steps;
        public float x;
    }
    public partial class Observation
    {
        public RewardAccounting reward_accounting, previous_episode_reward_accounting;
        public int protocol_version;
        public string stream_id, episode_id, reset_request_id;
        public long state_id;
        public bool game_over;
        public BoardFruit[] fruits;
        public ControlledFruit current_fruit;
        public int next_fruit_type;
        public PlayerController.DropRange drop_range;
        public StepResult step_result;
        public SuikaPhysicsSimulator.Result prediction;
        public int actual_total_physics_steps;
        public StepResult step_progress;
        public float ai_move_speed, fixed_delta_time, time_scale, drop_cooldown_seconds, drop_cooldown_remaining;
    }
    [Serializable]
    class StateFragment
    {
        public string message_type = "state_fragment";
        public string stream_id, data;
        public long state_id;
        public int index, count;
    }

    [Serializable] public class RewardInterval
    {
        public bool present; // JsonUtility serializes null classes as empty objects.
        public string phase; // No causal attribution for between_steps (action_id=0).
        public long action_id;
        public int score_before, score_after, reward;
        public double game_time_start, game_time_end, fixed_time_start, fixed_time_end;
    }
    [Serializable] public class RewardAccounting
    {
        public bool present;
        public string episode_id;
        public int version = 1, episode_start_score, episode_score, step_reward_total, between_steps_reward_total;
        public bool conserved;
        public RewardInterval last_step, last_between_steps, open_interval;
    }
    RewardAccounting previousEpisodeRewards;
    public void CaptureEpisodeRewardSummary()
    { if (!string.IsNullOrEmpty(episodeId)) previousEpisodeRewards = ReadRewardAccounting(ScoreManager.Instance.GetScore()); }

    int rewardStartScore, rewardBoundaryScore, stepRewardTotal, betweenRewardTotal;
    double rewardBoundaryTime, rewardBoundaryFixedTime;
    long rewardActionId;
    RewardInterval lastRewardStep, lastRewardGap;

    void ResetRewardAccounting()
    {
        rewardStartScore = rewardBoundaryScore = ScoreManager.Instance.GetScore();
        stepRewardTotal = betweenRewardTotal = 0;
        rewardActionId = 0;
        lastRewardStep = lastRewardGap = null;
        rewardBoundaryTime = Time.timeAsDouble;
        rewardBoundaryFixedTime = Time.fixedTimeAsDouble;
    }
    RewardInterval OpenRewardInterval(int score)
    {
        return new RewardInterval {
            present = true, phase = rewardActionId == 0 ? "between_steps" : "in_step", action_id = rewardActionId,
            score_before = rewardBoundaryScore, score_after = score, reward = score - rewardBoundaryScore,
            game_time_start = rewardBoundaryTime, game_time_end = Time.timeAsDouble,
            fixed_time_start = rewardBoundaryFixedTime, fixed_time_end = Time.fixedTimeAsDouble
        };
    }
    void AdvanceRewardBoundary(int score)
    {
        rewardBoundaryScore = score;
        rewardBoundaryTime = Time.timeAsDouble;
        rewardBoundaryFixedTime = Time.fixedTimeAsDouble;
    }
    void BeginRewardStep(long actionId, int score)
    {
        if (rewardActionId != 0) throw new InvalidOperationException("Reward interval already active");
        lastRewardGap = OpenRewardInterval(score);
        betweenRewardTotal += lastRewardGap.reward;
        AdvanceRewardBoundary(score);
        rewardActionId = actionId;
    }
    void EndRewardStep(int score)
    {
        if (rewardActionId == 0) throw new InvalidOperationException("No active reward interval");
        lastRewardStep = OpenRewardInterval(score);
        stepRewardTotal += lastRewardStep.reward;
        AdvanceRewardBoundary(score);
        rewardActionId = 0;
    }
    RewardAccounting ReadRewardAccounting(int score)
    {
        var open = OpenRewardInterval(score);
        return new RewardAccounting {
            present = true, episode_id = episodeId, episode_start_score = rewardStartScore, episode_score = score,
            step_reward_total = stepRewardTotal, between_steps_reward_total = betweenRewardTotal,
            last_step = lastRewardStep, last_between_steps = lastRewardGap, open_interval = open,
            conserved = score == rewardStartScore + stepRewardTotal + betweenRewardTotal + open.reward
        };
    }

}
