import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branch_teacher_batch import Batch,task_spec,select_stage,known_branch_groups
from watermelon_lab import write,sha


class BranchBatchTests(unittest.TestCase):
    def setup(self,d):
        out=Path(d);root=dict(id='root',fixture_sha256='fixture',split_keys=['game_seed:1'])
        plan=dict(total_seconds=300,exe_sha256='exe',assembly_sha256='assembly',
                  continuation=dict(kind='legacy_mcts',iterations=128,depth=4,search_seed=8191))
        write(out/'plan.json',plan);return out,root
    def runner(self,calls,interrupt=None):
        def run(folder,plan,root,future,mode,seconds,first_x,drops):
            calls.append(str(folder));folder.mkdir(parents=True)
            write(folder/'config.json',dict(first_x=first_x))
            if interrupt and interrupt[0]:
                interrupt[0]=False;(folder/'trace.jsonl').write_text('{"evt":"root"}\n')
                write(folder/'result.json',dict(end=None,process_error='interrupted',natural_go=False))
                raise RuntimeError('injected interruption')
            rows=[dict(evt='root'),dict(evt='end',natural_go=True,reason='natural_go',elapsed_seconds=.01)]
            (folder/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            r=dict(end=rows[-1],process_error=None,natural_go=True,wall_seconds=.01)
            write(folder/'result.json',r);return r,rows
        return run
    def test_completed_tasks_reused_without_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);calls=[];b=Batch(out,runner=self.runner(calls))
            b.task('one',root,1,'baseline',30,.25);b.save()
            resumed=Batch(out,True,runner=self.runner(calls));resumed.task('one',root,1,'baseline',30,.25)
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):resumed.task('one',root,2,'baseline',30,.25)
            with self.assertRaises(FileExistsError):Batch(out)
    def test_recover_result_after_crash_before_commit_without_replay(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);calls=[];b=Batch(out,runner=self.runner(calls))
            with patch.object(b,'_commit',side_effect=OSError('injected crash')):
                with self.assertRaises(OSError):b.task('one',root,1,'baseline',30,.5)
            resumed=Batch(out,True,runner=self.runner(calls));resumed.task('one',root,1,'baseline',30,.5)
            self.assertEqual(len(calls),1)
            self.assertTrue(json.loads((out/'tasks/one/completion.json').read_text())['recovered'])
    def test_partial_attempt_preserved_and_only_incomplete_task_retried(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);calls=[];b=Batch(out,runner=self.runner(calls))
            b.task('one',root,1,'baseline',30,.5)
            b.runner=self.runner(calls,[True])
            with self.assertRaises(KeyboardInterrupt):b.task('two',root,1,'baseline',30,0)
            partial=out/'tasks/two/attempt_000/trial/trace.jsonl';digest=sha(partial)
            resumed=Batch(out,True,runner=self.runner(calls));resumed.task('one',root,1,'baseline',30,.5)
            resumed.task('two',root,1,'baseline',30,0)
            self.assertEqual(len(calls),3);self.assertEqual(sha(partial),digest)
            self.assertTrue((out/'tasks/two/attempt_001/trial/result.json').exists())
    def test_hard_kill_budget_charge_is_conservative_and_plan_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);b=Batch(out,runner=self.runner([]))
            b.save(dict(task='lost',reserved_seconds=45));before=b.state['used_seconds']
            resumed=Batch(out,True,runner=self.runner([]));self.assertAlmostEqual(resumed.base_used,before+45)
            plan=json.loads((out/'plan.json').read_text());plan['total_seconds']=500
            (out/'plan.json').write_text(json.dumps(plan))
            with self.assertRaises(ValueError):Batch(out,True)
    def test_stage_rule_before_and_after_without_pending_merges(self):
        def row(n,wm=False,merging=False):return dict(action_id=n,state=dict(game_over=False,current_fruit=dict(present=True),fruits=[dict(type=10 if wm else 9,is_merging=merging)]))
        ts=[row(1),row(2,merging=True),row(3,wm=True)]
        self.assertEqual(select_stage(ts,'before')['action_id'],1);self.assertEqual(select_stage(ts,'after')['action_id'],3)
    def test_partial_jsonl_line_is_retained_and_retried_in_new_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);calls=[]
            def bad(folder,*args):
                calls.append(str(folder));folder.mkdir(parents=True);(folder/'trace.jsonl').write_text('{"evt":')
                raise KeyboardInterrupt()
            b=Batch(out,runner=bad)
            with self.assertRaises(KeyboardInterrupt):b.task('one',root,1,'baseline',30,.5)
            raw=out/'tasks/one/attempt_000/trial/trace.jsonl';digest=sha(raw)
            resumed=Batch(out,True,runner=self.runner(calls));resumed.task('one',root,1,'baseline',30,.5)
            self.assertEqual(len(calls),2);self.assertEqual(sha(raw),digest)
    def test_corrupt_summary_with_complete_native_end_recovers_without_replay(self):
        with tempfile.TemporaryDirectory() as d:
            out,root=self.setup(d);calls=[];good=self.runner(calls)
            def corrupt(folder,*args):
                good(folder,*args);(folder/'result.json').write_text('{');raise KeyboardInterrupt()
            b=Batch(out,runner=corrupt)
            with self.assertRaises(KeyboardInterrupt):b.task('one',root,1,'baseline',30,.5)
            raw=out/'tasks/one/attempt_000/trial/result.json';digest=sha(raw)
            resumed=Batch(out,True,runner=lambda *a:(_ for _ in ()).throw(AssertionError('Must not replay')))
            resumed.task('one',root,1,'baseline',30,.5);self.assertEqual(sha(raw),digest)
            self.assertEqual(json.loads((out/'tasks/one/completion.json').read_text())['result_name'],'recovered_result.json')
    def test_prior_batch_seed_and_initial8_registry_excludes_current_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);a=p/'branch_batch_a';b=p/'branch_batch_b';a.mkdir();b.mkdir()
            write(a/'plan.json',dict(roots=[dict(source_seed=1,source_initial_sequence='a')]))
            write(b/'plan.json',dict(roots=[dict(source_seed=2,source_initial_sequence='b')]))
            seeds,prefixes,plans=known_branch_groups(p,exclude=b)
            self.assertEqual(seeds,{1});self.assertEqual(prefixes,{'a'});self.assertEqual(len(plans),1)
    def test_legacy_fixture_registry_recovers_original_initial8_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);a=p/'branch_teacher_legacy';a.mkdir();source=p/'source.jsonl'
            source.write_text(''.join(json.dumps(dict(event='transition',info=dict(planning=dict(held_fruit_type=i%5))))+'\n' for i in range(8)))
            digest=sha(source);f=p/'fixture.json';write(f,dict(source_seed=7,source_file=str(source)))
            write(a/'plan.json',dict(roots=[str(f)]));seeds,prefixes,_=known_branch_groups(p)
            self.assertEqual(seeds,{7});self.assertEqual(prefixes,{'0,1,2,3,4,0,1,2'});self.assertEqual(sha(source),digest)


if __name__=='__main__':unittest.main()
