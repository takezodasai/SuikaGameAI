"""Single isolated fixed5/128/depth4 experiment, with optional first-action override."""
import argparse,json,math
from pathlib import Path
from watermelon_lab import ROOT
from staged_action_experiment import trial


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--fixture',type=Path);g.add_argument('--normal-seed',type=int)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['baseline','staged'],required=True)
    p.add_argument('--exe',type=Path,default=ROOT/'Unity/Builds/StagedAction_02/SuikaGameAI.exe')
    p.add_argument('--future-seed',type=int,default=2026103106);p.add_argument('--first-x',type=float,default=-1)
    p.add_argument('--seconds',type=float,default=45);p.add_argument('--drops',type=int,default=3);a=p.parse_args()
    if not math.isfinite(a.first_x) or a.first_x!=-1 and not 0<=a.first_x<=1:raise ValueError('Illegal first action')
    if a.first_x>=0 and a.mode!='baseline':raise ValueError('First-only diagnostic must use the common baseline continuation')
    if not 0<a.seconds<=600 or not 1<=a.drops<=1000:raise ValueError('Bounded trial required')
    if not 0<=a.future_seed<=2147483647 or a.normal_seed is not None and not 0<=a.normal_seed<=2147483647:raise ValueError('Seed out of range')
    if a.normal_seed is not None:
        reserved=json.loads((ROOT/'Python/outputs/qv_compare_01/latest/test_reservation_manifest.json').read_text())['episodes']
        if a.normal_seed in {e['seed'] for e in reserved}:raise ValueError('Reserved Test seed')
    trial(a.output,a.exe.resolve(),a.fixture,a.mode,a.future_seed,a.seconds,a.first_x,a.drops,a.normal_seed)


if __name__=='__main__':main()
