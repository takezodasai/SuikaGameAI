"""Four bounded fresh-process actual continuations; no learning or old log writes."""
import argparse,json,time
from pathlib import Path
from run_fresh_continuation import source_positions,config,run

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    # Root24 was verified separately; every continuation also verifies it itself.
    seed,positions,_=source_positions(a.source);positions=positions[:24]
    a.output.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    for future in [9101,9102]:
        for x in [0.,.37]:
            if time.monotonic()-start>600:return
            folder=a.output/f'branch24_f{future}_x{str(x).replace(".","p")}'
            conf=config(folder,seed,positions,a.reference,True,x,future,180)
            r=run(conf,a.exe,port=42050,timeout=210)
            if not r.get('end',{}).get('mc_return_known') or r['errors'] or r['first_mismatch']:
                print(json.dumps(dict(stopped='Do not expand invalid or high-cost pilot')),flush=True);return

if __name__=='__main__':main()
