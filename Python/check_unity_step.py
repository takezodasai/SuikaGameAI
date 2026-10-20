"""Bounded live STEP 3 smoke test; run while Unity is in Play (keep it foreground)."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from suika_ai.unity_env import UnityEnv


def main():
    with UnityEnv() as env:
        env.reset(timeout=30)
        # Duplicate each step datagram to exercise production at-most-once execution.
        original_send = env._send
        def duplicate_step(message):
            original_send(message)
            if message.get("command") == "step":
                original_send(message)
        env._send = duplicate_step
        ranges = {}
        for i in range(9):
            before = env.reset()
            normalized = (0, 0.5, 1)[i % 3]
            limits = before["drop_range"]
            assert limits["valid"], limits
            result, reward, done, info = env.step(normalized)
            assert not done and info["drop_success"]
            assert len(result["fruits"]) == 1, "Duplicate/absent drop on empty board"
            fruit = result["fruits"][0]
            assert fruit["id"] == info["dropped_fruit_id"]
            assert fruit["type"] == before["current_fruit"]["type"]
            expected = limits["min_x"] + normalized * (limits["max_x"] - limits["min_x"])
            assert abs(info["applied_x"] - expected) < 1e-5
            assert abs(fruit["x"] - expected) < 0.03, "Fruit moved horizontally on empty board"
            assert info["applied_x"] - limits["fruit_left_extent"] >= limits["left_wall_inner"]
            assert info["applied_x"] + limits["fruit_right_extent"] <= limits["right_wall_inner"]
            ranges[fruit["type"]] = limits
            print(json.dumps(dict(x=normalized, fruit_type=fruit["type"],
                                  applied=info["applied_x"], min=info["min_x"], max=info["max_x"],
                                  physics_steps=info["physics_steps"], duplicate_drop=False)), flush=True)
        env.reset()
        rng = random.Random(3)
        score = 0
        merged = False
        # Center drops promote merges, followed by bounded randomized positions.
        for i in range(28):
            result, reward, done, info = env.step(0.5 if i < 16 else rng.random())
            assert result["score"] - info["score_before"] == reward
            score = result["score"]
            merged |= reward > 0
            if done:
                print("terminal: reset after step", flush=True)
                env.reset()
                break
        print(json.dumps(dict(status="PASS", endpoint_trials=9, sizes=list(ranges),
                              score=score, merge=merged, randomized_steps=True)), flush=True)
        env.reset()


if __name__ == "__main__":
    main()
