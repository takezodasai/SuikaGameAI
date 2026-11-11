import argparse,json
from pathlib import Path
from candidate_ridge import train

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    train(json.loads(a.protocol.read_text(encoding='utf8')),a.output)
