"""STEP8-AE headless overnight data collection. No learning or AI comparison."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.overnight_collection import collect,summarize,DEFAULT_PROFILES

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true');p.add_argument('--summary',action='store_true');p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step8AE/SuikaGameAI.exe'));p.add_argument('--workers',type=int,default=2);p.add_argument('--hours',type=float,default=8);p.add_argument('--max-jobs',type=int,default=1000);p.add_argument('--max-steps',type=int,default=100000);p.add_argument('--think-seconds',type=float,default=240);p.add_argument('--communication-timeout',type=float,default=720);p.add_argument('--game-seed',type=int,default=780000);p.add_argument('--schedule-seed',type=int,default=20261027);p.add_argument('--base-port',type=int,default=40700);p.add_argument('--profiles',type=Path);p.add_argument('--shutdown',choices=['boundary','drain'],default='boundary');a=p.parse_args()
 if a.summary:result=summarize(a.output)
 else:
  cfg=dict(exe=str(a.exe.resolve()),workers=a.workers,hours=a.hours,max_jobs=a.max_jobs,max_steps=a.max_steps,think_seconds=a.think_seconds,communication_timeout=a.communication_timeout,game_seed=a.game_seed,schedule_seed=a.schedule_seed,base_port=a.base_port,profiles=json.loads(a.profiles.read_text(encoding='utf-8-sig')) if a.profiles else DEFAULT_PROFILES,shutdown=a.shutdown)
  result=collect(cfg,a.output,a.resume)
 print(json.dumps({k:v for k,v in result.items() if k!='games'},indent=2))
if __name__=='__main__':main()
