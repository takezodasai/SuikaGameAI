"""Bounded single-fixture MCTS versus 81-path diagnostic. No gameplay mode change."""
import argparse,json,subprocess
from pathlib import Path
from analyze_two_step_probe import analyze

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',type=Path,default=Path('outputs/step8c_01/dense_safe_fixture.json'))
    p.add_argument('--exe',type=Path,default=Path('../Unity/Builds/Step6/SuikaGameAI.exe'));a=p.parse_args()
    if not a.fixture.is_file() or not a.exe.is_file():p.error('Fixture and built Player must exist')
    a.output.mkdir(parents=True,exist_ok=False);out=a.output.resolve()
    config=dict(output=str(out/'fixed.jsonl'),fixtures=[str(a.fixture.resolve())],scan=False,exhaustive=True,searches=[dict(policy='grid',candidates=n,iterations=i) for n,i in [(5,32),(9,32),(9,64)]])
    (out/'config.json').write_text(json.dumps(config),encoding='utf-8')
    child=subprocess.Popen([str(a.exe.resolve()),'-batchmode','-nographics','--suika-game-id','game_00','--suika-seed','751300','-suikaRuntimeProbe',str(out/'runtime.jsonl'),'-suikaCandidateProbe',str(out/'config.json'),'-logFile',str(out/'player.log')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        if child.wait(timeout=90):raise RuntimeError('Diagnostic Player failed; see player.log')
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=5)
    report=analyze(out/'fixed.jsonl')
    with (out/'analysis.json').open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,ensure_ascii=False,allow_nan=False)
    import csv
    with (out/'pairs.csv').open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(report['exhaustive']['outcomes'][0]));w.writeheader();w.writerows(report['exhaustive']['outcomes'])
    print(json.dumps(dict(output=str(out),best=report['exhaustive']['outcomes'][report['exhaustive']['selected_path']],known=report['known_pair']),ensure_ascii=False))
if __name__=='__main__':main()
