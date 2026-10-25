"""STEP 5: one episode, no automatic reset loop. Ctrl+C stops after/in current action.

Start Unity Play first. Do not run another UDP client on the same port.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from suika_ai.unity_env import UnityEnv, validate_planning_settings


def play(env, settings, max_steps, output):
    state = env.reset()
    with Path(output).open("w", encoding="utf-8") as log:
        for turn in range(1, max_steps + 1):
            if state["game_over"]:
                break
            state, reward, done, info = env.plan_step(settings)
            row = dict(turn=turn, episode_id=state["episode_id"], score=state["score"],
                       reward=reward, game_over=done, info=info)
            log.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            log.flush()
            planning = info.get("planning", {})
            print(json.dumps(dict(turn=turn, score=state["score"], reward=reward, done=done,
                x=planning.get("selected_x"), planning_ms=planning.get("elapsed_ms"))), flush=True)
            if done:
                break
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=int, default=None)
    parser.add_argument("--post-drop-steps", type=int, default=25)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--settings", type=Path, help="JSON object overriding evaluation coefficients")
    parser.add_argument("--output", type=Path, default=Path("outputs/step5_decisions.jsonl"))
    parser.add_argument("--ai-mode",choices=("heuristic","value","two_step","mcts","mcts_value"),default="heuristic")
    parser.add_argument("--value-model",type=Path,help="Exported JSON; defaults to the epoch3 model bundled with Player")
    parser.add_argument("--search-leaf",choices=("reward","heuristic","value"),default="reward")
    parser.add_argument("--inter-step-wait-ticks",type=int,default=0)
    parser.add_argument("--mcts-iterations",type=int,default=32)
    parser.add_argument("--mcts-max-depth",type=int,default=3)
    parser.add_argument("--mcts-exploration",type=float,default=2**.5)
    parser.add_argument("--mcts-point-scale",type=float,default=55.)
    parser.add_argument("--mcts-seed",type=int,default=8191)
    args=parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8-sig")) if args.settings else {}
    settings.update(candidate_count=args.candidates if args.candidates is not None else (2 if args.ai_mode=="two_step" else 5), post_drop_steps=args.post_drop_steps)
    settings.update(mcts_iterations=args.mcts_iterations,mcts_max_depth=args.mcts_max_depth,mcts_exploration=args.mcts_exploration,mcts_point_scale=args.mcts_point_scale,mcts_seed=args.mcts_seed)
    settings.update(search_leaf=args.search_leaf,inter_step_wait_ticks=args.inter_step_wait_ticks,ai_mode=args.ai_mode,value_model_path=str(args.value_model.resolve()) if args.value_model else "")
    validate_planning_settings(settings)
    if args.max_steps < 1:
        parser.error("--max-steps must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with UnityEnv() as env:
            final = play(env, settings, args.max_steps, args.output)
            print(json.dumps(dict(status="game_over" if final["game_over"] else "step_limit", score=final["score"])))
    except KeyboardInterrupt:
        print("Stopped. An in-flight step may finish once; no further actions or resets are sent.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
