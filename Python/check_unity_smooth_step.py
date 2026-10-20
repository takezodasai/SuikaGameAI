"""Bounded live smooth-step check; Unity must be in Play and foreground."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from suika_ai.unity_env import UnityEnv


def main():
    with UnityEnv() as env:
        env.reset(timeout=30)
        original_receive = env.receive_state
        original_send = env._send
        samples = []
        def observe(*args, **kwargs):
            state = original_receive(*args, **kwargs)
            if state.get("step_progress"):
                samples.append(state)
            return state
        def duplicate(message):
            original_send(message)
            if message.get("command") == "step":
                original_send(message)
        env.receive_state = observe
        env._send = duplicate
        board_moves = False
        directions = set()
        for x in (0, 1, 0, 0.01, 0.02, 0.8):
            samples.clear()
            state, reward, done, info = env.step(x)
            assert not done, "Unexpected terminal state in short smoke test"
            assert info["drop_success"] and abs(info["applied_normalized_x"] - x) < 1e-5
            assert info["physics_steps"] >= 25
            assert abs(info["current_x"] - info["target_x"]) < 1e-5
            assert info["movement_steps"] <= info["planned_movement_steps"] + 1
            moving = [s for s in samples if s["step_progress"]["status"] == "moving"
                      and s["step_progress"]["action_id"] == info["action_id"]]
            sign = 1 if info["target_x"] > info["movement_start_x"] else -1
            if len(moving) > 1:
                directions.add(sign)
            for sample in moving:
                p = sample["step_progress"]
                assert not p["drop_success"]
                assert p["min_x"] - 1e-5 <= sample["current_fruit"]["x"] <= p["max_x"] + 1e-5
            for first, second in zip(moving, moving[1:]):
                a, b = first["step_progress"], second["step_progress"]
                dx = b["current_x"] - a["current_x"]
                dt = b["movement_seconds"] - a["movement_seconds"]
                assert sign * dx >= -1e-5
                assert abs(dx) <= info["movement_speed"] * dt + 0.0001, "Movement jumped"
                old = {f["id"]: f for f in first["fruits"]}
                board_moves |= any(f["id"] in old and abs(f["y"] - old[f["id"]]["y"]) > 0.001
                                   for f in second["fruits"])
            print(json.dumps(dict(x=x, start=info["movement_start_x"], applied=info["applied_x"],
                                  speed=info["movement_speed"], move_ticks=info["movement_steps"],
                                  move_seconds=info["movement_seconds"], post_drop_ticks=info["physics_steps"],
                                  moving_samples=len(moving))), flush=True)
        assert directions == {-1, 1}, "No intermediate observations in both directions"
        assert board_moves, "Did not observe the board simulating during movement"
        print("PASS: bidirectional/near movement, arrival then drop, board physics, duplicate commands", flush=True)

        # Interrupt a raw in-flight command using the normal reset protocol.
        before = env.reset()
        command = dict(command="step", stream_id=before["stream_id"], episode_id=before["episode_id"],
                       action_id=1, x=1.0)
        env._send(command)
        for _ in range(20):
            observed = env.receive_state()
            if (observed.get("step_progress") or {}).get("status") == "moving":
                break
        else:
            raise AssertionError("Could not observe in-flight movement")
        after = env.reset()
        assert after["episode_id"] != before["episode_id"] and not after["fruits"]
        env._send(command)  # Delayed packet from cancelled episode cannot move/drop.
        observed = env.receive_state()
        assert observed["episode_id"] == after["episode_id"] and not observed["fruits"]
        env.step(0.5)
        env.reset()
        print("PASS: reset during movement, stale retry rejected, new step after reset", flush=True)


if __name__ == "__main__":
    main()
