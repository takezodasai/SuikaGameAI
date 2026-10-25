"""Process presentation controls. Only the collector owns the gameplay receive socket."""
import json
import os
from pathlib import Path
import time
import uuid


def configured_video_maps(manifest):
    maps=manifest.get("video_maps")
    if maps is not None:return maps
    game=manifest.get("video_game");name=manifest.get("video_map")
    return {game:name} if game and name else {}


def write_control(output, games=None, audio=None, video=None):
    output=Path(output); manifest=json.loads((output/"run.json").read_text(encoding="utf-8"))
    valid={w["game_id"] for w in manifest["workers"]}
    targets=valid if games is None else set(games)
    if not targets or not targets<=valid: raise ValueError("Unknown/empty game selection")
    if audio is None and video is None: raise ValueError("Specify audio or video")
    for value in (audio,video):
        if value is not None and type(value) is not bool: raise ValueError("Expected on/off")
    if video is not None and any(g not in configured_video_maps(manifest) and g!=manifest.get("video_game") for g in targets):
        raise ValueError("Only configured video games support video control")
    # Unique files avoid lost updates between several simultaneous control clients.
    revision=time.time_ns(); token=uuid.uuid4().hex
    request=dict(run_id=manifest["run_id"],revision=revision,games=sorted(targets),audio=audio,video=video)
    inbox=output/"controls";inbox.mkdir(exist_ok=True)
    temporary=inbox/(token+".tmp"); final=inbox/(str(revision)+"_"+token+".json")
    temporary.write_text(json.dumps(request),encoding="utf-8");os.replace(temporary,final)
    return request


class PresentationControls:
    def __init__(self,output,run_id,envs,video_game):
        self.output=Path(output);self.run_id=run_id;self.envs=envs;self.video_games=set([video_game] if isinstance(video_game,str) else video_game or [])
        self.seen=set();self.desired={};self.last_send={};self.acked=set()
    def poll(self):
        inbox=self.output/"controls"
        for path in sorted(inbox.glob("*.json")):
            if path.name in self.seen: continue
            self.seen.add(path.name)
            try:
                row=json.loads(path.read_text(encoding="utf-8"))
                if row["run_id"]!=self.run_id or type(row["revision"]) is not int or not 0<row["revision"]<2**63:
                    raise ValueError("Wrong run/revision")
                if not row["games"] or not set(row["games"])<=self.envs.keys(): raise ValueError("Invalid games")
                changes={}
                for kind in ("audio","video"):
                    enabled=row.get(kind)
                    if enabled is None: continue
                    if type(enabled) is not bool: raise ValueError("Invalid enabled value")
                    for game in row["games"]:
                        if kind=="video" and game not in self.video_games: raise ValueError("Video not configured")
                        key=(game,kind)
                        if row["revision"]>self.desired.get(key,(0,False))[0]:changes[key]=(row["revision"],enabled)
                self.desired.update(changes)
                self.log(dict(event="requested",**row))
            except (ValueError,KeyError,TypeError) as error:self.log(dict(event="rejected",file=path.name,error=str(error)))
        for (game,kind),(revision,enabled) in self.desired.items():
            env=self.envs[game];state=env.last_state or {};key=(game,kind,revision)
            if state.get(kind+"_revision",0)>=revision:
                if key not in self.acked:
                    self.acked.add(key);self.log(dict(event="acknowledged",game_id=game,kind=kind,revision=revision,
                        enabled=state.get(kind+"_enabled"),error=state.get("video_error","") if kind=="video" else ""))
            elif time.monotonic()-self.last_send.get(key,0)>.5:
                if env.request_presentation(kind,enabled,revision):self.last_send[key]=time.monotonic()
    def log(self,row):
        with (self.output/"controls.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(dict(time=time.time(),**row))+"\n");stream.flush();os.fsync(stream.fileno())
