import json
import tempfile
import unittest
from pathlib import Path
from prepare_material_curriculum import prepare_progress
from double_watermelon_learning import sha


class PrepareMaterialTests(unittest.TestCase):
    def test_shared_prefix_not_counted_as_independent_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();replay=data/'replay.jsonl';replay.write_text('')
            sources=[]
            for seed,prefix,split in [(1,'p','train'),(2,'p','train'),(3,'q','train'),(4,'r','validation')]:
                p=root/str(seed);p.mkdir()
                fruit=dict(type=10,x=0,y=-2,vx=0,vy=0,angle=0,angular_velocity=0)
                state=dict(fruits=[fruit],current_fruit=dict(type=1,x=0,y=3,y_known=True),next_fruit_type=2,
                           geometry=[-3,3,-4,3.3],score=100,game_over=False)
                row=dict(evt='decision',state=state,command=dict(start_tick=1),tick=0)
                trace=p/'trace.jsonl';trace.write_text(json.dumps(row)+'\n')
                (p/'result.json').write_text(json.dumps(dict(new_watermelons=1)))
                sources.append(dict(path=str(p),seed=seed,initial8=prefix,split=split,trace_sha256=sha(trace)))
            (data/'manifest.json').write_text(json.dumps(dict(replay_sha256=sha(replay),sources=sources,fixtures=[],excluded_seeds=[])))
            out=root/'prepared';r=prepare_progress(data,out,max_roots=3,source_limit=4)
            self.assertEqual(r['independent_source_groups'],2)
            m=json.loads((out/'manifest.json').read_text())
            self.assertFalse((out/'replay.jsonl').exists());self.assertEqual(m['replay_file'],str(replay))
            self.assertNotIn(4,m['selection']['selected_source_seeds'])
            self.assertEqual(m['phase_groups']['watermelon_one'],2)
            with self.assertRaises(FileExistsError):prepare_progress(data,out,max_roots=3,source_limit=4)


if __name__=='__main__':unittest.main()
