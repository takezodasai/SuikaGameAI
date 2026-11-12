"""Bounded observer on/off and old/new Player compatibility check; never natural-GO collection."""
import argparse
import copy
import json
import subprocess
from pathlib import Path
from watermelon_lab import ROOT, write, sha
from compare_watermelon_dynamic import active_players


def run(fixture,model,output,drops=3):
    if active_players():raise RuntimeError('Existing Player left untouched')
    if not 1<=drops<=3:raise ValueError('short verification only')
    fixture,model,output=map(lambda p:Path(p).resolve(),(fixture,model,output))
    output.mkdir(exist_ok=False,parents=True);traces={}
    old=ROOT/'Unity/Builds/PolicySelfPlay_01/SuikaGameAI.exe'
    new=ROOT/'Unity/Builds/MaterialCurriculum_01/SuikaGameAI.exe'
    for name,exe,enabled in [('old_off',old,False),('new_off',new,False),('new_on',new,True)]:
        folder=output/name;folder.mkdir()
        cfg=dict(fixture=str(fixture),normal_start=False,output=str(folder/'trace.jsonl'),policy_model=str(model),
                 mode='learned',mixture=.5,material_progress=enabled,final_selection='legacy',
                 game_seed=1283111101,future_seed=1283111101,search_seed=8191,iterations=256,depth=4,
                 max_drops=drops,max_seconds=45,first_x=-1)
        write(folder/'config.json',cfg)
        args=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-events','1',
              '--suika-listen-port','44980','--suika-python-port','44981','-suikaRuntimeProbe',str(folder/'runtime.jsonl'),
              '-suikaPolicySelfPlayLab',str(folder/'config.json'),'-logFile',str(folder/'player.log')]
        result=subprocess.run(args,timeout=75,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError(name+' failed')
        rows=[json.loads(s) for s in (folder/'trace.jsonl').open(encoding='utf8')]
        if not rows or rows[-1]['evt']!='end':raise RuntimeError('Missing short-test end')
        traces[name]=rows
    def physical_state(s):
        s=copy.deepcopy(s)
        for f in s['fruits']:f.pop('id',None)
        s['fruits'].sort(key=lambda f:(f['type'],f['x'],f['y']))
        return s
    def signature(rows):
        return [dict(evt=r['evt'],tick=r['tick'],score=r['score'],state=physical_state(r['state']),
                     command=r['command'],rng=r['rng'],root=(r['search'] or {}).get('root')) for r in rows]
    old_equal=signature(traces['old_off'])==signature(traces['new_off'])
    on_equal=signature(traces['new_off'])==signature(traces['new_on'])
    presence=all(((r.get('raw_events') or {}).get('materials') or {}).get('known') for r in traces['new_on'])
    # JsonUtility may serialize a null nested snapshot as default fields (known=false).
    absence=all(not ((r.get('raw_events') or {}).get('materials') or {}).get('known') for name in ('old_off','new_off') for r in traces[name])
    report=dict(old_new_public_and_search_equal=old_equal,observer_on_off_public_and_search_equal=on_equal,
        compared='every recorded phase: score, public state excluding generated IDs, command/drop ticks, actual RNG, root visits/values',
        observer_known_only_when_enabled=presence and absence,
        drops=drops,long_run_verified=False,exe_sha256={k:sha(p) for k,p in [('old',old),('new',new)]},
        assembly_sha256={k:sha(p.parent/'SuikaGameAI_Data/Managed/Assembly-CSharp.dll') for k,p in [('old',old),('new',new)]})
    write(output/'verification.json',report);print(json.dumps(report,indent=2))
    if not old_equal or not on_equal or not presence or not absence:raise RuntimeError('Short prefix diverged or observer missing; see traces; no exactness claim')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--drops',type=int,default=3)
    a=p.parse_args();run(a.fixture,a.model,a.output,a.drops)
