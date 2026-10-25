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

    def __init__(self, server=("127.0.0.1", 7773), local=("127.0.0.1", 7889), *, expected_game_id=None):
        self.expected_game_id = expected_game_id
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
            if self.expected_game_id is not None and state.get("game_id") != self.expected_game_id:
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

    def get_environment(self, timeout=5.0):
        """Read-only metadata request. No action ID, Reset, or RNG change."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self._send({"command":"environment"})
            try:
                state=self.receive_state(min(.5,max(.001,deadline-time.monotonic())))
            except TimeoutError:
                continue
            metadata=state.get("environment") or {}
            # JsonUtility serializes a null nested class as a default-valued object.
            # schema_version alone is therefore not proof of an environment reply.
            if (metadata.get("schema_version")==1 and metadata.get("unity_version")
                    and metadata.get("build_guid") and metadata.get("fixed_delta_time",0)>0
                    and metadata.get("physics_profiles") and metadata.get("boundaries")):
                return metadata
        raise TimeoutError("No training metadata; rebuild STEP6 Player with the current Unity source")

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

    def plan_step(self, settings=None, timeout=None):
        """Choose and execute one action from the same live board in Unity.

        settings overrides the Inspector configuration for this decision only.
        A timeout leaves the outcome unknown; reset before issuing another action.
        """
        if settings is not None:
            validate_planning_settings(settings)
        return self.step(0.5, timeout, _planning=settings if settings is not None else {})

    def step(self, x: float, timeout=None, *, _planning=None, _path_probe=None):
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
                deadline = time.monotonic() + (self._movement_timeout(baseline, x) if _planning is None else
                    max(self._movement_timeout(baseline, 0), self._movement_timeout(baseline, 1))
                    + 30 + (_planning.get("post_drop_steps", 25) * baseline.get("fixed_delta_time", .02)) / baseline.get("time_scale", 1))
            action_id = self._action_id + 1
            command = dict(command="step", stream_id=baseline["stream_id"],
                           episode_id=baseline["episode_id"], action_id=action_id, x=float(x))
            if _planning is not None:
                command["command"] = "plan_step"
                if _planning:
                    command["planning_settings"] = dict(PLANNING_DEFAULTS, **_planning)
            if _path_probe is not None:command.update(_path_probe)
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
                if info.get("status") == "game_over" and state["game_over"]:
                    # GO may occur after the baseline but before the command is accepted.
                    self._pending_step = None
                    return state, 0, True, dict(info, reward_accounting=state.get("reward_accounting"))
                planning = state.get("planning") if _planning is not None else None
                if _planning is not None:
                    if not isinstance(planning, dict) or planning.get("selected_index", -1) < 0:
                        raise RuntimeError(f"Unity planning failed: {info.get('status')}; call reset()")
                    candidates = planning.get("candidates", [])
                    selected = planning["selected_index"]
                    if type(selected) is not int or not 0 <= selected < len(candidates):
                        raise RuntimeError("Invalid selected candidate; call reset()")
                    x = planning["selected_x"]
                    _number(x)
                    if not 0 <= x <= 1 or candidates[selected].get("x") != x:
                        raise RuntimeError("Invalid planning position; call reset()")
                    for candidate in candidates:
                        if "selection_score" not in candidate:
                            candidate["selection_score"] = json.loads(candidate.get("selection_score_json", "null"))
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
                return state, info["reward"], state["game_over"], dict(info, reward_accounting=state.get("reward_accounting"), **({"path_comparison":state.get("path_comparison")} if _path_probe is not None else {}), **({"planning": planning} if planning is not None else {}))
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

    def request_presentation(self, kind, enabled, revision):
        """Send desired state without receiving: safe beside the sole collector receiver.

        Confirmation is state[kind+'_revision']; caller retries the same revision until ack.
        Independent of episode/action IDs and survives reset. Requires a fresh known stream.
        """
        if kind not in ("audio", "video") or type(enabled) is not bool or type(revision) is not int or not 0 < revision < 2**63:
            raise ValueError("Invalid presentation control")
        state = self.last_state
        if not state or not state.get("game_id"):
            return False
        self._send(dict(command="presentation", stream_id=state["stream_id"], game_id=state["game_id"],
            control_kind=kind, enabled=enabled, control_revision=revision))
        return True

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


PLANNING_DEFAULTS = dict(candidate_policy="grid", candidate_count=5, post_drop_steps=25, height_bins=9,
    score_scale=55.0, weight_height=0.0, weight_danger=0.0, weight_roughness=.2,
    danger_band_fraction=.15, uncontacted_risk_weight=.5, planning_budget_ms=0.0, ai_mode="heuristic", value_model_path="", search_leaf="reward", inter_step_wait_ticks=0, mcts_iterations=32, mcts_max_depth=3,
    pair_coverage_iterations=0, action_order_policy="index", expansion_policy="legacy", tree_policy="chance", rollout_policy="random", rollout_random_probability=.5, mcts_common_chance=False, mcts_seed=8191, mcts_exploration=2**.5, mcts_point_scale=55., two_step_exhaustive_reward=False, execution_mode="sync", frame_tick_slicing=False, frame_budget_ms=6., frame_timeout_seconds=24., frame_lead_ticks=150, frame_max_attempts=2)
PLANNING_DEFAULTS.update(mcts_budget_mode="fixed",mcts_time_limit_seconds=5.,mcts_max_iterations=256,adaptive_initial_iterations=32,adaptive_min_action_visits=4,adaptive_uncertainty_multiplier=1.,adaptive_value_tolerance=3.,adaptive_max_terminal_rate=.1,mcts_widening=False,widening_max_candidates=9,widening_after_visits=10,widening_min_action_visits=1,widening_min_spacing=.03125)



def validate_planning_settings(settings):
    if not isinstance(settings, dict) or set(settings) - PLANNING_DEFAULTS.keys():
        raise ValueError("Unknown planning setting")
    values = dict(PLANNING_DEFAULTS, **settings)
    if values['mcts_budget_mode'] not in ('fixed','time','adaptive') or type(values['mcts_widening']) is not bool:raise ValueError('Invalid adaptive mode')
    for name,lo,hi in [('mcts_max_iterations',2,4096),('adaptive_initial_iterations',2,4096),('adaptive_min_action_visits',1,4096),('widening_max_candidates',5,31),('widening_after_visits',1,4096),('widening_min_action_visits',1,4096)]:
        if type(values[name]) is not int or not lo<=values[name]<=hi:raise ValueError('Invalid '+name)
    for name,lo,hi in [('mcts_time_limit_seconds',.000001,3600),('adaptive_uncertainty_multiplier',0,float('inf')),('adaptive_value_tolerance',0,float('inf')),('adaptive_max_terminal_rate',0,1),('widening_min_spacing',.000001,.125)]:
        _number(values[name])
        if not lo<=values[name]<=hi:raise ValueError('Invalid '+name)
    flexible=values['mcts_budget_mode']!='fixed'
    if flexible or values['mcts_widening']:
        if values['ai_mode']!='mcts' or values['execution_mode']!='sync' or values['frame_tick_slicing'] or values['candidate_policy']!='grid' or values['tree_policy']!='chance' or values['rollout_policy']!='random' or values['expansion_policy']!='legacy' or values['action_order_policy']!='index' or values['pair_coverage_iterations']!=0 or values['mcts_common_chance'] or values['planning_budget_ms']!=0:raise ValueError('Adaptive prototype requires sync legacy chance/grid/random MCTS')
    if flexible and (values['mcts_max_iterations']<values['candidate_count'] or not values['candidate_count']<=values['adaptive_initial_iterations']<=values['mcts_max_iterations']):raise ValueError('Invalid adaptive stage/cap')
    if values['mcts_widening'] and values['candidate_count']!=5:raise ValueError('Widening starts with five anchors')
    if type(values["pair_coverage_iterations"]) is not int or not 0<=values["pair_coverage_iterations"]<=25:raise ValueError("Invalid pair coverage budget")
    if values["pair_coverage_iterations"] and (type(values["mcts_iterations"]) is not int or values["pair_coverage_iterations"]>values["mcts_iterations"]):raise ValueError("Coverage exceeds search budget")
    if values["pair_coverage_iterations"] and (values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"] or values["candidate_policy"]!="grid" or values["candidate_count"]!=5 or values["mcts_max_depth"]<2 or values["tree_policy"]!="chance" or values["rollout_policy"]!="random" or values["action_order_policy"]!="index" or values["expansion_policy"]!="legacy"):raise ValueError("Pair coverage requires sync five-grid legacy chance/random MCTS")
    if values["action_order_policy"] not in ("index","shuffle"):raise ValueError("Invalid action order policy")
    if values["action_order_policy"]!="index" and (values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"] or values["tree_policy"]!="chance" or values["candidate_policy"]!="grid" or values["rollout_policy"]!="random" or values["expansion_policy"]!="legacy"):raise ValueError("Shuffle requires sync chance grid MCTS with legacy expansion and random rollout")
    if values["expansion_policy"] not in ("legacy","chance_decision"):raise ValueError("Invalid expansion policy")
    if values["expansion_policy"]!="legacy" and (values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"] or values["tree_policy"]!="chance" or values["candidate_policy"]!="grid" or values["rollout_policy"]!="random"):raise ValueError("Chance-decision requires sync chance-tree grid MCTS with random rollout")
    if values["tree_policy"] not in ("chance","public_open_loop"):raise ValueError("Invalid tree policy")
    if values["tree_policy"]!="chance" and (values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"] or values["candidate_policy"]!="grid" or values["rollout_policy"]!="random"):raise ValueError("Open-loop requires sync grid MCTS with random rollout")
    if values["rollout_policy"] not in ("random","guided"):raise ValueError("Invalid rollout policy")
    _number(values["rollout_random_probability"])
    if not 0<=values["rollout_random_probability"]<=1 or type(values["mcts_common_chance"]) is not bool:raise ValueError("Invalid rollout probability/chance flag")
    if (values["rollout_policy"]!="random" or values["mcts_common_chance"]) and (values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"]):raise ValueError("Guided rollout requires synchronous MCTS")
    if values["candidate_policy"] not in ("grid","board-five","coarse-root"):raise ValueError("Unknown candidate policy")
    if values["candidate_policy"]=="coarse-root" and (values["candidate_count"]!=7 or values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"] or values["tree_policy"]!="chance" or values["rollout_policy"]!="random" or values["expansion_policy"]!="legacy" or values["action_order_policy"]!="index"):raise ValueError("Coarse-root requires sync legacy grid-future MCTS with seven root actions")
    if values["candidate_policy"]=="board-five" and (values["candidate_count"]!=5 or values["ai_mode"]!="mcts" or values["execution_mode"]!="sync" or values["frame_tick_slicing"]):
        raise ValueError("Board-five requires synchronous MCTS with five candidates")
    for name, low, high in (("candidate_count", 2, 31), ("post_drop_steps", 1, 150), ("height_bins", 2, 128)):
        if type(values[name]) is not int or not low <= values[name] <= high:
            raise ValueError(f"Invalid {name}")
    if values["ai_mode"] not in ("heuristic","value","two_step","mcts","mcts_value") or not isinstance(values["value_model_path"],str):
        raise ValueError("Invalid AI mode/model path")
    if values["search_leaf"] not in ("reward","heuristic","value") or type(values["inter_step_wait_ticks"]) is not int or not 0<=values["inter_step_wait_ticks"]<=500:
        raise ValueError("Invalid path leaf/wait")
    for name,low,high in (("mcts_iterations",2,256),("mcts_max_depth",1,8),("mcts_seed",0,2147483647)):
        if type(values[name]) is not int or not low<=values[name]<=high:raise ValueError(f"Invalid {name}")
    if values["execution_mode"] not in ("sync","frames","frames_adaptive") or (values["execution_mode"]!="sync" and values["ai_mode"] not in ("mcts","mcts_value")):
        raise ValueError("Frame execution requires MCTS")
    for name,low,high in (("frame_lead_ticks",10,500),("frame_max_attempts",1,3)):
        if type(values[name]) is not int or not low<=values[name]<=high:raise ValueError(f"Invalid {name}")
    for name,low,high in (("frame_budget_ms",1,30),("frame_timeout_seconds",1,25)):
        _number(values[name])
        if not low<=values[name]<=high:raise ValueError(f"Invalid {name}")
    if type(values["frame_tick_slicing"]) is not bool:raise ValueError("Invalid tick slicing flag")
    if type(values["two_step_exhaustive_reward"]) is not bool:raise ValueError("Invalid exhaustive flag")
    if values["ai_mode"] in ("mcts","mcts_value") and values["mcts_iterations"]<values["candidate_count"]:raise ValueError("MCTS must cover every root candidate")
    _number(values["mcts_point_scale"])
    if values["mcts_point_scale"]<=0:raise ValueError("MCTS point scale must be positive")
    for name in PLANNING_DEFAULTS.keys() - {"mcts_budget_mode", "mcts_widening", "pair_coverage_iterations", "action_order_policy", "expansion_policy", "tree_policy", "rollout_policy", "mcts_common_chance", "candidate_policy", "candidate_count", "post_drop_steps", "height_bins", "ai_mode", "value_model_path", "search_leaf", "inter_step_wait_ticks", "mcts_iterations", "mcts_max_depth", "mcts_seed", "two_step_exhaustive_reward", "execution_mode", "frame_tick_slicing", "frame_lead_ticks", "frame_max_attempts"}:
        _number(values[name])
        if values[name] < 0:
            raise ValueError(f"Negative {name}")
    if values["score_scale"] <= 0 or not 0 < values["danger_band_fraction"] <= 1 or values["uncontacted_risk_weight"] > 1:
        raise ValueError("Invalid planning normalization")
    values["weight_height"] = values["weight_danger"] = 0.0  # legacy accepted, never re-enabled
    return values
