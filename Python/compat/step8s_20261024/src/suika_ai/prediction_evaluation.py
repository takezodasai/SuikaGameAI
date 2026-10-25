"""STEP 4-B offline metrics. No policy, search, or optional scientific dependencies."""
from __future__ import annotations

from collections import Counter
import math
import re
import statistics

ERROR_FIELDS = ("position", "velocity", "angle", "angular_velocity")
MERGE_EVENT = re.compile(r"^(\d+):merge:(m\(.+\)):(\d+)->(-?\d+)$")


def distribution(values):
    """Linear-interpolated empirical percentiles; empty populations stay undefined."""
    values = sorted(values)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Non-finite metric")
    def percentile(q):
        at = (len(values) - 1) * q
        lo, hi = math.floor(at), math.ceil(at)
        return values[lo] + (values[hi] - values[lo]) * (at - lo)
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None,
                "p95": None, "p99": None, "histogram": []}
    # Same numeric bins across runs; unit depends on the named metric.
    limits = (0, 1e-6, 1e-3, 1e-2, 0.1, 1, 10, 100)
    counts = [0] * (len(limits) + 1)
    for value in values:
        counts[next((i for i, edge in enumerate(limits) if value <= edge), len(limits))] += 1
    return {"n": len(values), "mean": statistics.fmean(values), "median": percentile(.5),
            "min": values[0], "max": values[-1], "p95": percentile(.95), "p99": percentile(.99),
            "histogram": [{"lower_exclusive": limits[i-1] if i else None,
                           "upper_inclusive": edge, "count": counts[i]}
                          for i, edge in enumerate((*limits, None))]}


def rate(successes, total):
    """Wilson 95% interval is descriptive; trials in one episode are NOT independent."""
    if not total:
        return {"successes": successes, "n": 0, "rate": None, "wilson95": None}
    p, z = successes / total, 1.959963984540054
    base = 1 + z*z/total
    center = (p + z*z/(2*total)) / base
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / base
    return {"successes": successes, "n": total, "rate": p,
            "wilson95": [max(0, center-half), min(1, center+half)]}


def merge_events(history):
    result = []
    for text in history:
        match = MERGE_EVENT.fullmatch(text)
        if match:
            tick, lineage, source, target = match.groups()
            if "untracked" in lineage:
                raise ValueError("Untracked merge parent")
            result.append({"tick": int(tick), "lineage": lineage,
                           "from": int(source), "to": int(target)})
        elif ":merge:" in text:
            raise ValueError("Unknown merge event format")
    return result


def merge_signature(events, parents=False):
    return Counter((e["lineage"], e["from"], e["to"]) if parents else (e["from"], e["to"])
                   for e in events)


def compare_fruits(predicted_frame, actual_frame):
    """Use inherited/merge-lineage aliases only; never guess correspondence by distance."""
    def board(frame):
        fruits = [f for f in frame["fruits"] if not f["preview"] and not f["merging"]]
        ids = [f["id"] for f in fruits]
        if len(set(ids)) != len(ids) or any("untracked" in i for i in ids):
            raise ValueError("Duplicate or untracked diagnostic alias")
        return {f["id"]: f for f in fruits}
    predicted, actual = board(predicted_frame), board(actual_frame)
    pairs, mismatches = [], []
    for alias in sorted(predicted.keys() & actual.keys()):
        p, a = predicted[alias], actual[alias]
        if p["type"] != a["type"]:
            mismatches.append(alias)
            continue
        error = {"id": alias, "type": a["type"],
                 "position": math.hypot(p["position"]["x"]-a["position"]["x"], p["position"]["y"]-a["position"]["y"]),
                 "velocity": math.hypot(p["velocity"]["x"]-a["velocity"]["x"], p["velocity"]["y"]-a["velocity"]["y"]),
                 "angle": abs((p["angle"]-a["angle"]+180) % 360-180),
                 "angular_velocity": abs(p["angular_velocity"]-a["angular_velocity"])}
        if not all(math.isfinite(error[k]) for k in ERROR_FIELDS):
            raise ValueError("Non-finite fruit error")
        pairs.append(error)
    missing, extra = sorted(actual.keys()-predicted.keys()), sorted(predicted.keys()-actual.keys())
    complete = not (missing or extra or mismatches)
    return {"mapping": "lineage_exact" if complete else "partial_lineage_only",
            "complete": complete, "matched": len(pairs), "actual_count": len(actual),
            "predicted_count": len(predicted), "missing_predicted_aliases": missing,
            "extra_predicted_aliases": extra, "type_mismatch_aliases": mismatches,
            "types_count_match": Counter(f["type"] for f in predicted.values()) == Counter(f["type"] for f in actual.values()),
            "per_fruit": pairs}


def initial_conditions(prediction, diagnostics, near_margin):
    """Operational labels, not claims that a rare event will occur."""
    initial = diagnostics["initial_actual"]
    board = [f for f in initial["fruits"] if not f["preview"] and not f["merging"]]
    touching = sum(bool(f["contacts"]) for f in board)
    board_ids = {f["id"] for f in board}
    fruit_contacts = sum(c["other"] in board_ids for f in board for c in f["contacts"])
    max_y = max((f["position"]["y"] for f in board), default=None)
    height = prediction["game_over_height"]
    labels = []
    if len(board) <= 1: labels.append("sparse")
    if board and not touching: labels.append("free_fall")
    if fruit_contacts: labels.append("fruit_contact")
    if len(board) >= 6 and touching >= 3: labels.append("dense_contact")
    if max_y is not None and max_y >= height-near_margin: labels.append("near_game_over")
    if not labels: labels.append("other")
    return {"labels": labels, "board_count": len(board), "touching_fruit_count": touching,
            "fruit_contact_entries": fruit_contacts, "max_center_y": max_y,
            "game_over_height": height, "near_over_margin": near_margin,
            "held": [f for f in initial["fruits"] if f["preview"]],
            "next_type": prediction["initial_next_fruit_type"], "score": initial["score"]}


def evaluate(state, near_margin=.5, requested_post_drop_steps=None):
    """Evaluate one completed compare_step. Reject unfair comparisons from denominators."""
    p, info = state["prediction"], state["step_result"]
    d = p.get("diagnostics")
    if not d or "final_actual" not in d:
        raise ValueError("STEP 4-B final diagnostics missing; refresh Unity scripts")
    reasons = []
    if not p["source_unchanged"]: reasons.append("source_changed")
    reference_matches = (p["reference_fruits"] == p["fruits"] and p["reference_score"] == p["score"]
                         and p["reference_game_over"] == p["game_over"])
    if not reference_matches: reasons.append("instrumentation_changed_prediction")
    if abs(p["fixed_delta_time"]-state["fixed_delta_time"]) > 1e-7: reasons.append("fixed_dt_mismatch")
    if p["movement_steps"] != info["movement_steps"]: reasons.append("movement_ticks_mismatch")
    if requested_post_drop_steps is not None and not state["game_over"] and p["post_drop_steps"] != requested_post_drop_steps:
        reasons.append("requested_horizon_mismatch")
    if d["truncated"]: reasons.append("trace_truncated")
    if p["physics_steps"] != state["actual_total_physics_steps"]: reasons.append("total_ticks_mismatch")
    if d["actual_ticks"] != d["predicted_ticks"]: reasons.append("trace_ticks_mismatch")
    if d["actual_ticks"] != state["actual_total_physics_steps"]: reasons.append("trace_completion_mismatch")
    if not state["game_over"] and p["post_drop_steps"] != info["physics_steps"]: reasons.append("post_drop_ticks_mismatch")
    if p["drop_success"] != info["drop_success"]: reasons.append("drop_status_mismatch")
    if info["drop_success"] and abs(p["applied_x"]-info["applied_x"]) > 1e-5: reasons.append("drop_position_mismatch")
    e0 = d["errors"][0]
    if (not e0["ids_types_match"] or not e0["score_match"] or not e0["game_over_match"]
            or any(e0[k] > threshold for k,threshold in {"position":1e-6,"velocity":1e-5,"angle":1e-4,"angular_velocity":1e-3,"mass":1e-6,"inertia":1e-6,"center_of_mass":1e-6}.items())):
        reasons.append("initial_public_state_mismatch")
    physical = compare_fruits(d["final_prediction"], d["final_actual"])
    actual_events, predicted_events = merge_events(d["actual_events"]), merge_events(d["predicted_events"])
    actual_cascade = any(e["lineage"].count("m(") > 1 for e in actual_events)
    predicted_cascade = any(e["lineage"].count("m(") > 1 for e in predicted_events)
    conditions = initial_conditions(p, d, near_margin)
    labels = conditions["labels"] + (["actual_merge"] if actual_events else ["actual_no_merge"])
    if actual_cascade: labels.append("actual_cascade")
    delta = p["reward"]-info["reward"]
    if p["score"]-conditions["score"] != p["reward"]: reasons.append("predicted_reward_inconsistent")
    if state["score"]-conditions["score"] != info["reward"]: reasons.append("actual_reward_inconsistent")
    return {"eligible": not reasons, "reference_matches_traced": reference_matches, "ineligible_reasons": reasons, "conditions": conditions, "labels": labels,
            "physical": physical,
            "trace_max": {k: max(e[k] for e in d["errors"]) for k in ERROR_FIELDS},
            "trace_identity_complete": all(e["ids_types_match"] for e in d["errors"]),
            "first_numeric_tick": d["first_numeric_tick"],
            "merge": {"actual": actual_events, "predicted": predicted_events,
                      "presence_match": bool(actual_events)==bool(predicted_events),
                      "types_count_match": merge_signature(actual_events)==merge_signature(predicted_events),
                      "lineage_match": merge_signature(actual_events,True)==merge_signature(predicted_events,True),
                      "count_match": len(actual_events)==len(predicted_events),
                      "actual_cascade": actual_cascade, "predicted_cascade": predicted_cascade,
                      "cascade_match": actual_cascade==predicted_cascade},
            "reward": {"actual": info["reward"], "predicted": p["reward"], "error": delta},
            "game_over": {"actual": state["game_over"], "predicted": p["game_over"]},
            "timing": {k: p[k] for k in ("elapsed_ms", "reference_elapsed_ms", "scene_create_ms", "copy_ms", "simulation_ms", "cleanup_schedule_ms")},
            "ticks": {"predicted": p["physics_steps"], "actual": state["actual_total_physics_steps"],
                      "post_drop": p["post_drop_steps"], "movement": p["movement_steps"]}}


def _group(rows):
    n = len(rows)
    def score_group(items):
        return {"n": len(items), "exact": rate(sum(r["reward"]["error"]==0 for r in items),len(items)),
                "absolute_error": distribution([abs(r["reward"]["error"]) for r in items]),
                "overprediction": rate(sum(r["reward"]["error"]>0 for r in items),len(items)),
                "underprediction": rate(sum(r["reward"]["error"]<0 for r in items),len(items))}
    def merge_group(items):
        return {"n": len(items), **{key: rate(sum(r["merge"][key] for r in items),len(items))
                for key in ("presence_match","types_count_match","lineage_match","count_match","cascade_match")}}
    physical = [r["physical"] for r in rows]
    events = [r["merge"] for r in rows]
    tp = sum(bool(r["game_over"]["actual"] and r["game_over"]["predicted"]) for r in rows)
    fn = sum(bool(r["game_over"]["actual"] and not r["game_over"]["predicted"]) for r in rows)
    fp = sum(bool(not r["game_over"]["actual"] and r["game_over"]["predicted"]) for r in rows)
    tn = n-tp-fn-fp
    mtp = sum(bool(e["actual"] and e["predicted"]) for e in events)
    mfn = sum(bool(e["actual"] and not e["predicted"]) for e in events)
    mfp = sum(bool(not e["actual"] and e["predicted"]) for e in events)
    return {"n": n, "episodes": len({r["episode_id"] for r in rows}),
            "physical": {"complete_mapping": rate(sum(p["complete"] for p in physical),n),
                         "types_count_match": rate(sum(p["types_count_match"] for p in physical),n),
                         "unmatched_actual_count": sum(len(p["missing_predicted_aliases"])+len(p["type_mismatch_aliases"]) for p in physical),
                         "per_fruit": {k:distribution([f[k] for p in physical for f in p["per_fruit"]]) for k in ERROR_FIELDS},
                         "per_trial_max": {k:distribution([max((f[k] for f in p["per_fruit"]),default=0) for p in physical if p["complete"]]) for k in ERROR_FIELDS},
                         "trace_identity_complete_trials": sum(r.get("trace_identity_complete",False) for r in rows),
                         "max_over_time": {k:distribution([r["trace_max"][k] for r in rows if r.get("trace_identity_complete",False)]) for k in ERROR_FIELDS}},
            "merge": {"all": merge_group(rows),
                      "actual_positive": merge_group([r for r in rows if r["merge"]["actual"]]),
                      "actual_negative": merge_group([r for r in rows if not r["merge"]["actual"]]),
                      "recall": rate(mtp,mtp+mfn), "precision": rate(mtp,mtp+mfp),
                      "tp": mtp, "fn": mfn, "fp": mfp,
                      "evolution_counts_actual":dict(Counter(f"{e['from']}->{e['to']}" for r in rows for e in r["merge"]["actual"])),
                      "evolution_counts_predicted":dict(Counter(f"{e['from']}->{e['to']}" for r in rows for e in r["merge"]["predicted"]))},
            "reward": {"all":score_group(rows),"actual_nonzero":score_group([r for r in rows if r["reward"]["actual"]!=0]),
                       "actual_zero":score_group([r for r in rows if r["reward"]["actual"]==0])},
            "game_over": {"tp":tp,"fn":fn,"fp":fp,"tn":tn,"miss_rate":rate(fn,tp+fn),"false_alarm_rate":rate(fp,fp+tn)},
            "timing_ms": {k:distribution([r["timing"][k] for r in rows if r["timing"][k]>=0])
                          for k in ("elapsed_ms","reference_elapsed_ms","scene_create_ms","copy_ms","simulation_ms","cleanup_schedule_ms")}}


def reward_accounting_summary(records):
    """Use one latest cumulative ledger per episode, never sum repeated snapshots."""
    latest = {}
    for record in records:
        state = record.get("state", {})
        for key in ("reward_accounting", "previous_episode_reward_accounting"):
            ledger = state.get(key)
            if not ledger or not ledger.get("present", True) or not ledger.get("conserved"):
                continue
            episode = ledger["episode_id"]
            old = latest.get(episode)
            if old is None or ledger["open_interval"]["game_time_end"] >= old["open_interval"]["game_time_end"]:
                latest[episode] = ledger
    if not latest:
        return {"available": False, "episodes": 0, "note": "Legacy recordings have no interval ledger"}
    ledgers = list(latest.values())
    result = {"available": True, "episodes": len(ledgers), "episode_snapshots": ledgers}
    for key in ("episode_start_score", "episode_score", "step_reward_total", "between_steps_reward_total"):
        result[key] = sum(ledger[key] for ledger in ledgers)
    result["open_step_reward"] = sum(l["open_interval"]["reward"] for l in ledgers if l["open_interval"]["phase"] == "in_step")
    result["open_between_steps_reward"] = sum(l["open_interval"]["reward"] for l in ledgers if l["open_interval"]["phase"] == "between_steps")
    result["conserved"] = (result["episode_score"] == result["episode_start_score"] + result["step_reward_total"]
                           + result["between_steps_reward_total"] + result["open_step_reward"] + result["open_between_steps_reward"])
    return result


def summarize(records):
    rows = [dict(r["metrics"],episode_id=r["episode_id"]) for r in records
            if r.get("status")=="completed" and r["metrics"]["eligible"]]
    invalid = [r for r in records if r.get("status")!="completed" or not r["metrics"]["eligible"]]
    labels = sorted({"sparse","free_fall","fruit_contact","dense_contact","actual_merge","actual_no_merge","actual_cascade","near_game_over","other"} | {label for r in rows for label in r["labels"]})
    return {"schema_version":1,"attempts":len(records),"eligible":len(rows),"excluded":len(invalid),
            "exclusion_counts":dict(Counter(reason for r in invalid for reason in
                (r.get("metrics",{}).get("ineligible_reasons") or [r.get("status","unknown")]))),
            "all":_group(rows),
            "reward_accounting_all_completed":reward_accounting_summary(records),
            "game_over_all_completed_screening": {**_group([dict(r["metrics"],episode_id=r["episode_id"]) for r in records if r.get("status")=="completed"])["game_over"],
                "note":"Includes timing-mismatched trials so terminal disagreements cannot be hidden by exclusion; inspect raw records before treating as same-horizon accuracy"},
            "terminal_disagreements_for_review": [{"index":r["index"],"episode_id":r["episode_id"],"exclusions":r["metrics"]["ineligible_reasons"],"game_over":r["metrics"]["game_over"]}
                for r in records if r.get("status")=="completed" and r["metrics"]["game_over"]["actual"]!=r["metrics"]["game_over"]["predicted"]],
            "by_stratum":{label:_group([r for r in rows if label in r["labels"]]) for label in labels},
            "by_board_count":{label:_group([r for r in rows if lo<=r["conditions"]["board_count"] and (hi is None or r["conditions"]["board_count"]<=hi)])
                for label,lo,hi in (("0-1",0,1),("2-5",2,5),("6-10",6,10),("11+",11,None))},
            "by_episode":{episode:_group([r for r in rows if r["episode_id"]==episode]) for episode in sorted({r["episode_id"] for r in rows})},
            "candidate_ranking": {"available":False,"reason":"No same-board multi-candidate real outcome fixture; different boards are never ranking ground truth"},
            "notes":["Strata overlap; consecutive samples in an episode are correlated.",
                     "Wilson intervals assume independent Bernoulli samples and are descriptive here, not proof of targets.",
                     "Per-fruit distributions are fruit-weighted and omit unmatched identities; see mapping coverage.",
                     "Game-over measures only the configured horizon, not long-term danger.",
                     "Trace is enabled; reference_elapsed_ms is the paired uninstrumented prediction. Async unload completion excluded."]}
