"""Add an explicit source action index without rewriting the frozen feature files."""
import json
from collections import defaultdict
from pathlib import Path
from suika_ai.policy_data import teacher
from qv_experiment import ROOT,write

def main():
    records=json.loads((ROOT/'latest/records.json').read_text());groups=defaultdict(list)
    for i,r in enumerate(records):groups[r['source']].append((i,r))
    result=[]
    for source,wanted in groups.items():
        n=0
        with Path(source).open() as f:
            for l in f:
                row=json.loads(l)
                if row['event']!='transition' or row['info'].get('drop_success') is not True:continue
                try:s,t=teacher(row)
                except (KeyError,ValueError,TypeError):continue
                index,r=wanted[n]
                if r['score']!=s['state']['score'] or abs(r['selected_x']-t['selected_x'])>1e-6:raise ValueError('Source row alignment changed')
                result.append(dict(record=index,episode=r['episode'],action_id=row['action_id']));n+=1
        if n!=len(wanted):raise ValueError('Source count changed')
    write(ROOT/'latest/observed_action_index.json',sorted(result,key=lambda r:r['record']));print('indexed',len(result),flush=True)

if __name__=='__main__':main()
