"""Control the collector's presentation inbox; no competing UDP receiver."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from suika_ai.presentation import write_control
import json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("output",type=Path)
g=p.add_mutually_exclusive_group();g.add_argument("--game",type=int);g.add_argument("--others",action="store_true");g.add_argument("--all",action="store_true")
p.add_argument("--audio",choices=("on","off"));p.add_argument("--video",choices=("on","off"))
a=p.parse_args();manifest=json.loads((a.output/"run.json").read_text(encoding="utf-8"))
games=[w["game_id"] for w in manifest["workers"] if not a.others or w["game_id"]!="game_00"] if a.game is None else [f"game_{a.game:02d}"]
print(json.dumps(write_control(a.output,games,None if a.audio is None else a.audio=="on",None if a.video is None else a.video=="on")))
print("Queued; inspect controls.jsonl for Unity acknowledgment. The collection must still be running.")
