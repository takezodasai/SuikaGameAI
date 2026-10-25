"""Versioned checkpoints with atomic pointers, SHA256 validation and corruption fallback."""
import hashlib
import json
import os
import pickle
from pathlib import Path
import uuid
import torch

def atomic_bytes(path,data):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
def atomic_json(path,value):atomic_bytes(path,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'))

def save_checkpoint(directory,payload,is_best=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    stem=f"e{payload['epoch']:05d}_u{payload['updates']:09d}_"+uuid.uuid4().hex[:8]
    target=directory/(stem+'.pt');temporary=directory/(stem+'.pt.tmp')
    with temporary.open('xb') as stream:torch.save(payload,stream);stream.flush();os.fsync(stream.fileno())
    sha=hashlib.sha256(temporary.read_bytes()).hexdigest();os.replace(temporary,target)
    meta=dict(file=target.name,sha256=sha,updates=payload['updates'],epoch=payload['epoch'],best_eligible=is_best)
    atomic_json(directory/(stem+'.meta.json'),meta)
    atomic_json(directory/'latest.json',meta)
    if is_best:atomic_json(directory/'best.json',meta)
    return target

def load_checkpoint(directory,which='latest'):
    directory=Path(directory);candidates=[]
    if which in ('latest','best'):
        try:candidates.append(json.loads((directory/(which+'.json')).read_text(encoding='utf-8')))
        except (OSError,ValueError):pass
        for p in sorted(directory.glob('*.meta.json'),reverse=True):
            try:
                meta=json.loads(p.read_text(encoding='utf-8'))
                if which!='best' or meta.get('best_eligible'):candidates.append(meta)
            except (OSError,ValueError):continue
    else:
        p=Path(which).resolve();candidates=[json.loads(p.with_suffix('.meta.json').read_text(encoding='utf-8'))];directory=p.parent
    errors=[];seen=set()
    for meta in candidates:
        try:
            name=meta['file']
            if Path(name).name!=name or not name.endswith('.pt'):raise ValueError('invalid checkpoint filename')
            if name in seen:continue
            seen.add(name);path=directory/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('checkpoint hash mismatch')
            payload=torch.load(path,map_location='cpu',weights_only=True)
            if payload.get('checkpoint_version')!=1:raise ValueError('unknown checkpoint version')
            if errors:print('Checkpoint fallback: '+str(path)+'; rejected '+str(errors),flush=True)
            return payload,path
        except (OSError,ValueError,KeyError,RuntimeError,EOFError,pickle.UnpicklingError) as error:errors.append(str(error))
    raise ValueError('No valid checkpoint: '+str(errors))
