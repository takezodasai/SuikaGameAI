"""One visible normal-start game, using the bundled frozen rollout policy.

Standard library only; no private dataset, training, or model promotion.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'Python/examples/portfolio/latest_policy.json'


def read_model(path):
    model = json.loads(path.read_text(encoding='utf-8-sig'))
    if (model.get('version') != 'candidate-linear213-v1'
            or model.get('grid') != [0, .25, .5, .75, 1]
            or len(model.get('weights', [])) != 213
            or not all(math.isfinite(float(x)) for x in model['weights'])):
        raise ValueError('Unsupported policy; expected finite linear213 / fixed five candidates')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(folder, model, seed, max_drops, seconds):
    if not 1 <= max_drops <= 100000 or not 1 <= seconds <= 86400:
        raise ValueError('Invalid game safety limit')
    return dict(policy_model=str(model), output=str(folder / 'trace.jsonl'),
                mode='learned', normal_start=True, material_progress=True,
                mixture=.5, final_selection='legacy', game_seed=seed,
                future_seed=seed, search_seed=8191, iterations=256, depth=4,
                max_drops=max_drops, max_seconds=seconds, first_x=-1)


def command(exe, folder, seed, port):
    # Deliberately no -batchmode / -nographics: show the real Unity game.
    return [str(exe), '--suika-audio', '0', '--suika-events', '1',
            '--suika-seed', str(seed), '--suika-listen-port', str(port),
            '--suika-python-port', str(port + 1),
            '-suikaRuntimeProbe', str(folder / 'runtime.jsonl'),
            '-suikaPolicySelfPlayLab', str(folder / 'config.json'),
            '-logFile', str(folder / 'player.log')]


def summarize(rows, exit_code, interrupted=False):
    ends = [r for r in rows if r.get('evt') == 'end']
    end = ends[-1] if ends else {}
    natural = (exit_code == 0 and not interrupted and len(ends) == 1
               and end.get('natural_go') is True and not end.get('truncated')
               and end.get('reason') == 'natural_go'
               and not any(r.get('evt') == 'error' or r.get('error') for r in rows))
    return dict(natural_go=natural, exit_code=exit_code, interrupted=interrupted,
                reason=end.get('reason', 'interrupted' if interrupted else 'missing_end'),
                score=end.get('score'), drops=end.get('accepted_drops'),
                new_watermelons=end.get('new_watermelons'),
                double_watermelons=end.get('double_watermelons'),
                elapsed_seconds=end.get('elapsed_seconds'), training_started=False)


def write(path, value):
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=ROOT / 'Unity/Builds/MaterialView_01/SuikaGameAI.exe')
    parser.add_argument('--model', type=Path, default=MODEL)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-drops', type=int, default=100000)
    parser.add_argument('--game-seconds', type=int, default=14400)
    parser.add_argument('--port', type=int, default=45900)
    parser.add_argument('--dry-run', action='store_true', help='Validate and print config without launching/writing')
    args = parser.parse_args()
    exe, model = args.exe.resolve(), args.model.resolve()
    model_sha = read_model(model)
    seed = args.seed if args.seed is not None else secrets.randbelow(2000000000) + 1
    if not 0 <= seed <= 2147483647 or not 1024 <= args.port <= 65534:
        parser.error('Seed or port outside supported range')
    folder = (args.output or ROOT / 'Python/outputs' / (
        'public_gui_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(4))).resolve()
    cfg = config(folder, model, seed, args.max_drops, args.game_seconds)
    if args.dry_run:
        print(json.dumps(dict(config=cfg, model_sha256=model_sha, visible=True), indent=2))
        return
    if os.name != 'nt':
        parser.error('This launcher targets the Windows Unity Player')
    if not exe.is_file():
        parser.error('Player missing; build SuikaMaterialViewBuild.Build (see docs/GUI_MODEL_PREVIEW.md)')
    # Do not compete with the user's active collection. Never stop another Player.
    active = subprocess.run(['powershell', '-NoProfile', '-Command',
        "@(Get-Process -Name SuikaGameAI -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True, check=True, timeout=15)
    if int(active.stdout.strip()) != 0:
        parser.error('A SuikaGameAI Player is running; finish/stop it yourself before this demo')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', args.port))
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / 'config.json', cfg)
    cmd = command(exe, folder, seed, args.port)
    write(folder / 'launch.json', dict(command=cmd, model_sha256=model_sha,
        exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), seed=seed,
        purpose='interactive development demo; not independent performance evaluation'))
    print('Unity GUI | MCTS 256 / depth 4 / five candidates / learned rollout 50%', flush=True)
    print('Logs:', folder, '| Esc: stop in game; Ctrl+C: stop owned Player', flush=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1
    process = subprocess.Popen(cmd, startupinfo=startup,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    interrupted = False
    try:
        # Native wall limit is checked between decisions; allow a shutdown margin.
        process.wait(timeout=args.game_seconds + 720)
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        interrupted = True
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    rows = []
    trace = folder / 'trace.jsonl'
    if trace.exists():
        for line in trace.read_text(encoding='utf-8-sig').splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                interrupted = True  # Preserve partial file; never count it as a valid GO.
    result = summarize(rows, process.returncode, interrupted)
    write(folder / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if process.returncode != 0 or not any(r.get('evt') == 'end' for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
