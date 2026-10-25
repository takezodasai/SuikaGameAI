"""1..4 game Windows latest-frame Viewer; stdlib only. Never receives gameplay UDP."""
import argparse
import json
import mmap
from pathlib import Path
import struct
import time

WIDTH,HEIGHT,HEADER=640,360,128
CAPACITY=HEADER+WIDTH*HEIGHT*4


def read_frame(mapping,previous=0):
    first=struct.unpack_from("<q",mapping,0)[0]
    if not first or first&1 or first==previous:return None
    raw=mapping[:CAPACITY]
    last=struct.unpack_from("<q",mapping,0)[0]
    if last!=first or last&1:return None
    version,width,height=struct.unpack_from("<iii",raw,8)
    if (version,width,height)!=(1,WIDTH,HEIGHT):return None
    captured,published=struct.unpack_from("<qq",raw,24)
    score,go,frame,enabled=struct.unpack_from("<iiii",raw,40)
    return dict(sequence=last,captured_ms=captured,published_ms=published,score=score,
        game_over=bool(go),frame=frame,enabled=bool(enabled),capture_cpu_ms=struct.unpack_from("<d",raw,56)[0],
        readback_callback_ms=struct.unpack_from("<d",raw,64)[0],publish_cpu_ms=struct.unpack_from("<d",raw,72)[0],rgba=raw[HEADER:])


def ppm(rgba,flip=False):
    if len(rgba)!=WIDTH*HEIGHT*4:raise ValueError("Invalid video size")
    rgb=bytearray(WIDTH*HEIGHT*3)
    rgb[0::3]=rgba[0::4];rgb[1::3]=rgba[1::4];rgb[2::3]=rgba[2::4]
    if flip:
        stride=WIDTH*3;rgb=b"".join(rgb[i:i+stride] for i in range((HEIGHT-1)*stride,-1,-stride))
    return b"P6\n%d %d\n255\n"%(WIDTH,HEIGHT)+rgb


def tile_positions(count):
    if type(count) is not int or not 1<=count<=4:raise ValueError("Viewer supports 1..4 games")
    return [(i//(1 if count==1 else 2),i%(1 if count==1 else 2)) for i in range(count)]


def fitted_size(width,height):
    """Keep aspect ratio; Tk scales on a small rational grid without dependencies."""
    from math import gcd
    numerator=max(1,int(min(max(1,width)/WIDTH,max(1,height)/HEIGHT)*8))
    divisor=gcd(numerator,8)
    return numerator//divisor,8//divisor


class ViewerLayout:
    """Only rearranges video widgets. Never sends a game action or Reset."""
    def __init__(self,root,toolbar,grid,tiles):
        import tkinter as tk
        self.root,self.grid,self.tiles=root,grid,tiles
        self.selected=None;self.fullscreen=False
        self.buttons={}
        for game,text in [(None,"一覧")]+[(t["game"],t["game"]) for t in tiles]:
            button=tk.Button(toolbar,text=text,command=lambda value=game:self.show(value))
            button.pack(side="left");self.buttons[game]=button
        tk.Button(toolbar,text="全画面 (F11)",command=self.toggle_fullscreen).pack(side="left")
        for tile in tiles:
            tile["label"].bind("<Double-Button-1>",lambda event,game=tile["game"]:self.show(None if self.selected==game else game))
        root.bind("<F11>",self.toggle_fullscreen)
        root.bind("<Escape>",self.leave_fullscreen)
        self.show(None)

    def show(self,game=None):
        if game is not None and game not in self.buttons:raise ValueError("Video source is not configured")
        self.selected=game
        visible=[t for t in self.tiles if game is None or t["game"]==game]
        for i in range(2):
            self.grid.rowconfigure(i,weight=0,minsize=0,uniform="")
            self.grid.columnconfigure(i,weight=0,minsize=0,uniform="")
        for tile in self.tiles:tile["box"].grid_remove()
        for tile,(row,column) in zip(visible,tile_positions(len(visible))):
            self.grid.rowconfigure(row,weight=1,uniform="video")
            self.grid.columnconfigure(column,weight=1,uniform="video")
            tile["box"].grid(row=row,column=column,padx=2,pady=2,sticky="nsew")
        for key,button in self.buttons.items():button.configure(relief="sunken" if key==game else "raised")

    def toggle_fullscreen(self,event=None):
        self.fullscreen=not self.fullscreen
        self.root.attributes("-fullscreen",self.fullscreen)
        return "break"

    def leave_fullscreen(self,event=None):
        self.fullscreen=False;self.root.attributes("-fullscreen",False)
        return "break"

    def visible(self,tile):return self.selected is None or self.selected==tile["game"]

    def render(self,tile,source=None):
        import tkinter as tk
        if source is not None:tile["source_photo"]=source
        source=tile.get("source_photo")
        if source is None:return
        zoom,subsample=fitted_size(tile["label"].winfo_width()-4,tile["label"].winfo_height()-4)
        key=(zoom,subsample)
        if tile.get("image_scale")==key and tile.get("rendered_source") is source:return
        photo=tile.get("display_photo") if tile.get("image_scale")==key else None
        if photo is None:photo=tk.PhotoImage(master=self.root)
        self.root.tk.call(str(photo),"copy",str(source),"-zoom",zoom,zoom,"-subsample",subsample,subsample)
        if getattr(tile["label"],"image",None) is not photo:tile["label"].configure(image=photo)
        tile["label"].image=photo;tile["display_photo"]=photo
        tile["image_scale"]=key;tile["rendered_source"]=source


def viewer_sources(manifest):
    from .presentation import configured_video_maps
    maps=configured_video_maps(manifest)
    if not isinstance(maps,dict) or not 1<=len(maps)<=4:raise ValueError("Run must configure 1..4 video games")
    games={w["game_id"] for w in manifest["workers"]}
    if not set(maps)<=games or any(not isinstance(v,str) or not v for v in maps.values()) or len(set(maps.values()))!=len(maps):
        raise ValueError("Invalid/duplicate video sources")
    return list(maps.items())


class FrameMetrics:
    """Counters persist; distributions are bounded for long debug sessions."""
    def __init__(self):
        from collections import deque
        self.delays=deque(maxlen=4096);self.conversions=deque(maxlen=4096)
        self.transfer=deque(maxlen=4096);self.read_costs=deque(maxlen=4096);self.ages=deque(maxlen=4096);self.poll_gaps=deque(maxlen=4096);self.last_poll=None
        self.count=0;self.skipped=0;self.last_frame=0;self.first=None;self.last=None
    def add(self,frame,delay,conversion,now):
        self.skipped+=max(0,frame-self.last_frame-1) if self.last_frame else 0
        self.last_frame=frame;self.count+=1;self.delays.append(delay);self.conversions.append(conversion);self.last=now
        if self.first is None:self.first=now
    def observe(self,now,age_ms,read_ms):
        if self.last_poll is not None:self.poll_gaps.append((now-self.last_poll)*1000)
        self.last_poll=now;self.read_costs.append(read_ms)
        if age_ms is not None:self.ages.append(age_ms)
    def result(self,elapsed):
        def stats(values):
            if not values:return None
            ordered=sorted(values);n=len(ordered)
            return dict(mean=sum(ordered)/n,p50=ordered[n//2],p95=ordered[min(n-1,int(n*.95))],maximum=ordered[-1])
        return dict(displayed=self.count,elapsed_seconds=elapsed,display_fps=self.count/elapsed if elapsed else 0,
            skipped=self.skipped,active_display_fps=(self.count-1)/(self.last-self.first) if self.first is not None and self.last>self.first else None,
            published_to_tk_submit_ms=stats(self.transfer),shared_memory_read_ms=stats(self.read_costs),held_frame_age_ms=stats(self.ages),viewer_poll_gaps_ms=stats(self.poll_gaps),
            capture_to_tk_submit_ms=stats(self.delays),conversion_and_tk_ms=stats(self.conversions),distribution_samples=len(self.delays),distribution_limit=4096)


def main():
    import tkinter as tk
    from .presentation import write_control
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--map",help="Legacy single-game map")
    source.add_argument("--run",type=Path,help="Collection directory containing run.json")
    parser.add_argument("--metrics",type=Path)
    parser.add_argument("--seconds",type=float,default=0,help="0: until closed")
    parser.add_argument("--metrics-interval",type=float,default=0,help="Opt-in periodic metrics for a new diagnostic run")
    parser.add_argument("--flip-y",action="store_true",help="Bottom-up backends only; DX11 needs no flip")
    args=parser.parse_args()
    manifest=json.loads((args.run/"run.json").read_text(encoding="utf-8")) if args.run else None
    sources=viewer_sources(manifest) if manifest else [("game_00",args.map)]
    root=tk.Tk();root.title(f"Suika Debug Viewer - {len(sources)} games")
    root.geometry(f"{min(1320,root.winfo_screenwidth()-80)}x{min(840,root.winfo_screenheight()-100)}")
    root.minsize(600,360)
    switches=tk.Frame(root);switches.pack(fill="x")
    toolbar=tk.Frame(root);toolbar.pack(fill="x")
    message=tk.Label(toolbar,text="Closing Viewer does not stop games");message.pack(side="left")
    others=[w["game_id"] for w in manifest["workers"] if w["game_id"]!="game_00"] if manifest else []
    def audio(enabled):
        try:
            write_control(args.run,others,audio=enabled)
            message.configure(text="Audio queued; confirmation: controls.jsonl")
        except (OSError,ValueError) as error:message.configure(text=str(error))
    for enabled,text in [(True,"Others audio ON"),(False,"Others audio OFF")]:
        tk.Button(toolbar,text=text,command=lambda value=enabled:audio(value),state="normal" if others else "disabled").pack(side="right")
    grid=tk.Frame(root);grid.pack(fill="both",expand=True);tiles=[];started=time.monotonic()
    try:
        for (game,name),(row,column) in zip(sources,tile_positions(len(sources))):
            box=tk.LabelFrame(grid,text=game,width=320,height=200);box.grid_propagate(False)
            box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            label=tk.Label(box,bg="black");label.grid(row=0,column=0,sticky="nsew");blank=tk.PhotoImage(width=1,height=1)
            label.configure(image=blank);label.image=blank
            status=tk.Label(box,text=f"{game} | waiting for frames");status.grid(row=1,column=0,sticky="ew")
            tiles.append(dict(game=game,box=box,mapping=mmap.mmap(-1,CAPACITY,tagname=name),previous=0,label=label,status=status,metrics=FrameMetrics(),last_display=started))
    except Exception:
        for tile in tiles:tile["mapping"].close()
        root.destroy();raise
    layout=ViewerLayout(root,switches,grid,tiles)
    last_metrics=[started]
    def save_metrics():
        elapsed=time.monotonic()-started
        result=dict(games={t['game']:t['metrics'].result(elapsed) for t in tiles},elapsed_seconds=elapsed,note="Tk submission, not photon latency; latest frame only")
        if args.metrics:
            temporary=args.metrics.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2),encoding='utf-8');temporary.replace(args.metrics)
        return result
    def update():
        begin=time.perf_counter()
        for tile in tiles:
            if not layout.visible(tile):continue
            layout.render(tile)
            read_begin=time.perf_counter();frame=read_frame(tile["mapping"],tile["previous"]);read_ms=(time.perf_counter()-read_begin)*1000
            if frame:tile["last_capture_ms"]=frame["captured_ms"]
            tile["metrics"].observe(time.monotonic(),time.time()*1000-tile["last_capture_ms"] if "last_capture_ms" in tile else None,read_ms)
            if frame:
                conversion=time.perf_counter();tile["previous"]=frame["sequence"]
                photo=tk.PhotoImage(data=ppm(frame.pop("rgba"),args.flip_y),format="PPM")
                layout.render(tile,photo)
                cost=(time.perf_counter()-conversion)*1000
                delay=time.time()*1000-frame["captured_ms"];now=time.monotonic();tile["last_display"]=now
                tile["metrics"].add(frame["frame"],delay,cost,now)
                tile["metrics"].transfer.append(time.time()*1000-frame["published_ms"])
                tile["status"].configure(text=f"{tile['game']} | score={frame['score']} | GO={frame['game_over']} | delay={delay:.0f}ms")
            elif time.monotonic()-tile["last_display"]>1:
                age=time.time()*1000-tile["last_capture_ms"] if "last_capture_ms" in tile else None
                tile["status"].configure(text=f"{tile['game']} | 更新待ち | 最終映像 {age:.0f}ms前" if age is not None else f"{tile['game']} | 映像待ち")
        if args.metrics_interval>0 and time.monotonic()-last_metrics[0]>=args.metrics_interval:
            save_metrics();last_metrics[0]=time.monotonic()
        if args.seconds and time.monotonic()-started>=args.seconds:root.destroy();return
        root.after(max(1,33-int((time.perf_counter()-begin)*1000)),update)
    root.after(33,update)
    try:root.mainloop()
    finally:
        elapsed=time.monotonic()-started;results={tile["game"]:tile["metrics"].result(elapsed) for tile in tiles}
        for tile in tiles:tile["mapping"].close()
        result=dict(games=results,elapsed_seconds=elapsed,note="Capture UTC to Tk submission, not photon latency; distributions use last 4096 frames/game")
        if len(results)==1:result.update(next(iter(results.values())))
        if args.metrics:args.metrics.write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result))

if __name__=="__main__":main()
