import copy
import tempfile
import time
import unittest
from pathlib import Path

from alternative_mcts_experiment import validate_decision
from branch_teacher_batch import Batch,prepare,fixed_branch_selection,operator_pause_requested
from watermelon_lab import write


class AlternativeMctsTests(unittest.TestCase):
    def decision(self,selector):
        cs=[dict(index=i,x=i/4,visits=25 if i<4 else 28,mean_points=i,drop_success=True,immediate_go=False) for i in range(5)]
        selected=3 if selector=='alternative' else 4
        return dict(planning=dict(selected_index=4,selected_x=1),search=dict(root=cs,source_unchanged=True,completed_iterations=128),
            final_selection=dict(has_alternative=True,alternative_index=3,actual_x=selected/4),command=dict(x=selected/4))
    def test_selector_matches_frozen_reference_and_does_not_mutate_statistics(self):
        for selector in ['legacy','alternative']:
            row=self.decision(selector);before=copy.deepcopy(row)
            self.assertTrue(validate_decision(row,selector));self.assertEqual(before,row)
    def test_wrong_executed_coordinate_rejected(self):
        row=self.decision('alternative');row['command']['x']=1
        with self.assertRaises(AssertionError):validate_decision(row,'alternative')
    def test_no_safe_alternative_falls_back_to_A(self):
        row=self.decision('alternative')
        for c in row['search']['root'][:4]:c['immediate_go']=True
        row['final_selection']=dict(has_alternative=False,actual_x=1);row['command']['x']=1
        self.assertFalse(validate_decision(row,'alternative'))
        selection=fixed_branch_selection(row)
        self.assertTrue(selection['unavailable']);self.assertIsNone(selection['alternative_x'])
    def test_duplicate_future_seeds_rejected_before_source_access(self):
        with self.assertRaises(ValueError):prepare(Path('missing'),Path('unused'),8,future_seeds=[1,1])
    def test_outer_deadline_only_reduces_existing_batch_budget(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);write(p/'plan.json',dict(total_seconds=300))
            b=Batch(p);original=b.remaining();b.external_deadline=time.time()+60
            self.assertLess(b.remaining(),60);self.assertLess(b.remaining(),original)
            b.external_deadline=time.time()+600
            self.assertLessEqual(b.remaining(),original)
    def test_failed_native_end_requires_explicit_quarantine_and_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);write(out/'plan.json',dict(total_seconds=300,exe_sha256='exe',assembly_sha256='asm',continuation=dict(kind='legacy_mcts',iterations=128,depth=4,search_seed=8191)))
            root=dict(id='root',fixture_sha256='unique-test-fixture');calls=[]
            def failed(folder,*args):
                calls.append(1);folder.mkdir(parents=True)
                (folder/'trace.jsonl').write_text('{"evt":"root"}\n{"evt":"end","reason":"error"}\n')
                write(folder/'result.json',dict(root=dict(score=0),end=dict(reason='error'),natural_go=False,errors=['clone invariant'],exit_code=2,process_error=None,wall_seconds=.1))
                raise RuntimeError('native error')
            b=Batch(out,runner=failed)
            with self.assertRaises(RuntimeError):b.task('one',root,1,'survey',30,drops=1)
            b.save();resumed=Batch(out,True,runner=failed)
            with self.assertRaises(RuntimeError):resumed.task('one',root,1,'survey',30,drops=1)
            resumed.quarantine_trial_errors=True;r,_=resumed.task('one',root,1,'survey',30,drops=1)
            self.assertFalse(r['natural_go']);self.assertEqual(len(calls),1)
            import json
            self.assertFalse(json.loads((out/'tasks/one/completion.json').read_text())['natural_go'])
    def test_pause_request_stops_current_session_but_not_explicit_later_resume(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)
            self.assertFalse(operator_pause_requested(out,10))
            write(out/'operator_pause_request.json',dict(requested_unix=15))
            self.assertTrue(operator_pause_requested(out,10))
            self.assertFalse(operator_pause_requested(out,20))


if __name__=='__main__':unittest.main()
