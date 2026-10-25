import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
from analyze_two_step_probe import trace_search
import test_two_step_diagnostic as diagnostic
from compare_expansion_ai import settings,validate_geometry

class ExpansionTests(unittest.TestCase):
    def test_default_opt_in(self):
        self.assertEqual(validate_planning_settings({})['expansion_policy'],'legacy')
        self.assertEqual(validate_planning_settings(settings('chance_decision'))['expansion_policy'],'chance_decision')
    def test_invalid_combinations(self):
        for patch in [dict(expansion_policy='wrong'),dict(ai_mode='value'),dict(tree_policy='public_open_loop'),dict(execution_mode='frames'),dict(frame_tick_slicing=True),dict(rollout_policy='guided'),dict(candidate_policy='board-five')]:
            s=settings('chance_decision');s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'fake.exe';exe.write_bytes(b'fake')
            with self.assertRaises(ValueError):run_parallel(exe,p/'out',games=4,settings=settings('chance_decision'))
            self.assertFalse((p/'out').exists())
    def sample(self):
        r=diagnostic.TwoStepDiagnosticTests().search();r['decision']['settings']['expansion_policy']='chance_decision'
        for i,(it,node) in enumerate(zip(r['report']['iterations'],r['report']['nodes'][1:])):
            it.update(rollout_steps=[False,False],extra_decisions=1,expanded_actions=2,new_chance_nodes=1)
            node['visits']=1;node['actions']=[dict(visits=int(j==1-i)) for j in range(2)]
        return r
    def test_child_action_backed_up_once(self):
        traces=trace_search(self.sample())
        for t in traces:self.assertEqual([s['phase'] for s in t['steps']],['expansion','expansion']);self.assertEqual(t['extra_decisions'],1)
    def test_wrong_rollout_boundary_rejected(self):
        r=self.sample();r['report']['iterations'][0]['rollout_steps'][1]=True
        with self.assertRaisesRegex(ValueError,'boundary'):trace_search(r)
    def test_wrong_extra_or_expansion_counts_rejected(self):
        for key in ['extra_decisions','expanded_actions','new_chance_nodes']:
            r=self.sample();r['report']['iterations'][0][key]+=1
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'accounting'):trace_search(r)
    def test_duplicate_backprop_rejected(self):
        r=self.sample();r['report']['nodes'][1]['visits']=2
        with self.assertRaisesRegex(ValueError,'visit'):trace_search(r)
    def test_game_over_no_child_or_bonus(self):
        r=self.sample();m=r['report'];m['nodes']=m['nodes'][:1]
        for it in m['iterations']:
            it.update(actions=it['actions'][:1],chance_slots=it['chance_slots'][:1],rollout_steps=[False],depth=1,game_over=True,extra_decisions=0,expanded_actions=1,new_chance_nodes=0)
        self.assertTrue(all(t['extra_decisions']==0 for t in trace_search(r)))
    def test_legacy_without_new_fields_compatible(self):
        self.assertTrue(all(t['extra_decisions']==0 for t in trace_search(diagnostic.TwoStepDiagnosticTests().search())))
    def test_only_expansion_setting_differs(self):
        a=settings('legacy');b=settings('chance_decision');a.pop('expansion_policy');b.pop('expansion_policy');self.assertEqual(a,b)
