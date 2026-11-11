"""Opt-in isolated Physics2D threading audit; never changes production settings."""
import argparse, json, statistics, subprocess, time
from pathlib import Path

def summarize(rows):
    searches=[r for r in rows if r.get("evt")=="search"]
    pairs=[r for r in rows if r.get("evt")=="pair"]
    if not searches or not pairs: raise ValueError("Missing complete paired results")
    for r in searches:
        if r.get("error"): raise ValueError(r["error"])
        if r["actual_multithreading"]!=r["threaded"] or r["actual_sorting"]!=r["threaded"]:
            raise ValueError("Physics settings were not applied")
        if not r["source_unchanged"] or r["report"]["completed_iterations"]!=r["iterations"]:
            raise ValueError("Changed root or incomplete iterations")
        if r["lifetime"]["retained_scenes"]!=1 or r["lifetime"]["pending_unloads"]!=0:
            raise ValueError("Prediction scene leak")
    result=[]
    keys=sorted({(r["fixture"],r["iterations"],r["depth"]) for r in searches})
    for fixture,it,depth in keys:
        group=[r for r in searches if (r["fixture"],r["iterations"],r["depth"])==(fixture,it,depth) and not r["warmup"]]
        a=[r["elapsed_ms"] for r in group if not r["threaded"]]; b=[r["elapsed_ms"] for r in group if r["threaded"]]
        if not a or len(a)!=len(b): raise ValueError("Unpaired timings")
        checks=[r for r in pairs if (r["fixture"],r["iterations"],r["depth"])==(fixture,it,depth)]
        result.append(dict(fixture=Path(fixture).name,iterations=it,depth=depth,samples=len(a),equal_pairs=sum(r["equal"] for r in checks),total_pairs=len(checks),single_median_ms=statistics.median(a),threaded_median_ms=statistics.median(b),time_reduction_percent=100*(1-statistics.median(b)/statistics.median(a)),single_range_ms=[min(a),max(a)],threaded_range_ms=[min(b),max(b)]))
    return dict(exact_pairs=sum(r["equal"] for r in pairs),total_pairs=len(pairs),all_equal=all(r["equal"] for r in pairs),results=result)

def run(exe,output,fixtures,specs,repeats=1,verify=True):
    if not Path(exe).is_file(): raise FileNotFoundError(exe)
    for fixture in fixtures:
        if not Path(fixture).is_file(): raise FileNotFoundError(fixture)
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    cfg=output/"config.json"; trace=output/"trace.jsonl"
    cfg.write_text(json.dumps(dict(output=str(trace.resolve()),fixtures=[str(Path(f).resolve()) for f in fixtures],specs=specs,repeats=repeats,verify=verify,profile=False)))
    command=[str(Path(exe).resolve()),"-batchmode","-nographics","--suika-audio","0","--suika-listen-port","41480","--suika-python-port","41481","-logFile",str((output/"player.log").resolve()),"-suikaRuntimeProbe",str((output/"runtime.jsonl").resolve()),"-suikaPhysicsThreadProbe",str(cfg.resolve())]
    child=subprocess.Popen(command,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); start=time.monotonic()
    try:
        while child.poll() is None:
            if time.monotonic()-start>180: raise TimeoutError("Bounded thread diagnostic exceeded 180 seconds")
            time.sleep(.2)
        if child.returncode: raise RuntimeError("Diagnostic failed; inspect trace and player.log")
    finally:
        if child.poll() is None: child.terminate();child.wait(timeout=10)
    rows=[json.loads(line) for line in trace.read_text().splitlines()]
    report=summarize(rows); report["verify_full_states"]=verify
    (output/"summary.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--exe",type=Path,default=Path("../Unity/Builds/PhysicsThreads_01/SuikaGameAI.exe"));p.add_argument("--output",type=Path,required=True)
    p.add_argument("--fixtures",type=Path,nargs="+",required=True);p.add_argument("--specs",nargs="+",default=["32:4","32:16"])
    p.add_argument("--repeats",type=int,choices=range(1,6),default=1);p.add_argument("--timing",action="store_true")
    a=p.parse_args();specs=[dict(zip(["iterations","depth"],map(int,s.split(":")))) for s in a.specs]
    if not 1<=len(a.fixtures)<=4 or not 1<=len(specs)<=3 or any(not 32<=s["iterations"]<=128 or not 2<=s["depth"]<=16 for s in specs):p.error("Bounded diagnostic only: <=4 fixtures, <=3 specs, iterations32..128/depth2..16")
    run(a.exe,a.output,a.fixtures,specs,a.repeats,not a.timing)
if __name__=="__main__":main()
