import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branch_trial_registry import (branch_plans, trial_identity, relationship,
                                   check_new_trial, clone_plan, snapshot_identity, preview_plan)
from branch_teacher_batch import known_branch_groups, prepare
from watermelon_lab import write


class RegistryTests(unittest.TestCase):
    def make(self, base, name='branch_night_test/batch_01', seed=1):
        out=base/name;out.mkdir(parents=True)
        f=out/'board.json';write(f,dict(fruits=[dict(type=10,x=0,y=0)],score=100,
                                     snapshot=dict(current_fruit=dict(type=0),process_id=123)))
        root=dict(id='root',source_seed=seed,source_initial_sequence=str(seed),fixture=str(f),board_uid='board')
        plan=dict(roots=[root],future_seeds=[10,11],continuation=dict(kind='legacy',iterations=128,depth=4,search_seed=8191),
                  exe_sha256='exe',assembly_sha256='asm')
        write(out/'plan.json',plan);write(out/'root_selection.json',dict(recommended_x=0,alternative_x=.5))
        return out,plan,root

    def test_nested_four_batches_detected_and_current_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            for i in range(1,5):self.make(base,f'branch_night_test/batch_{i:02}')
            self.assertEqual(len(list(branch_plans(base))),4)
            seeds,prefixes,plans=known_branch_groups(base,base/'branch_night_test/batch_04')
            self.assertEqual((seeds,prefixes,len(plans)),({1},{'1'},3))

    def test_schema_detects_arbitrarily_named_nested_output(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,p,_=self.make(base,'night_2026/results/01')
            p['version']='branch-batch-v2';(out/'plan.json').write_text(json.dumps(p))
            self.assertEqual(len(list(branch_plans(base))),1)

    def test_unintentional_duplicate_blocked_even_different_output_directory(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,p,r=self.make(base)
            with self.assertRaisesRegex(ValueError,'duplicate'):
                check_new_trial(base,base/'branch_new',p,r,10,0)
            check_new_trial(base,base/'branch_new',p,r,12,0)

    def test_relationship_four_cases(self):
        with tempfile.TemporaryDirectory() as t:
            _,p,r=self.make(Path(t));a=trial_identity(p,r,10,0)
            self.assertEqual(relationship(a,dict(a)),'same_condition')
            self.assertEqual(relationship(a,dict(a,future_seed=12)),'new_future')
            self.assertEqual(relationship(a,dict(a,snapshot='other')),'same_source_different_board')
            self.assertEqual(relationship(a,dict(a,snapshot='other',source_keys=['game_seed:9'])),'independent_source')

    def test_snapshot_ignores_process_metadata_but_not_velocity_or_held(self):
        with tempfile.TemporaryDirectory() as t:
            _,p,r=self.make(Path(t));f=Path(r['fixture']);before=snapshot_identity(r)
            x=json.loads(f.read_text());x['snapshot']['process_id']=999;f.write_text(json.dumps(x))
            self.assertEqual(before,snapshot_identity(r))
            x['fruits'][0]['id']=42;f.write_text(json.dumps(x))
            self.assertEqual(before,snapshot_identity(r))
            x['fruits'][0]['vx']=.1;f.write_text(json.dumps(x))
            self.assertNotEqual(before,snapshot_identity(r))

    def test_explicit_repeat_validated_and_reason_required(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,p,r=self.make(base);new=base/'branch_repeat'
            with self.assertRaises(ValueError):clone_plan(out,new,[10,11],'intentional_repeat')
            clone_plan(out,new,[10,11],'intentional_repeat','reproducibility')
            np=json.loads((new/'plan.json').read_text())
            check_new_trial(base,new,np,r,10,0)
            np['repeat_of_plan_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'authorization'):check_new_trial(base,new,np,r,10,0)

    def test_new_futures_not_independent_and_dry_run_no_writes(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,p,r=self.make(base);new=base/'branch_future'
            with self.assertRaises(ValueError):clone_plan(out,new,[10,12],'new_future_series')
            with patch('branch_trial_registry.branch_plans',return_value=iter([(out/'plan.json',p)])):
                x=clone_plan(out,new,[12,13],'new_future_series',dry_run=True)
            self.assertEqual(x['new_independent_boards'],0);self.assertEqual(x['planned_main_trials'],4)
            self.assertFalse(new.exists())

    def test_corrupt_nested_plan_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,_,_=self.make(base);(out/'plan.json').write_text('{')
            with self.assertRaises(ValueError):list(branch_plans(base))

    def test_same_source_new_board_not_new_independent_even_with_new_future(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);out,p,r=self.make(base)
            r=dict(r,fixture_sha256='changed',fixture=None,board_uid='changed')
            p=dict(p,collection_intent='new_independent_sources')
            with self.assertRaisesRegex(ValueError,'independent'):
                check_new_trial(base,base/'branch_new',p,r,12,0)

    def test_preview_counts_nested_overlap_without_changing_files(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);a,p,r=self.make(base);b,_,_=self.make(base,'branch_night_test/batch_02')
            before={str(f):f.read_bytes() for f in base.rglob('*') if f.is_file()}
            result=preview_plan(b,base)
            self.assertEqual(result['new_independent_boards'],0)
            self.assertEqual(result['existing_board_overlaps'],1)
            self.assertEqual(result['same_condition_trials'],4)
            self.assertEqual(before,{str(f):f.read_bytes() for f in base.rglob('*') if f.is_file()})

    def test_prepare_dry_run_is_read_only_and_excludes_nested_sources(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);existing,p,r=self.make(base);source=base/'source';source.mkdir()
            for seed in range(1,6):
                job=source/'jobs'/f'job_{seed:06}';(job/'attempt_000').mkdir(parents=True)
                write(job/'attempt_000_result.json',dict(valid_for_return_learning=True,watermelon_events=True,game_seed=seed,job=seed))
            import branch_teacher_batch as module
            original=module.load
            def read(path):
                if str(path).endswith('test_reservation_manifest.json'):return dict(episodes=[])
                if str(path).endswith('branch_teacher_jobs18_29_01/plan.json') or str(path).endswith('branch_teacher_jobs18_29_01\\plan.json'):return dict(roots=[])
                return original(path)
            with patch.object(module,'load',side_effect=read),patch.object(module,'known_branch_groups',return_value=({1},{'1'},[])),patch.object(module,'records',return_value=[dict(event='episode_end',game_over=True,truncated=False,reason='game_over',conserved=True)]),patch.object(module,'initial_sequence',side_effect=['2','3','4','5']):
                result=prepare(source,base/'branch_new',dry_run=True)
            self.assertEqual(result['existing_source_overlaps'],1)
            self.assertEqual(result['new_independent_boards'],4)
            self.assertEqual(result['planned_main_trials'],16)
            self.assertNotIn(1,result['selected_source_seeds']);self.assertFalse((base/'branch_new').exists())


if __name__=='__main__':unittest.main()
