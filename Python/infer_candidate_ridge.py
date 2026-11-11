"""Infer from a public snapshot and the prevalidated canonical A/B candidate pair."""
import argparse,json,time
from pathlib import Path
from candidate_ridge import infer_public

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True);p.add_argument('--input',type=Path,required=True);a=p.parse_args()
    m=json.loads(a.model.read_text(encoding='utf8'));row=json.loads(a.input.read_text(encoding='utf8'));start=time.perf_counter()
    result=infer_public(m,row.get('input',row));result['inference_ms']=(time.perf_counter()-start)*1000
    print(json.dumps(result,indent=2))
