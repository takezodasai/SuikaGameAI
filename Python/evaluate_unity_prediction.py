"""STEP 4-B sequential compare_step collection / offline aggregation (no search)."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).parent / "src"))
from suika_ai.unity_env import UnityEnv
from suika_ai.prediction_evaluation import evaluate, summarize


def load_records(path):
    """Keep valid data readable after an interrupted final write; never rewrite raw data."""
    records = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines)-1:
                print("Warning: incomplete final JSONL record ignored; earlier records preserved", file=sys.stderr)
                return records, True
            raise ValueError(f"Invalid JSONL record {index+1}")
    return records, False


def append_record(path, record):
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))+"\n")
        file.flush()
        os.fsync(file.fileno())


def export_results(directory, records):
    summary = summarize(records)
    summary["aggregation_source_sha256"]=hashlib.sha256((Path(__file__).parent/"src/suika_ai/prediction_evaluation.py").read_bytes()).hexdigest()
    (directory/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    with (directory/"trials.csv").open("w",newline="",encoding="utf-8-sig") as file:
        fields = ("index","episode_id","status","eligible","labels","x","actual_reward","predicted_reward",
                  "board_count","touching_count","held_type","next_type","actual_merges","predicted_merges",
                  "actual_game_over","predicted_game_over","mapping","matched","predicted_ticks","actual_ticks","reference_ms","traced_ms","exclusions")
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for r in records:
            m=r.get("metrics",{})
            writer.writerow({"index":r["index"],"episode_id":r.get("episode_id"),"status":r["status"],
                "eligible":m.get("eligible"),"labels":"|".join(m.get("labels",[])),"x":r["x"],
                "actual_reward":m.get("reward",{}).get("actual"),"predicted_reward":m.get("reward",{}).get("predicted"),
                "board_count":m.get("conditions",{}).get("board_count"),"touching_count":m.get("conditions",{}).get("touching_fruit_count"),
                "held_type":next((f["type"] for f in m.get("conditions",{}).get("held",[])),None),"next_type":m.get("conditions",{}).get("next_type"),
                "actual_merges":len(m.get("merge",{}).get("actual",[])) if m else None,
                "predicted_merges":len(m.get("merge",{}).get("predicted",[])) if m else None,
                "actual_game_over":m.get("game_over",{}).get("actual"),"predicted_game_over":m.get("game_over",{}).get("predicted"),
                "mapping":m.get("physical",{}).get("mapping"),"matched":m.get("physical",{}).get("matched"),
                "predicted_ticks":m.get("ticks",{}).get("predicted"),"actual_ticks":m.get("ticks",{}).get("actual"),
                "reference_ms":m.get("timing",{}).get("reference_elapsed_ms"),"traced_ms":m.get("timing",{}).get("elapsed_ms"),
                "exclusions":"|".join(m.get("ineligible_reasons",[])) or r.get("error","")})
    with (directory/"fruits.csv").open("w",newline="",encoding="utf-8-sig") as file:
        writer=csv.DictWriter(file,fieldnames=("index","episode_id","mapping","id","type","position","velocity","angle","angular_velocity"))
        writer.writeheader()
        for r in records:
            for f in r.get("metrics",{}).get("physical",{}).get("per_fruit",[]):
                writer.writerow(dict(f,index=r["index"],episode_id=r["episode_id"],mapping=r["metrics"]["physical"]["mapping"]))
    return summary


def provenance():
    root=Path(__file__).resolve().parent.parent
    paths=("Python/evaluate_unity_prediction.py","Python/src/suika_ai/prediction_evaluation.py",
           "Python/src/suika_ai/unity_env.py","Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs",
           "Unity/Assets/Scenes/Script/PredictionDiagnostics.cs","Unity/Assets/Scenes/Script/UDPStepProtocol.cs",
           "Unity/ProjectSettings/Physics2DSettings.asset","Unity/ProjectSettings/TimeManager.asset")
    # Include actual rules, scene, polygon prefabs and project settings in resume identity.
    assets=root/"Unity/Assets"
    extra=[p for p in assets.rglob("*") if p.is_file() and p.suffix.lower() in (".cs",".prefab",".unity",".physicsmaterial2d",".meta")]
    extra += [p for p in (root/"Unity/ProjectSettings").glob("*") if p.is_file()]
    extra += [root/"Unity/Packages/manifest.json",root/"Unity/Packages/packages-lock.json"]
    paths=sorted(set(paths)|{p.relative_to(root).as_posix() for p in extra if p.is_file()})
    result={"source_sha256":{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
            "python":sys.version,"unity_version":(root/"Unity/ProjectSettings/ProjectVersion.txt").read_text().strip()}
    for key,args in (("branch",["git","branch","--show-current"]),("commit",["git","rev-parse","HEAD"])):
        process=subprocess.run(args,cwd=root,capture_output=True,text=True,check=True);result[key]=process.stdout.strip()
    if result["branch"]!="develop":raise RuntimeError("Evaluation requires develop branch")
    return result


def collect(args):
    positions=[float(x) for x in args.positions.split(",")]
    if not positions or any(not 0<=x<=1 for x in positions):raise ValueError("positions must be finite normalized X in [0,1]")
    config={"post_drop_steps":args.post_drop_steps,"episode_steps":args.episode_steps,
            "positions":positions,"random_x":args.random_x,"seed":args.seed,"near_over_margin":args.near_over_margin,
            "timeout":args.timeout,"trace_physics":True,"unity_random_seed_controlled":False,
            "horizon_note":"Diagnostic only; ordinary step remains >=0.5 game seconds"}
    directory=args.output
    current=provenance()
    if args.resume:
        metadata=json.loads((directory/"experiment.json").read_text(encoding="utf-8"))
        if metadata["config"]!=config or metadata["provenance"]!=current:
            raise ValueError("Resume requires identical config, source hashes, commit and versions; use a new output folder")
        records,partial=load_records(directory/"trials.jsonl")
        if partial:raise ValueError("Resume refused after partial final raw record; summarize existing data and use a new folder")
    else:
        directory.mkdir(parents=True,exist_ok=False)
        metadata={"schema_version":1,"experiment_id":uuid.uuid4().hex,"created_utc":datetime.now(timezone.utc).isoformat(),
                  "config":config,"provenance":current}
        (directory/"experiment.json").write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        (directory/"trials.jsonl").touch(exist_ok=False)
        records=[]
    # Resuming starts a NEW Unity episode; it does not restore a suspended physics world.
    episode_steps=args.episode_steps
    with UnityEnv() as env:
        original_send=env._send
        def send(message):
            if message.get("command")=="step":
                message=dict(message,command="compare_step",trace_physics=True,
                             comparison_post_drop_steps=args.post_drop_steps)
            original_send(message)
        env._send=send
        try:
            context=None
            for index in range(len(records),args.samples):
                x=random.Random(f"{args.seed}:{index}").random() if args.random_x else positions[index%len(positions)]
                record={"schema_version":1,"experiment_id":metadata["experiment_id"],"index":index,"x":x,
                        "utc":datetime.now(timezone.utc).isoformat(),"requested_post_drop_steps":args.post_drop_steps}
                try:
                    if context is None or context["game_over"] or episode_steps>=args.episode_steps:
                        context=env.reset(timeout=args.timeout);episode_steps=0
                    record.update(episode_id=context["episode_id"],stream_id=context["stream_id"],episode_step=episode_steps,
                                  previous_observation={k:context[k] for k in ("episode_id","state_id","score","game_over","fruits","current_fruit","next_fruit_type","ai_move_speed","fixed_delta_time","time_scale")})
                    start=time.perf_counter()
                    state,reward,done,info=env.step(x,timeout=args.timeout)
                    record.update(wall_ms=(time.perf_counter()-start)*1000,state=state,action_id=info.get("action_id"))
                    record["metrics"]=evaluate(state,args.near_over_margin,args.post_drop_steps)
                    record["status"]="completed"
                    context=state;episode_steps+=1
                except (RuntimeError,TimeoutError,ValueError,KeyError,TypeError) as error:
                    record.update(status="failed",error=f"{type(error).__name__}: {error}")
                    context=None  # Never retry an unknown outcome as a new action; reset first.
                append_record(directory/"trials.jsonl",record)
                records.append(record)
                summary=export_results(directory,records)
                print(json.dumps({"attempts":len(records),"eligible":summary["eligible"],"status":record["status"],
                                  "labels":record.get("metrics",{}).get("labels",[])}),flush=True)
                if record["status"]=="failed":
                    print(record["error"],file=sys.stderr)
                    break  # Avoid expensive repeated failures (e.g. missing refreshed Unity assembly).
        except KeyboardInterrupt:
            print("Interrupted: completed JSONL records preserved; Unity action may need reset",file=sys.stderr)
        finally:
            summary=export_results(directory,records)
    print(json.dumps({"output":str(directory.resolve()),"attempts":summary["attempts"],"eligible":summary["eligible"]}),flush=True)
    return 0 if summary["eligible"] and not any(r["status"]=="failed" for r in records) else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=10,help="Total attempts, including already collected records on resume")
    parser.add_argument("--episode-steps",type=int,default=20)
    parser.add_argument("--post-drop-steps",type=int,choices=range(1,151),default=25)
    parser.add_argument("--positions",default="0,0.5,1,0.65",help="Fixed cyclic diagnostic inputs; no optimization")
    parser.add_argument("--random-x",action="store_true")
    parser.add_argument("--seed",type=int,default=123,help="Controls Python input sequence only, NOT Unity spawn RNG")
    parser.add_argument("--near-over-margin",type=float,default=.5,help="World units below center-height game-over threshold")
    parser.add_argument("--timeout",type=float,default=30)
    parser.add_argument("--output",type=Path,default=Path("evaluation_"+datetime.now().strftime("%Y%m%d_%H%M%S")))
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--summarize",type=Path,help="Rebuild derived JSON/CSV from this experiment directory; Unity not needed")
    args=parser.parse_args()
    if args.summarize:
        records,_=load_records(args.summarize/"trials.jsonl")
        metadata=json.loads((args.summarize/"experiment.json").read_text(encoding="utf-8"))
        for record in records:
            if record.get("status")=="completed" and "state" in record:
                record["metrics"]=evaluate(record["state"],metadata["config"]["near_over_margin"],metadata["config"]["post_drop_steps"])
        result=export_results(args.summarize,records)
        print(json.dumps({"attempts":result["attempts"],"eligible":result["eligible"]}));return 0
    if args.samples<1 or args.episode_steps<1 or not 0<=args.near_over_margin<100 or not 0<args.timeout<3600:
        parser.error("Invalid sample count, episode length, margin or timeout")
    return collect(args)


if __name__=="__main__":
    sys.exit(main())
