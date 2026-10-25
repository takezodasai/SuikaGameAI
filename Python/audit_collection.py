"""Read-only STEP7-B collection totals, labels, rewards, seeds and metadata audit."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.collection_audit import audit,save_audit

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path)
    args=p.parse_args();result=audit(args.input)
    if args.output:save_audit(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['integrity_ok'] else 1

if __name__=='__main__':raise SystemExit(main())
