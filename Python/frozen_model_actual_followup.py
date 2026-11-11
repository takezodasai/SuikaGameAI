"""Wait only on our supervisor, then execute bounded predeclared follow-ups."""
import argparse,ctypes,json,subprocess,time
from pathlib import Path
import frozen_model_actual_play as play
import collection_concurrency_probe as probe
from frozen_model_actual_play import ROOT,write

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-pid',type=int,required=True);a=parser.parse_args()
    handle=ctypes.windll.kernel32.OpenProcess(0x100000,False,a.wait_pid)
    if handle:
        try:
            while ctypes.windll.kernel32.WaitForSingleObject(handle,1000)==258:pass
        finally:ctypes.windll.kernel32.CloseHandle(handle)
    if probe.active_players():write(ROOT/'followup_blocked.json',dict(reason='Active unrelated Player after owned supervisor exit'));return
    models=play.Models();first=json.loads((ROOT/'seed_882610501/A/result.json').read_text())
    if first['reason']=='wall_limit':
        play.EXE=Path('Unity/Builds/FrozenModels_03/SuikaGameAI.exe')
        play.run_game(ROOT/'recovery/A',dict(seed=882610501,mode='A',max_seconds=900,max_drops=600),models,port=44640)
    play.EXE=Path('Unity/Builds/FrozenModels_02/SuikaGameAI.exe')
    import frozen_model_actual_branches
    frozen_model_actual_branches.main()
    import frozen_model_heavy_concurrency
    frozen_model_heavy_concurrency.main()
    # Ordinary native regression path, without installing the new opt-in agent.
    for flag,name in [('-suikaRulesSelfTest','rules'),('-suikaMctsSelfTest','mcts'),('-suikaPathSelfTest','path')]:
        if probe.active_players():break
        output=ROOT/f'native_{name}.json';log=ROOT/f'native_{name}.log';started=time.monotonic()
        cmd=[str(Path('Unity/Builds/FrozenModels_03/SuikaGameAI.exe').resolve()),'-batchmode','-nographics','--suika-audio','0','--suika-listen-port','44720','--suika-python-port','44721',flag,str(output.resolve()),'-logFile',str(log.resolve())]
        p=subprocess.Popen(cmd,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        try:p.wait(timeout=60)
        finally:
            if p.poll() is None:p.terminate();p.wait(10)
        write(ROOT/f'native_{name}_execution.json',dict(exit_code=p.returncode,seconds=time.monotonic()-started))
    import analyze_frozen_model_actual
    analyze_frozen_model_actual.main()
    write(ROOT/'followup_complete.json',dict(done=True))

if __name__=='__main__':main()
