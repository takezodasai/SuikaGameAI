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
        GameObject held = playerController.currentFruit;
        observation.current_fruit = new ControlledFruit {
            present = held != null, type = GetFruitType(held),
            x = held != null ? held.transform.position.x : 0
        };
        observation.next_fruit_type = GetFruitType(playerController.nextFruitObject);
        observation.drop_range = playerController.GetDropRange();
        observation.ai_move_speed = playerController.aiMoveSpeed;
        observation.fixed_delta_time = Time.fixedDeltaTime;
        observation.time_scale = Time.timeScale;
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
                angle = body.rotation, angular_velocity = body.angularVelocity
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
        public float ai_move_speed, fixed_delta_time, time_scale;
    }
    [Serializable]
    class StateFragment
    {
        public string message_type = "state_fragment";
        public string stream_id, data;
        public long state_id;
        public int index, count;
    }
}
