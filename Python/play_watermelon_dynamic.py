"""One bounded headless continuation; defaults outside this tool are unchanged."""
import argparse
import json
from pathlib import Path
from watermelon_lab import ROOT
from compare_watermelon_dynamic import run_game


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['baseline','refined'],required=True)
    p.add_argument('--exe',type=Path,default=ROOT/'Unity/Builds/WatermelonDynamic_02/SuikaGameAI.exe')
    p.add_argument('--future-seed',type=int,default=2026103103);p.add_argument('--seconds',type=float,default=480)
    p.add_argument('--drops',type=int,default=1000);a=p.parse_args()
    if not 0<a.seconds<=600 or not 1<=a.drops<=1000:raise ValueError('Bounded continuation required')
    fixture=json.loads(a.fixture.read_text(encoding='utf8'))
    if not any(f['type']==10 for f in fixture['fruits']):raise ValueError('This CLI is for post-watermelon fixtures')
    run_game(a.output,a.fixture.resolve(),a.mode,a.future_seed,a.exe.resolve(),a.seconds,a.drops)


if __name__=='__main__':main()
