"""Package the already-built Windows AI demo. Never uploads or rebuilds Players."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['AI-Demo.exe', 'UnityPlayer.dll', 'UnityCrashHandler64.exe',
         'demo_policy.json', 'demo_policy.sha256', 'model_provenance.json']
DIRS = ['AI-Demo_Data', 'MonoBleedingEdge']


def package(build, output):
    build, output = Path(build).resolve(), Path(output).resolve()
    for name in FILES + DIRS:
        if not (build / name).exists():
            raise FileNotFoundError('Incomplete Player: ' + name)
    if output.exists():
        raise FileExistsError(output)
    model_sha = hashlib.sha256((build / 'demo_policy.json').read_bytes()).hexdigest()
    if model_sha != (build / 'demo_policy.sha256').read_text().strip():
        raise ValueError('Model SHA256 mismatch')
    inputs = {name: build / name for name in FILES}
    for name in DIRS:
        for path in sorted((build / name).rglob('*')):
            if path.is_file() and path.suffix.lower() not in ('.pdb', '.mdb', '.log'):
                inputs[path.relative_to(build).as_posix()] = path
    inputs['START_HERE.txt'] = ROOT / 'docs/AI_DEMO_START_HERE.txt'
    inputs['DISTRIBUTION_NOTICE.md'] = ROOT / 'docs/AI_DEMO_DISTRIBUTION.md'
    manifest = dict(platform='Windows x64', model_sha256=model_sha,
                    policy_generation='gen_d9eb9e9bef0e',
                    files={name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for name, path in inputs.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in inputs.items():
            archive.write(path, 'SuikaGameAI-AI-Demo/' + name)
        archive.writestr('SuikaGameAI-AI-Demo/package_manifest.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC validation failed')
        for name, sha in manifest['files'].items():
            if hashlib.sha256(archive.read('SuikaGameAI-AI-Demo/' + name)).hexdigest() != sha:
                raise ValueError('Packaged file SHA mismatch: ' + name)
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(sha + '  ' + output.name + '\n', encoding='ascii')
    return dict(zip=str(output), sha256=sha, files=len(inputs), bytes=output.stat().st_size)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'Unity/Builds/StandaloneAiDemo_02')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.build, args.output), indent=2))
