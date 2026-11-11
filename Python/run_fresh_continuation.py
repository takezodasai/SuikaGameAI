"""Bounded one-process-per-root/candidate actual-game replay and continuation."""
import argparse,json,subprocess,time,hashlib
from pathlib import Path
from suika_ai.parallel_play import worker_specs,check_ports

def read_rows(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        for line in f:
            if not line.endswith('\n'):raise ValueError('Incomplete diagnostic line')
            yield json.loads(line)

def run(config_path,exe,port=42040,timeout=330):
    p=Path(config_path);cfg=json.loads(p.read_text());folder=p.parent;out=Path(cfg['output']);check_ports(worker_specs(1,port))
    if out.exists() or (folder/'player.log').exists():raise FileExistsError('Fresh output required')
    command=[str(Path(exe).resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-events','1','--suika-seed',str(cfg['seed']),'--suika-listen-port',str(port),'--suika-python-port',str(port+1),'-suikaFreshBranch',str(p.resolve()),'-logFile',str((folder/'player.log').resolve())]
    start=time.monotonic();child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    timed_out=False
    try:child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:timed_out=True
    finally:
        if child.poll() is None:child.terminate();child.wait(10)
    rows=list(read_rows(out));ends=[r for r in rows if r['evt']=='end'];roots=[r for r in rows if r['evt']=='root'];end=ends[-1] if ends else None
    result=dict(exit_code=child.returncode,process_timeout=timed_out,wall_seconds=time.monotonic()-start,command=command,end=end,root=roots[-1] if roots else None,errors=[r for r in rows if r['evt']=='error']+([dict(error='process_timeout')] if timed_out else []),first_mismatch=next((r for r in rows if r['evt']=='prefix_mismatch'),None),file_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),original_game_exactly_replayed=False)
    with (folder/'result.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(folder=str(folder),exit_code=child.returncode,reason=end.get('reason') if end else None,score=end.get('score') if end else None,known_return=end.get('mc_return_known') if end else False)),flush=True);return result

def source_positions(source):
    rows=[json.loads(x) for x in Path(source).read_text().splitlines()];start=next(r for r in rows if r['event']=='episode_start');trans=[r for r in rows if r['event']=='transition' and r['info']['drop_success']]
    return start['seed'],[float(r['selected_x']) for r in trans],rows

def config(folder,seed,positions,reference=None,continuation=False,x=.5,future=9101,seconds=300,abort=True):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);p=folder/'config.json';cfg=dict(output=str((folder/'trace.jsonl').resolve()),seed=seed,startup_draws=2,positions=positions,reference=str(Path(reference).resolve()) if reference else '',continue_after_prefix=continuation,candidate_x=x,future_seed=future,max_seconds=seconds,max_ticks=25000,max_drops=600,abort_on_mismatch=abort)
    p.write_text(json.dumps(cfg,indent=2));return p

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--prefix',type=int,default=295);p.add_argument('--seconds',type=float,default=300);p.add_argument('--reference',type=Path);p.add_argument('--candidate-x',type=float);p.add_argument('--future-seed',type=int,default=9101);p.add_argument('--keep-after-mismatch',action='store_true');a=p.parse_args()
    seed,positions,_=source_positions(a.source);positions=positions[:a.prefix]
    conf=config(a.output,seed,positions,a.reference,a.candidate_x is not None,a.candidate_x if a.candidate_x is not None else .5,a.future_seed,a.seconds,not a.keep_after_mismatch);run(conf,a.exe,timeout=a.seconds+30)

if __name__=='__main__':main()
