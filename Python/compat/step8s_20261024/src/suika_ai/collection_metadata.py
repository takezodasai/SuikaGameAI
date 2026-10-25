"""Read-only telemetry catalog. Fixed environment + runtime physics profiles once/run."""
import hashlib
import json
import os
from pathlib import Path


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def atomic_metadata(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.pending')
    with temporary.open('wb') as f:
        f.write(canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)


class CollectionMetadata:
    def __init__(self,env,path,require=False,expected_go_ratio=None,enabled=True,expected_rules_version=None):
        self.env,self.path,self.require,self.expected_go_ratio=env,Path(path),require,expected_go_ratio
        self.enabled=enabled;self.expected_rules_version=expected_rules_version
        if not enabled and (require or expected_go_ratio is not None or expected_rules_version is not None):raise ValueError("Metadata required for environment verification")
        self.fixed=None;self.profiles={};self.environment_id=None

    def refresh(self):
        value=self.env.get_environment()
        profiles=value.pop('physics_profiles',[])
        environment_id=hashlib.sha256(canonical(value)).hexdigest()
        if self.environment_id is not None and environment_id!=self.environment_id:raise ValueError('Environment changed during collection')
        if self.expected_go_ratio is not None and abs(value['game_over_screen_ratio']-self.expected_go_ratio)>1e-5:
            raise ValueError('Player GameOverScreenRatio differs from --expected-go-ratio; rebuild the Player')
        if self.expected_rules_version is not None and value.get('rules_version')!=self.expected_rules_version:
            raise ValueError('Player rules_version differs from comparison; rebuild the Player')
        self.fixed=value;self.environment_id=environment_id
        for profile in profiles:
            key=profile['id']
            if key in self.profiles and self.profiles[key]!=profile:raise ValueError('Physics profile identity conflict')
            self.profiles[key]=profile
        atomic_metadata(self.path,dict(schema_version=1,environment_id=environment_id,environment=value,physics_profiles=self.profiles))

    def attach(self,state):
        if not self.enabled:return {k:v for k,v in state.items() if k!="environment"}
        if self.fixed is None:
            if state.get('metadata_schema_version')==1:self.refresh()
            elif self.require or self.expected_go_ratio is not None:raise ValueError('Old Player lacks training metadata; rebuild STEP6 Player')
        if self.fixed is not None:
            missing={f.get('physics_profile_id') for f in state['fruits'] if f.get('observation_metadata_known')} - self.profiles.keys()
            if missing:self.refresh()
            if any(f.get('observation_metadata_known') and f.get('physics_profile_id') not in self.profiles for f in state['fruits']):raise ValueError('Missing runtime physics profile')
        clean={k:v for k,v in state.items() if k!='environment'}
        clean['environment_id']=self.environment_id
        return clean
