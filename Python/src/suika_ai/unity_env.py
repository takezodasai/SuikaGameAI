"""Numeric UDP bridge (protocol 2). No DQN imports or image processing required."""
from __future__ import annotations

import base64
import json
import math
import socket
import time
import uuid
import threading


def parse_state(value: dict) -> dict:
    """Validate a complete snapshot; malformed/partial states never enter training."""
    if not isinstance(value, dict) or value.get("protocol_version") != 2:
        raise ValueError("Expected protocol_version 2")
    for name in ("stream_id", "episode_id"):
        if not isinstance(value.get(name), str) or not value[name]:
            raise ValueError(f"Invalid {name}")
    if type(value.get("state_id")) is not int or value["state_id"] < 1:
        raise ValueError("Invalid state_id")
    if type(value.get("score")) is not int or type(value.get("game_over")) is not bool:
        raise ValueError("Invalid score/game_over")
    if not isinstance(value.get("reset_request_id"), str):
        raise ValueError("Missing reset_request_id")
    fruits = value.get("fruits")
    if not isinstance(fruits, list):
        raise ValueError("Missing fruits array")
    ids = set()
    for fruit in fruits:
        if not isinstance(fruit, dict) or type(fruit.get("id")) is not int or fruit["id"] <= 0:
            raise ValueError("Invalid fruit id")
        if fruit["id"] in ids:
            raise ValueError("Duplicate fruit id")
        ids.add(fruit["id"])
        _fruit_type(fruit.get("type"))
        for field in ("x", "y", "vx", "vy", "angle", "angular_velocity"):
            _number(fruit.get(field))
    held = value.get("current_fruit")
    if not isinstance(held, dict) or type(held.get("present")) is not bool:
        raise ValueError("Missing current_fruit")
    _fruit_type(held.get("type"), allow_missing=not held["present"])
    _number(held.get("x"))
    _fruit_type(value.get("next_fruit_type"))
    accounting = value.get("reward_accounting")
    if accounting is not None:
        validate_reward_accounting(accounting)
        if accounting["episode_score"] != value["score"] or accounting["episode_id"] != value["episode_id"]:
            raise ValueError("Reward ledger does not describe this snapshot")
    previous = value.get("previous_episode_reward_accounting")
    if previous is not None:
        if not isinstance(previous, dict):
            raise ValueError("Invalid previous episode ledger")
        if previous.get("present", True):
            validate_reward_accounting(previous)
    return value


def validate_reward_accounting(value):
    """Disjoint time intervals; the between-step amount is never added to step reward."""
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("conserved") is not True:
        raise ValueError("Invalid reward accounting")
    if not isinstance(value.get("episode_id"), str) or not value["episode_id"]:
        raise ValueError("Reward episode missing")
    for key in ("episode_start_score", "episode_score", "step_reward_total", "between_steps_reward_total"):
        if type(value.get(key)) is not int:
            raise ValueError("Invalid reward total")
    for key in ("last_step", "last_between_steps", "open_interval"):
        interval = value.get(key)
        if interval is not None and not isinstance(interval, dict):
            raise ValueError("Invalid reward interval")
        if key != "open_interval" and (interval is None or interval.get("present", True) is False):
            continue
        if not isinstance(interval, dict) or interval.get("present", True) is not True or interval.get("phase") not in ("in_step", "between_steps"):
            raise ValueError("Missing reward interval")
        for field in ("score_before", "score_after", "reward", "action_id"):
            if type(interval.get(field)) is not int:
                raise ValueError("Invalid reward interval value")
        if interval["reward"] != interval["score_after"] - interval["score_before"]:
            raise ValueError("Reward interval double count or omission")
        if (interval["phase"] == "between_steps") != (interval["action_id"] == 0):
            raise ValueError("Reward attribution inconsistent")
        for prefix in ("game_time", "fixed_time"):
            start, end = interval.get(prefix+"_start"), interval.get(prefix+"_end")
            _number(start); _number(end)
            if end < start:
                raise ValueError("Reversed reward interval")
    expected = (value["episode_start_score"] + value["step_reward_total"]
                + value["between_steps_reward_total"] + value["open_interval"]["reward"])
    if expected != value["episode_score"] or value["open_interval"]["score_after"] != value["episode_score"]:
        raise ValueError("Reward totals do not conserve episode score")
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Non-finite or missing physical value")


def _fruit_type(value, allow_missing=False):
    if type(value) is not int or not ((allow_missing and value == -1) or 0 <= value <= 10):
        raise ValueError("Unknown fruit type")


class UnityEnv:
    """One client per Unity instance; do not run main.py on the same receive port.

    Positions: Unity world units, +X right/+Y up; velocities: units/s;
    angle: degrees about +Z, angular_velocity: degrees/s (positive CCW).
    reset(timeout) retries one request id until an acknowledged fresh episode arrives.
    A new Play session requires a new UnityEnv (different stream_id).
    """

    def __init__(self, server=("127.0.0.1", 7773), local=("127.0.0.1", 7889)):
        self.server = server
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(local)
        except BaseException:
            self.socket.close()
            raise
        self.stream_id = None
        self.last_state_id = 0
        self.last_state = None
        self._parts = {}
        self._operation_lock = threading.Lock()
        self._pending_step = None
        self._action_id = 0
        self._action_episode = None
        self._send({"command": "observe"})

    def _send(self, message):
        self.socket.sendto(json.dumps(message).encode("utf-8"), self.server)

    def send_action(self, action: int):
        if self._pending_step is not None or self._operation_lock.locked():
            raise RuntimeError("An operation is pending; reset before mixing legacy actions")
        if type(action) is not int or not 0 <= action <= 5:
            raise ValueError("action must be 0..5")
        self._send({"action": action})

    def _decode(self, packet):
        value = json.loads(packet)
        if not isinstance(value, dict):
            raise ValueError("Expected object")
        if value.get("message_type") != "state_fragment":
            return value
        key = (value["stream_id"], value["state_id"])
        count, index = value["count"], value["index"]
        if type(count) is not int or type(index) is not int or not 0 <= index < count <= 4096:
            raise ValueError("Invalid fragment")
        now = time.monotonic()
        self._parts = {k: v for k, v in self._parts.items() if now - v[0] < 2}
        if key not in self._parts:
            if len(self._parts) >= 8:
                self._parts.pop(next(iter(self._parts)))
            self._parts[key] = (now, count, {})
        _, expected, chunks = self._parts[key]
        if expected != count:
            raise ValueError("Conflicting fragments")
        chunks[index] = base64.b64decode(value["data"], validate=True)
        if len(chunks) != count:
            return None
        del self._parts[key]
        result = json.loads(b"".join(chunks[i] for i in range(count)))
        if not isinstance(result, dict):
            raise ValueError("Fragment payload must be a state object")
        if (result.get("stream_id"), result.get("state_id")) != key:
            raise ValueError("Fragment identity mismatch")
        return result

    def receive_state(self, timeout=3.0, *, step_action_id=None, step_episode_id=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                packet, sender = self.socket.recvfrom(65535)
            except socket.timeout as error:
                raise TimeoutError("No fresh Unity state; check Play/ports/Console") from error
            if sender[0] != socket.gethostbyname(self.server[0]):
                continue
            try:
                state = self._decode(packet)
                if state is None:
                    continue
                state = parse_state(state)
            except (ValueError, TypeError, KeyError, UnicodeError):
                continue
            if self.stream_id is None:
                self.stream_id = state["stream_id"]
            result = state.get("step_result")
            expected_result = (step_action_id is not None and isinstance(result, dict)
                               and result.get("action_id") == step_action_id
                               and (step_episode_id is None or state["episode_id"] == step_episode_id))
            if state["stream_id"] != self.stream_id:
                continue
            if state["state_id"] <= self.last_state_id and not expected_result:
                continue
            if state["state_id"] > self.last_state_id:
                self.last_state_id = state["state_id"]
                self.last_state = state
            return state
        raise TimeoutError("No complete fresh Unity state")

    def reset(self, timeout=5.0):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Another reset/step is in progress")
        try:
            state = self._reset(timeout)
            self._action_id = 0
            self._action_episode = state["episode_id"]
            self._pending_step = None
            return state
        finally:
            self._operation_lock.release()

    def _reset(self, timeout):
        # Obtain a current baseline before addressing a reset to this episode.
        deadline = time.monotonic() + timeout
        self._send({"command": "observe"})
        baseline = self.receive_state(timeout)
        request_id = uuid.uuid4().hex
        command = {"command": "reset", "request_id": request_id,
                   "episode_id": baseline["episode_id"]}
        while time.monotonic() < deadline:
            self._send(command)
            try:
                state = self.receive_state(min(0.3, max(0.001, deadline - time.monotonic())))
            except TimeoutError:
                continue
            if (state["reset_request_id"] == request_id
                    and state["episode_id"] != baseline["episode_id"]):
                if state["game_over"] or state["score"] != 0 or state["fruits"] or not state["current_fruit"]["present"]:
                    raise RuntimeError("Reset acknowledged but initial state is invalid")
                return state
        raise TimeoutError("Unity did not acknowledge reset")

    def step(self, x: float, timeout=None):
        """Drop once at normalized X and observe after >=0.5 simulated seconds.

        Motion runs at the Inspector speed in fixed game-time updates while the board
        keeps simulating. The 0.5s window starts after dropping. The returned state is the cached completion
        snapshot, not an arbitrary later observation. Timeout means outcome unknown:
        reset before another action. Operations on one client are strictly sequential.
        """
        if type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1:
            raise ValueError("x must be a finite number in [0.0, 1.0]")
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be finite and positive")
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Another reset/step is in progress")
        try:
            if self._pending_step is not None:
                raise RuntimeError("Previous step outcome is unknown; call reset()")
            if self._action_episode is None:
                raise RuntimeError("Call reset() before step()")
            initial_timeout = 5.0 if timeout is None else timeout
            deadline = time.monotonic() + initial_timeout
            baseline = self.receive_state(initial_timeout)
            if baseline["episode_id"] != self._action_episode:
                raise RuntimeError("Episode changed outside this client; call reset()")
            if baseline["game_over"]:
                return baseline, 0, True, {"drop_success": False, "status": "game_over", "requested_x": x}
            if timeout is None:
                deadline = time.monotonic() + self._movement_timeout(baseline, x)
            action_id = self._action_id + 1
            command = dict(command="step", stream_id=baseline["stream_id"],
                           episode_id=baseline["episode_id"], action_id=action_id, x=float(x))
            self._pending_step = command
            retry_at = 0
            while time.monotonic() < deadline:
                if time.monotonic() >= retry_at:
                    self._send(command)
                    retry_at = time.monotonic() + 0.25
                try:
                    state = self.receive_state(min(0.25, max(0.001, deadline - time.monotonic())),
                                               step_action_id=action_id,
                                               step_episode_id=baseline["episode_id"])
                except TimeoutError:
                    continue
                info = state.get("step_result")
                if not isinstance(info, dict) or info.get("action_id") != action_id:
                    if state["episode_id"] != baseline["episode_id"]:
                        raise RuntimeError("Episode changed during step; call reset()")
                    continue
                dropped = info.get("drop_success")
                if info.get("status") != "completed" or (dropped is not True and not (dropped is False and state["game_over"])):
                    raise RuntimeError(f"Unity rejected step: {info.get('status')}; call reset()")
                if state["episode_id"] != baseline["episode_id"]:
                    raise RuntimeError("Step reply has wrong episode; call reset()")
                for name in ("requested_x", "applied_x", "applied_normalized_x", "min_x", "max_x"):
                    _number(info.get(name))
                if (abs(info["requested_x"] - x) > 1e-6
                        or (dropped and not info["min_x"] <= info["applied_x"] <= info["max_x"])
                        or (dropped and abs(info["applied_normalized_x"] - x) > 1e-5)
                        or type(info.get("reward")) is not int
                        or type(info.get("score_before")) is not int
                        or info["reward"] != state["score"] - info["score_before"]
                        or type(info.get("dropped_fruit_id")) is not int
                        or (dropped and info["dropped_fruit_id"] <= 0)
                        or type(info.get("physics_steps")) is not int
                        or (info["physics_steps"] < 1 and not state["game_over"])):
                    raise RuntimeError("Inconsistent step reply; call reset()")
                self._action_id = action_id
                self._pending_step = None
                return state, info["reward"], state["game_over"], dict(info, reward_accounting=state.get("reward_accounting"))
            raise TimeoutError("Step outcome unknown; call reset() before another step")
        finally:
            self._operation_lock.release()

    @staticmethod
    def _movement_timeout(state, x):
        """Wall-clock allowance: game-time movement + post-drop window + network margin."""
        limits = state.get("drop_range")
        if not isinstance(limits, dict) or not limits.get("valid"):
            return 5.0
        speed = state.get("ai_move_speed", 2.5)
        scale = state.get("time_scale", 1.0)
        _number(speed)
        _number(scale)
        if speed <= 0 or scale <= 0:
            raise RuntimeError("Unity movement speed/time scale must be positive")
        target = limits["min_x"] + x * (limits["max_x"] - limits["min_x"])
        distance = abs(target - state["current_fruit"]["x"])
        wait = state.get("drop_cooldown_remaining", 0.0)
        _number(wait)
        if wait < 0:
            raise ValueError("drop_cooldown_remaining must be nonnegative")
        return max(5.0, (max(distance / speed, wait) + 0.5 + 2 * state.get("fixed_delta_time", 0.02)) / scale + 3.0)

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
