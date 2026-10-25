"""STEP8-W opt-in, one Player, bounded exploratory play. Default: eight actions."""
import argparse,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step8W/SuikaGameAI.exe'))
 p.add_argument('--mode',choices=['fixed','time','adaptive'],default='adaptive');p.add_argument('--iterations',type=int,default=32);p.add_argument('--max-iterations',type=int,default=512);p.add_argument('--time-limit',type=float,default=5)
 p.add_argument('--depth',type=int,default=4);p.add_argument('--auto-depth',action='store_true');p.add_argument('--auto-depth-min',type=int,default=2);p.add_argument('--auto-depth-max',type=int,default=8)
 p.add_argument('--full-trace',action='store_true');p.add_argument('--candidates',type=int,choices=[5,9],default=5);p.add_argument('--widening',action='store_true');p.add_argument('--max-steps',type=int,default=8);p.add_argument('--seed',type=int,default=762100);p.add_argument('--search-seed',type=int,default=8191);p.add_argument('--base-port',type=int,default=39900);a=p.parse_args()
 s=validate_planning_settings(dict(ai_mode='mcts',mcts_extended_budget=True,mcts_full_trace=a.full_trace,mcts_budget_mode=a.mode,mcts_iterations=a.iterations,mcts_max_iterations=a.max_iterations,mcts_time_limit_seconds=a.time_limit,mcts_max_depth=a.depth,mcts_auto_depth=a.auto_depth,auto_depth_min=a.auto_depth_min,auto_depth_max=a.auto_depth_max,candidate_count=a.candidates,mcts_widening=a.widening,mcts_seed=a.search_seed))
 run_parallel(a.exe,a.output,games=1,episodes=1,max_steps=a.max_steps,base_port=a.base_port,seed=a.seed,headless=True,settings=s,main_audio=False,require_metadata=True,expected_go_ratio=.83,expected_rules_version='step8e-all-fruit-go-v2',episode_events=True)
if __name__=='__main__':main()
