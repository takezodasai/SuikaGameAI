"""Short isolated native regression tests, no collection or model tuning."""
import json,subprocess
from pathlib import Path
from watermelon_lab import ROOT,write
from compare_watermelon_dynamic import active_players

def main():
    if active_players():raise RuntimeError('Leave active collection alone')
    p=ROOT/'Python/outputs/learned_rollout_01';exe=ROOT/'Unity/Builds/LearnedRollout_03/SuikaGameAI.exe'
    for flag,name in [('-suikaRolloutParity','parity'),('-suikaRulesSelfTest','rules'),('-suikaMctsSelfTest','mcts'),('-suikaPathSelfTest','path')]:
        result=p/(name+'_result_03.json')
        if result.exists():raise RuntimeError('Protect prior native result')
        arg=p/'parity_config_03.json' if name=='parity' else result
        cmd=[str(exe),'-batchmode','-nographics','--suika-audio','0','--suika-listen-port','43750','--suika-python-port','43751',flag,str(arg),'-logFile',str(p/(name+'_03.log'))]
        r=subprocess.run(cmd,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        data=json.loads(result.read_text());assert r.returncode==0 and not data.get('error'),data.get('error');print(name, data.get('checks',len(data.get('passed',[]))),flush=True)

if __name__=='__main__':main()
