"""Render an honest portfolio illustration from committed observations and aggregates."""
import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ASSETS=ROOT/'docs/assets'


def sha(p):
    data=Path(p).read_bytes()
    # Git/Windows may convert text newlines; content checks must remain portable.
    if Path(p).suffix in ('.py','.json','.svg'):data=data.replace(b'\r\n',b'\n')
    return hashlib.sha256(data).hexdigest()


def check():
    manifest=json.loads((ASSETS/'overview_manifest.json').read_text())
    for path,value in {**manifest['sources'],**manifest['assets']}.items():
        if sha(ROOT/path)!=value:raise ValueError('Stale portfolio asset: '+path)
    return True


def render():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse
    s=json.loads((HERE/'observation.json').read_text())['state']
    results=json.loads((HERE/'results.json').read_text())['cohorts']
    count=sum(r['games'] for r in results);best=max(r['max_score'] for r in results)
    watermelons=sum(r['new_watermelons'] for r in results)
    bg='#111c29';ink='#edf5f3';muted='#a4b7c4';accent='#7be0b4'
    plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','svg.hashsalt':'suika-portfolio-v1'})
    fig=plt.figure(figsize=(14,7),facecolor=bg)
    ax=fig.add_axes([.035,.12,.38,.76]);ax.set_facecolor('#192b3a')
    left,right,bottom,top=s['geometry']
    colors=['#e96771','#f0b1ba','#a88bd2','#f3ae66','#df8c4b','#cc6469','#dabf68','#e6a9bd','#e5cd61','#a6c977','#379568']
    for f in sorted(s['fruits'],key=lambda f:f['type']):
        w=f['half_width']*2;h=f['half_height']*2
        ax.add_patch(Ellipse((f['x'],f['y']),w,h,angle=0,facecolor=colors[f['type']],edgecolor=bg,lw=1.3))
        if f['type'] in (8,9,10):ax.text(f['x'],f['y'],{8:'P',9:'M',10:'W'}[f['type']],ha='center',va='center',color=bg,fontweight='bold',fontsize=14)
    ax.axhline(top,color='#ed8e8e',ls=(0,(4,3)),lw=1.3)
    ax.set_xlim(left-.12,right+.12);ax.set_ylim(bottom-.12,top+.34);ax.set_aspect('equal');ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():spine.set_color('#527084')
    ax.set_title('RECORDED PUBLIC OBSERVATION',color=muted,fontsize=10,pad=12,loc='left')
    fig.text(.46,.86,'SUIKA GAME AI',color=ink,fontsize=30,fontweight='bold')
    fig.text(.46,.78,'Physics search. Self-play. Learning.',color=accent,fontsize=15)
    fig.text(.46,.65,'Unity / C#  +  Python',color=ink,fontsize=17)
    fig.text(.46,.53,'MCTS with isolated Physics2D predictions\nVersioned policies and auditable game outcomes',color=muted,fontsize=12,linespacing=1.8)
    for x,value,label in [(.46,str(count),'completed games'),(.64,f'{best:,}','best full-game score'),(.82,str(watermelons),'watermelons created')]:
        fig.text(x,.36,value,color=accent,fontsize=27,fontweight='bold')
        fig.text(x,.30,label,color=muted,fontsize=9)
    fig.text(.46,.18,'Double watermelon: not yet achieved',color=ink,fontsize=12)
    fig.text(.46,.12,'Descriptive totals from four sessions; not a paired comparison.',color=muted,fontsize=9)
    fig.text(.035,.035,'Board illustration from a real log; not a gameplay screenshot.  W = watermelon / M = melon / P = pineapple',color=muted,fontsize=8)
    ASSETS.mkdir(exist_ok=True)
    fig.savefig(ASSETS/'overview.png',dpi=140,facecolor=bg)
    fig.savefig(ASSETS/'overview.svg',facecolor=bg,metadata={'Date':None})
    svg=ASSETS/'overview.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf8').splitlines())+'\n',encoding='utf8',newline='\n')
    plt.close(fig)
    relative=lambda p:p.relative_to(ROOT).as_posix()
    sources=[HERE/'observation.json',HERE/'results.json',Path(__file__).resolve()]
    assets=[ASSETS/'overview.png',ASSETS/'overview.svg']
    (ASSETS/'overview_manifest.json').write_text(json.dumps(dict(sources={relative(p):sha(p) for p in sources},assets={relative(p):sha(p) for p in assets}),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args()
    if a.check:check();print('Portfolio assets match committed source data.')
    else:render();print('Rendered recorded-board portfolio overview.')
