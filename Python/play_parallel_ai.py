"""STEP 6: launch 1..4 independent Unity Players and collect bounded episodes."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from suika_ai.parallel_play import run_parallel,resolve_collection_seed,run_seeded_episodes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe",type=Path,default=Path(__file__).resolve().parents[1]/"Unity/Builds/Step6/SuikaGameAI.exe")
    parser.add_argument("--games",type=int,default=2)
    parser.add_argument("--episodes",type=int,default=1,help="Explicit number per game; no infinite reset loop")
    parser.add_argument("--max-steps",type=int,default=1000)
    parser.add_argument("--base-port",type=int,default=18000)
    parser.add_argument("--seed",default="12345",help="Integer or auto; actual seed is recorded")
    parser.add_argument("--independent-episode-seeds",action="store_true",help="Headless/zero-video collection: restart owned Players for each episode with a new reproducible seed")
    parser.add_argument("--candidate-policy",choices=("grid","board-five","coarse-root"),default="grid")
    parser.add_argument("--candidates",type=int,default=None)
    parser.add_argument("--post-drop-steps",type=int,default=25)
    parser.add_argument("--settings",type=Path)
    parser.add_argument("--keep-player-on-error",action="store_true",help="GUI only: stop AI on error but keep its Player window for diagnosis")
    parser.add_argument("--episode-events",action="store_true",help="Record actual-game drop counts and watermelon events (STEP8U+)")
    parser.add_argument("--no-training-metadata",action="store_true",help="Diagnostic baseline only: skip optional telemetry queries")
    parser.add_argument("--require-metadata",action="store_true",help="Refuse old Players without training metadata")
    parser.add_argument("--expected-go-ratio",type=float,help="Fail before collecting if the built Player has a different GO ratio")
    parser.add_argument("--headless",action="store_true",help="Experimental no-graphics execution, unchanged physics clock")
    views=parser.add_mutually_exclusive_group()
    views.add_argument("--view-game",type=int,help="Legacy: display one game by index")
    views.add_argument("--view-games",type=int,help="Display first N games (0..games), independent of --games")
    parser.add_argument("--no-viewer",action="store_true",help="Export frames without launching Viewer")
    parser.add_argument("--main-audio",choices=("on","off"),default="on")
    parser.add_argument("--others-audio",choices=("on","off"),default="off")
    parser.add_argument("--output",type=Path,default=Path("outputs")/("parallel_"+datetime.now().strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6]))
    parser.add_argument("--ai-mode",choices=("heuristic","value","two_step","mcts","mcts_value"),default="heuristic")
    parser.add_argument("--value-model",type=Path,help="Exported JSON; defaults to the epoch3 model bundled with Player")
    parser.add_argument("--search-leaf",choices=("reward","heuristic","value"),default="reward")
    parser.add_argument("--inter-step-wait-ticks",type=int,default=0)
    parser.add_argument("--mcts-iterations",type=int,default=32)
    parser.add_argument("--mcts-max-depth",type=int,default=3)
    parser.add_argument("--mcts-exploration",type=float,default=2**.5)
    parser.add_argument("--mcts-point-scale",type=float,default=55.)
    parser.add_argument("--pair-coverage-iterations",type=int,default=0)
    parser.add_argument("--action-order-policy",choices=("index","shuffle"),default="index")
    parser.add_argument("--expansion-policy",choices=("legacy","chance_decision"),default="legacy")
    parser.add_argument("--tree-policy",choices=("chance","public_open_loop"),default="chance")
    parser.add_argument("--rollout-policy",choices=("random","guided"),default="random")
    parser.add_argument("--rollout-random-probability",type=float,default=.5)
    parser.add_argument("--mcts-common-chance",action="store_true")
    parser.add_argument("--mcts-seed",type=int,default=8191)
    parser.add_argument("--planning-execution",choices=("sync","frames","frames_adaptive"),default="sync",help="Experimental frame-sliced MCTS, one game only")
    parser.add_argument("--frame-tick-slicing",action="store_true",help="Opt-in per-physics-tick prediction yields; same MCTS calculation")
    parser.add_argument("--frame-budget-ms",type=float,default=6.)
    parser.add_argument("--frame-lead-ticks",type=int,default=150)
    parser.add_argument("--frame-max-attempts",type=int,default=2)
    args=parser.parse_args()
    if args.planning_execution!="sync" and (args.games!=1 or args.ai_mode not in ("mcts","mcts_value")):
        parser.error("Frame prototype requires --games 1 and MCTS")
    if args.no_training_metadata and (args.require_metadata or args.expected_go_ratio is not None):parser.error("Cannot verify metadata/GO ratio with --no-training-metadata")
    settings=json.loads(args.settings.read_text(encoding="utf-8-sig")) if args.settings else {}
    settings.update(candidate_policy=args.candidate_policy,candidate_count=args.candidates if args.candidates is not None else (7 if args.candidate_policy=="coarse-root" else 2 if args.ai_mode=="two_step" else 5),post_drop_steps=args.post_drop_steps)
    settings.update(pair_coverage_iterations=args.pair_coverage_iterations,action_order_policy=args.action_order_policy,expansion_policy=args.expansion_policy,tree_policy=args.tree_policy,rollout_policy=args.rollout_policy,rollout_random_probability=args.rollout_random_probability,mcts_common_chance=args.mcts_common_chance)
    settings.update(mcts_iterations=args.mcts_iterations,mcts_max_depth=args.mcts_max_depth,mcts_exploration=args.mcts_exploration,mcts_point_scale=args.mcts_point_scale,mcts_seed=args.mcts_seed)
    settings.update(search_leaf=args.search_leaf,inter_step_wait_ticks=args.inter_step_wait_ticks,ai_mode=args.ai_mode,value_model_path=str(args.value_model.resolve()) if args.value_model else "")
    settings.update(frame_tick_slicing=args.frame_tick_slicing,execution_mode=args.planning_execution,frame_budget_ms=args.frame_budget_ms,frame_lead_ticks=args.frame_lead_ticks,frame_max_attempts=args.frame_max_attempts)
    seed=resolve_collection_seed(args.seed,args.games,args.episodes,args.independent_episode_seeds)
    if args.independent_episode_seeds:
        if args.keep_player_on_error:parser.error("--keep-player-on-error requires regular GUI mode")
        if args.episode_events:parser.error("--episode-events currently requires regular worker mode")
        if args.view_game is not None or args.view_games not in (None,0):parser.error("Independent episode seed mode is for non-Viewer collection; use legacy mode for live debugging")
        summary=run_seeded_episodes(args.exe,args.output,args.games,args.episodes,args.max_steps,args.base_port,seed,args.headless,settings,args.main_audio=="on",args.others_audio=="on",require_metadata=args.require_metadata,expected_go_ratio=args.expected_go_ratio,training_metadata=not args.no_training_metadata)
        print(json.dumps(dict(output=str(args.output.resolve()),**summary)))
        return 1 if any(w['status']=='error' for r in summary['runs'] for w in r['workers']) else 0
    summary=run_parallel(args.exe,args.output,args.games,args.episodes,args.max_steps,args.base_port,seed,args.headless,settings,args.view_game,args.main_audio=="on",args.others_audio=="on",not args.no_viewer,view_games=args.view_games,require_metadata=args.require_metadata,expected_go_ratio=args.expected_go_ratio,training_metadata=not args.no_training_metadata,episode_events=args.episode_events,keep_player_on_error=args.keep_player_on_error)
    print(json.dumps(dict(output=str(args.output.resolve()),**summary),ensure_ascii=False))
    return 1 if any(w["status"]=="error" for w in summary["workers"]) else 0


if __name__=="__main__":raise SystemExit(main())
