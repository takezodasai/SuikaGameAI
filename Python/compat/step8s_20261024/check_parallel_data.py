"""Check duplicate actions, game mixing, and score/reward conservation offline."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from suika_ai.parallel_play import validate_run
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: python check_parallel_data.py outputs/parallel_run")
    print(json.dumps(validate_run(sys.argv[1]),ensure_ascii=False,indent=2))
