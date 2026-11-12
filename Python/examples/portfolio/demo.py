"""Public, Unity-free inference sample. Demonstrates probabilities, not game strength."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from learned_rollout import GRID,probabilities


def run():
    model=json.loads((HERE/'policy.json').read_text(encoding='utf8'))
    sample=json.loads((HERE/'observation.json').read_text(encoding='utf8'))
    before=copy.deepcopy(sample)
    p=probabilities(model,sample)
    if sample!=before or abs(float(sum(p))-1)>1e-10:
        raise ValueError('Mutation or invalid probabilities')
    return dict(kind='rollout-policy-demo-not-MCTS-or-physics',
                source='recorded public board; demonstration, not independent evaluation',
                current_fruit=sample['state']['current_fruit']['type'],
                public_next=sample['state']['next_fruit_type'],
                candidates=[dict(x=x,probability=float(y)) for x,y in zip(GRID,p)],
                policy_argmax_x=GRID[int(p.argmax())],
                model_sha256=hashlib.sha256((HERE/'policy.json').read_bytes()).hexdigest(),
                note='The real MCTS also searches physics and filters immediate GO. This demo does neither.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');a=parser.parse_args()
    r=run()
    if a.json:print(json.dumps(r,indent=2))
    else:
        print('Recorded-board rollout policy | fixed five candidates')
        for c in r['candidates']:print(f"x={c['x']:.2f}  probability={c['probability']:.4f}")
        print('Policy argmax:',r['policy_argmax_x'])
        print(r['note'])
