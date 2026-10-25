"""Independent Unity processes, bounded collection, and durable episode ledgers."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

from .unity_env import UnityEnv, validate_planning_settings


@dataclass(frozen=True)
class WorkerSpec:
    game_id: str
    listen_port: int
    python_port: int
    seed: int


def worker_specs(games=2, base_port=18000, seed=12345):
    if type(games) is not int or not 1 <= games <= 4:
        raise ValueError("games must be 1..4")
    if type(base_port) is not int or not 1024 <= base_port <= 65535 - 2 * games + 1:
        raise ValueError("Invalid base port range")
    if type(seed) is not int or not -2147483648 <= seed <= 2147483647 - games + 1:
        raise ValueError("Invalid seed")
    return [WorkerSpec(f"game_{i:02d}", base_port + 2*i, base_port + 2*i+1, seed+i) for i in range(games)]


def check_ports(specs):
    """Fail before launching children; bind again in UnityEnv/Unity to close TOCTOU safely."""
    held=[]
    try:
        for spec in specs:
            for port in (spec.listen_port, spec.python_port):
                sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                held.append(sock)
                if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                sock.bind(("127.0.0.1",port))
    finally:
        for sock in held: sock.close()


class DurableLog:
    """Exclusive new file; one complete JSON object per flush+fsync. Never rewrite history."""
    def __init__(self,path):
        self.file=Path(path).open("x",encoding="utf-8")
        self.keys=set()
    def write(self,event):
        if event["event"]=="transition":
            key=tuple(event[k] for k in ("game_id","stream_id","episode_id","action_id"))
            if key in self.keys: raise ValueError("Duplicate transition")
            self.keys.add(key)
        self.file.write(json.dumps(dict(schema_version=2,**event),ensure_ascii=False,allow_nan=False)+"\n")
        self.file.flush();os.fsync(self.file.fileno())
    def close(self): self.file.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def source_state(before,state,info):
    """The planner's exact acceptance board differs from an earlier network snapshot."""
    p=info.get("planning") or {}
    if not p: return None
    return dict(episode_id=state["episode_id"],state_id=p["source_state_id"],score=info["score_before"],
        fruits=p["source_fruits"],current_fruit=dict(id=p["held_fruit_id"],type=p["held_fruit_type"],x=info["movement_start_x"]),
        next_fruit_type=p["next_fruit_type"],fixed_delta_time=p["fixed_delta_time"],move_speed=p["move_speed"])


def collect_worker(spec,env,settings,episodes,max_steps,stop,output,barrier=None,require_metadata=False,expected_go_ratio=None,training_metadata=True,max_episode_seconds=None,expected_rules_version=None,step_timeout=None):
    """No auto reset beyond explicitly requested episode count; timeout never auto-recovers."""
    from .collection_metadata import CollectionMetadata
    metadata=CollectionMetadata(env,Path(output).parent/"metadata"/(spec.game_id+".json"),require_metadata,expected_go_ratio,training_metadata,expected_rules_version)
    steps=0;ended=0;started=time.monotonic()
    with DurableLog(output) as log:
        try:
            ready_deadline=time.monotonic()+30
            while True:
                if stop.is_set():return dict(game_id=spec.game_id,status="stopped",steps=0)
                try: env.receive_state(min(2,max(.01,ready_deadline-time.monotonic())));break
                except (TimeoutError,ConnectionResetError):
                    if time.monotonic()>=ready_deadline:raise
            if barrier:barrier.wait(timeout=35)
            started=time.monotonic()
            for episode_number in range(1,episodes+1):
                if stop.is_set():break
                episode_started=time.monotonic();wall_limited=False
                state=env.reset()
                if state.get("has_worker_seed") and state.get("worker_seed")!=spec.seed:raise ValueError("Player seed differs from requested worker seed")
                if require_metadata and state.get("has_worker_seed") is not True:raise ValueError("Player did not confirm worker seed")
                metadata.attach(state)
                if metadata.environment_id is not None and env.last_state and env.last_state["episode_id"]==state["episode_id"]:state=env.last_state
                state=metadata.attach(state);initial_score=state["score"];step_total=0;gap_total=0
                log.write(dict(environment_id=metadata.environment_id,event="episode_start",game_id=spec.game_id,episode_id=state["episode_id"],
                    stream_id=state["stream_id"],seed=spec.seed,worker_seed=spec.seed,episode_number=episode_number,
                    rng_mode="continuous_after_worker_seed",collection_policy=dict(command="plan_step",settings=settings),state=state))
                episode_steps=0
                for turn in range(1,max_steps+1):
                    if stop.is_set() or state["game_over"]:break
                    if max_episode_seconds is not None and time.monotonic()-episode_started>=max_episode_seconds:
                        wall_limited=True;break
                    before=state;step_started=time.monotonic()
                    state,reward,done,info=env.plan_step(settings) if step_timeout is None else env.plan_step(settings,timeout=step_timeout)
                    step_wall_seconds=time.monotonic()-step_started
                    state=metadata.attach(state)
                    if info.get("status") != "completed":
                        if not done or state["episode_id"]!=before["episode_id"]:
                            raise ValueError("Rejected/nonterminal action during collection")
                        # GO can occur between accepted actions: this is an observation,
                        # not another transition with the previous action_id.
                        gap=state["score"]-before["score"];gap_total+=gap
                        log.write(dict(event="terminal_observation",game_id=spec.game_id,stream_id=state["stream_id"],
                            episode_id=state["episode_id"],state=state,between_steps_reward=gap,game_over=True))
                        break
                    # Exact score_before comes from Unity's accepted action, not a stale snapshot.
                    score_before=info["score_before"] if info.get("status")=="completed" else state["score"]
                    gap=score_before-before["score"]
                    if state["episode_id"]!=before["episode_id"] or state["score"]!=before["score"]+gap+reward:
                        raise ValueError("Episode mix or nonconserving transition reward")
                    step_total+=reward;gap_total+=gap;steps+=1;episode_steps+=1
                    log.write(dict(event="transition",game_id=spec.game_id,stream_id=state["stream_id"],
                        episode_id=state["episode_id"],action_id=info.get("action_id",env._action_id),turn=turn,
                        observed_before=before,decision_source=source_state(before,state,info),state=state,
                        action_accepted=info.get("status")=="completed",
                        selected_x=(info.get("planning") or {}).get("selected_x"),score=state["score"],reward=reward,
                        between_steps_reward=gap,game_over=done,info=info,step_wall_seconds=step_wall_seconds))
                    if done:break
                final=metadata.attach(env.receive_state(3))
                if final["episode_id"]!=state["episode_id"]:raise ValueError("Episode changed at final boundary")
                tail=final["score"]-state["score"]
                conserved=final["score"]==initial_score+step_total+gap_total+tail
                if not conserved:raise ValueError("Episode score was double counted or lost")
                terminal=final["game_over"]
                log.write(dict(event="episode_end",game_id=spec.game_id,stream_id=final["stream_id"],
                    episode_id=final["episode_id"],game_over=terminal,truncated=not terminal,
                    reason="game_over" if terminal else "stopped" if stop.is_set() else "wall_limit" if wall_limited else "step_limit",
                    wall_seconds=time.monotonic()-episode_started,
                    final_score=final["score"] if terminal else None,last_observed_score=final["score"],
                    step_reward_total=step_total,between_steps_reward_total=gap_total,
                    tail_between_steps_reward=tail,conserved=conserved,state=final,steps=episode_steps))
                ended+=1
            elapsed=time.monotonic()-started
            return dict(game_id=spec.game_id,status="stopped" if stop.is_set() else "completed",steps=steps,
                episodes=ended,elapsed_seconds=elapsed,steps_per_second=steps/elapsed if elapsed else 0)
        except Exception as error:
            if barrier:
                try:barrier.abort()
                except Exception:pass
            log.write(dict(event="worker_error",game_id=spec.game_id,error=type(error).__name__+": "+str(error),
                completed_steps=steps,outcome_unknown=env._pending_step is not None,
                episode_id=env._action_episode,pending_command=env._pending_step,last_observed_state=env.last_state,final_score=None))
            return dict(game_id=spec.game_id,status="error",steps=steps,error=str(error),elapsed_seconds=time.monotonic()-started)


def player_command(exe,spec,log_path,headless=False,audio=None,video_map=None):
    command=[str(exe),"--suika-game-id",spec.game_id,"--suika-listen-port",str(spec.listen_port),
        "--suika-python-port",str(spec.python_port),"--suika-seed",str(spec.seed),
        "-screen-width","960","-screen-height","540","-screen-fullscreen","0","-logFile",str(log_path)]
    if audio is None:audio=not headless and spec.game_id=="game_00"
    command.extend(["--suika-audio","1" if audio else "0"])
    if video_map:command.extend(["--suika-video-map",video_map])
    if headless:command.extend(["-batchmode","-nographics"])
    return command


def selected_video_games(games,headless=False,view_game=None,view_games=None):
    """Legacy single index or an independent display count; validate before spawning."""
    if view_game is not None and view_games is not None:
        raise ValueError("Choose --view-game OR --view-games")
    if view_games is not None:
        if type(view_games) is not int or not 0<=view_games<=games:
            raise ValueError("--view-games must be 0..games")
        indices=list(range(view_games))
    elif view_game is not None:
        if type(view_game) is not int or not 0<=view_game<games:
            raise ValueError("--view-game must select an existing game")
        indices=[view_game]
    else:indices=[]
    if headless and indices:raise ValueError("Video requires graphics Players; unavailable with --headless")
    return [f"game_{i:02d}" for i in indices]


def run_parallel(exe,output,games=2,episodes=1,max_steps=1000,base_port=18000,seed=12345,headless=False,settings=None,view_game=None,main_audio=True,others_audio=False,launch_viewer=True,view_games=None,require_metadata=False,expected_go_ratio=None,training_metadata=True,max_episode_seconds=None,expected_rules_version=None,step_timeout=None):
    if max_episode_seconds is not None and (not isinstance(max_episode_seconds,(float,int)) or not 0<max_episode_seconds<=86400):raise ValueError("Invalid episode wall limit")
    if not training_metadata and (require_metadata or expected_go_ratio is not None or expected_rules_version is not None):raise ValueError("Metadata must be enabled to verify the environment")
    exe=Path(exe).resolve();output=Path(output).resolve()
    if not exe.is_file():raise FileNotFoundError(f"Build the Unity Player first: {exe}")
    if type(episodes) is not int or episodes<1 or type(max_steps) is not int or max_steps<1:
        raise ValueError("episodes/max_steps must be positive")
    settings=validate_planning_settings(settings or {})
    if settings["execution_mode"]!="sync" and games!=1:raise ValueError("Frame execution prototype supports one game only")
    if (settings["pair_coverage_iterations"]>0 or settings["candidate_policy"]=="coarse-root" or settings["action_order_policy"]!="index" or settings["expansion_policy"]!="legacy" or settings["tree_policy"]!="chance" or settings["rollout_policy"]!="random" or settings["mcts_common_chance"]) and games!=1:raise ValueError("Experimental tree/rollout sampling supports one game only")
    if settings["candidate_policy"]!="grid" and games!=1:raise ValueError("Board-five prototype supports one game only")
    if step_timeout is not None and (type(step_timeout) not in (int,float) or not __import__("math").isfinite(step_timeout) or step_timeout<=0):raise ValueError("Invalid step timeout")
    specs=worker_specs(games,base_port,seed);check_ports(specs)
    video_games=selected_video_games(games,headless,view_game,view_games)
    import uuid,sys
    from .presentation import PresentationControls
    run_id=uuid.uuid4().hex
    video_maps={g:"Local\\SuikaVideo_"+run_id+"_"+g for g in video_games}
    # Retain the old manifest fields only for single-game tools.
    video_game=video_games[0] if len(video_games)==1 else None
    video_map=video_maps.get(video_game)
    viewer=None
    output.mkdir(parents=True,exist_ok=False)
    stop=threading.Event();barrier=threading.Barrier(games)
    children=[];envs=[];results=[];collection_started=time.monotonic()
    try:
        for spec in specs:
            env=UnityEnv(server=("127.0.0.1",spec.listen_port),local=("127.0.0.1",spec.python_port),expected_game_id=spec.game_id)
            envs.append(env)
            command=player_command(exe,spec,output/(spec.game_id+"_player.log"),headless,
                audio=False if headless else main_audio if spec.game_id=="game_00" else others_audio,
                video_map=video_maps.get(spec.game_id))
            children.append(subprocess.Popen(command,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)))
        (output/"run.json").write_text(json.dumps(dict(schema_version=4,training_metadata=training_metadata,require_metadata=require_metadata,expected_go_ratio=expected_go_ratio,expected_rules_version=expected_rules_version,exe_sha256=__import__("hashlib").sha256(exe.read_bytes()).hexdigest(),evaluation_version=("step8b-uct-"+("value" if (settings or {}).get("ai_mode")=="mcts_value" else "reward")) if (settings or {}).get("ai_mode") in ("mcts","mcts_value") else ("step8a-depth2-"+(settings or {}).get("search_leaf","reward")) if (settings or {}).get("ai_mode")=="two_step" else "step7c-v1-value-points" if (settings or {}).get("ai_mode")=="value" else "step5-v3-score-roughness",seed_mode="continuous_after_worker_seed",run_id=run_id,video_maps=video_maps,video_game=video_game,video_map=video_map,exe=str(exe),headless=headless,
            settings=settings,episodes=episodes,max_steps=max_steps,max_episode_seconds=max_episode_seconds,step_timeout=step_timeout,workers=[dict(**s.__dict__,pid=p.pid) for s,p in zip(specs,children)]),indent=2),encoding="utf-8")
        controls=PresentationControls(output,run_id,{s.game_id:e for s,e in zip(specs,envs)},video_games)
        if video_maps and launch_viewer:
            viewer=subprocess.Popen([sys.executable,"-m","suika_ai.video_viewer","--run",str(output),
                "--metrics",str(output/"viewer_metrics.json")],cwd=str(Path(__file__).resolve().parents[2]),
                env=dict(__import__("os").environ,PYTHONPATH=str(Path(__file__).resolve().parents[1])))
        with ThreadPoolExecutor(max_workers=games) as pool:
            futures=[pool.submit(collect_worker,s,e,settings,episodes,max_steps,stop,output/(s.game_id+".jsonl"),barrier,require_metadata,expected_go_ratio,training_metadata,max_episode_seconds,expected_rules_version,step_timeout)
                for s,e in zip(specs,envs)]
            try:
                pending=set(futures)
                while pending:
                    completed,pending=wait(pending,timeout=.25)
                    controls.poll()
                    for f in completed:
                        result=f.result();results.append(result);print(json.dumps(result),flush=True)
                    if any(p.poll() is not None for p in children) and pending:
                        stop.set();barrier.abort()
            except KeyboardInterrupt:
                stop.set();barrier.abort()
                print("Stopping: completed actions will be flushed; no new reset/actions.",flush=True)
                for f in futures:
                    if not any(r.get("game_id")==specs[futures.index(f)].game_id for r in results):results.append(f.result())
        elapsed=time.monotonic()-collection_started
        # Startup-inclusive throughput is explicit; per-worker elapsed excludes startup/barrier.
        summary=dict(workers=results,wall_seconds=elapsed,total_steps=sum(r["steps"] for r in results),
            startup_included_steps_per_second=sum(r["steps"] for r in results)/elapsed,
            collection_steps_per_second=sum(r["steps"] for r in results)/max([r.get("elapsed_seconds",0) for r in results]+[.001]))
        (output/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        return summary
    finally:
        stop.set()
        for env in envs:env.close()
        # Only handles launched above; never find/kill the user's Editor or unrelated Players.
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)


def validate_run(output):
    """Offline integrity check. A partial final line is reported, never treated as data."""
    output=Path(output);manifest=json.loads((output/"run.json").read_text(encoding="utf-8"))
    report=[]
    for worker in manifest["workers"]:
        game=worker["game_id"];seen=set();balances={};ended_ids=set();ends=0;terminal=0;partial=False
        path=output/(game+".jsonl");lines=path.read_text(encoding="utf-8").splitlines()
        for n,line in enumerate(lines):
            try:row=json.loads(line)
            except json.JSONDecodeError:
                if n!=len(lines)-1:raise
                partial=True;break
            if row["game_id"]!=game:raise ValueError("Cross-game log contamination")
            event=row["event"];episode=row.get("episode_id")
            if event!="worker_error" and episode in ended_ids:raise ValueError("Record after episode end")
            state=row.get("state")
            if state is not None:
                for field in ("game_id","stream_id","episode_id"):
                    if state.get(field)!=row.get(field):raise ValueError("Observation identity mismatch")
            if event=="episode_start":
                if episode in balances:raise ValueError("Repeated episode start")
                balances[episode]=row["state"]["score"]
            elif event=="transition":
                key=(row["stream_id"],episode,row["action_id"])
                if key in seen:raise ValueError("Duplicate action record")
                seen.add(key)
                balances[episode]+=row["between_steps_reward"]+row["reward"]
                if balances[episode]!=row["score"] or row["state"]["game_id"]!=game:
                    raise ValueError("Nonconserving/cross-game transition")
                ledger=row["state"].get("reward_accounting")
                if ledger and (not ledger["conserved"] or ledger["episode_score"]!=row["score"]):
                    raise ValueError("Invalid Unity reward ledger")
            elif event=="terminal_observation":
                balances[episode]+=row["between_steps_reward"]
                if balances[episode]!=row["state"]["score"]:raise ValueError("Nonconserving terminal observation")
            elif event=="episode_end":
                if row["state"]["game_over"]!=row["game_over"] or row["truncated"]==row["game_over"]:raise ValueError("GO/truncation label mismatch")
                if row.get("steps")!=sum(key[1]==episode for key in seen):raise ValueError("Episode step count mismatch")
                balances[episode]+=row["tail_between_steps_reward"]
                if balances[episode]!=row["last_observed_score"] or not row["conserved"]:
                    raise ValueError("Nonconserving episode end")
                if row["game_over"] and row["final_score"]!=balances[episode]:raise ValueError("Wrong terminal label")
                ends+=1;terminal+=int(row["game_over"]);ended_ids.add(episode)
        report.append(dict(game_id=game,transitions=len(seen),episodes_ended=ends,terminal_episodes=terminal,
            incomplete_final_line=partial,incomplete_episodes=len(set(balances)-ended_ids),conserved=True))
    return report


def resolve_collection_seed(value,games=2,episodes=1,independent_episodes=False):
    """Automatic selection uses Python secrets, never the Unity game RNG."""
    import secrets
    span=games*(episodes if independent_episodes else 1)
    if type(games) is not int or not 1<=games<=4 or type(episodes) is not int or episodes<1 or span>2147483647:raise ValueError("Invalid collection size")
    seed=secrets.randbelow(2147483647-span+1) if str(value).lower()=="auto" else int(value)
    if not -2147483648<=seed<=2147483647-span+1:raise ValueError("Seed schedule exceeds signed 32-bit range")
    return seed


def run_seeded_episodes(exe,output,games=2,episodes=1,max_steps=1000,base_port=18000,seed=12345,headless=False,settings=None,main_audio=True,others_audio=False,require_metadata=False,expected_go_ratio=None,training_metadata=True):
    """Opt-in independent episode seeds without altering Unity reset/RNG semantics.

    Recreate owned Players for each bounded episode; legacy continuous mode is unchanged.
    """
    output=Path(output).resolve();seed=resolve_collection_seed(seed,games,episodes,True)
    worker_specs(games,base_port,seed);settings=validate_planning_settings(settings or {})
    if type(max_steps) is not int or max_steps<1:raise ValueError("max_steps must be positive")
    output.mkdir(parents=True,exist_ok=False)
    manifest=dict(schema_version=2,require_metadata=require_metadata,expected_go_ratio=expected_go_ratio,seed_mode="independent_player_per_episode",base_seed=seed,games=games,episodes=episodes,
        schedule=[dict(episode=i+1,worker_seeds=[seed+i*games+j for j in range(games)]) for i in range(episodes)],settings=settings)
    (output/'collection.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    results=[]
    for i in range(episodes):
        summary=run_parallel(exe,output/f"episode_{i+1:04d}",games,1,max_steps,base_port,seed+i*games,headless,settings,
            main_audio=main_audio,others_audio=others_audio,require_metadata=require_metadata,expected_go_ratio=expected_go_ratio,training_metadata=training_metadata)
        results.append(summary)
        if any(w['status'] in ('error','stopped') for w in summary['workers']):break
    summary=dict(seed_mode=manifest['seed_mode'],base_seed=seed,episodes_requested=episodes,episodes_started=len(results),runs=results)
    (output/'collection_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary
