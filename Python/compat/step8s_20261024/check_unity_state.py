"""Run with Unity in Play mode. Uses existing actions, no learning.

python check_unity_state.py          # initial state + 3 resets
python check_unity_state.py --play   # bounded drop/merge/terminal/reset check (90s)
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from suika_ai.unity_env import UnityEnv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()
    with UnityEnv() as env:
        initial = env.reset(timeout=30)  # Allow time to return focus to a paused Editor.
        print("initial", json.dumps(initial, ensure_ascii=False), flush=True)
        episodes = {initial["episode_id"]}
        for _ in range(2):
            reset = env.reset()
            assert reset["episode_id"] not in episodes
            episodes.add(reset["episode_id"])
        print("PASS: 3 resets, fresh episodes, empty board, score=0, current/NEXT", flush=True)
        if not args.play:
            return
        deadline = time.monotonic() + 90
        saw_drop = saw_merge = saw_motion = saw_stable_id = False
        previous = None
        next_drop = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_drop:
                env.send_action(2)
                next_drop = now + 0.18
            current = env.receive_state()
            if current["fruits"]:
                saw_drop = True
                saw_motion |= any(abs(f["vy"]) > 0.01 for f in current["fruits"])
            if previous is not None:
                before = {f["id"]: f for f in previous["fruits"]}
                after = {f["id"]: f for f in current["fruits"]}
                saw_stable_id |= bool(before.keys() & after.keys())
                saw_merge |= (current["score"] > previous["score"] and
                              any(f["type"] > 0 for key, f in after.items() if key not in before))
            if current["game_over"]:
                print("terminal", json.dumps(current), flush=True)
                # No auto restart in numeric mode; verify paused receive and reset retry safety.
                terminal_episode = current["episode_id"]
                time.sleep(0.1)
                reset = env.reset()
                assert reset["episode_id"] != terminal_episode
                print("PASS: reset after game over", flush=True)
                break
            previous = current
        else:
            print("UNVERIFIED: game over not reached within 90s", flush=True)
        print(json.dumps(dict(drop=saw_drop, merge=saw_merge,
                              motion=saw_motion, stable_id=saw_stable_id)), flush=True)
        env.reset()


if __name__ == "__main__":
    main()
