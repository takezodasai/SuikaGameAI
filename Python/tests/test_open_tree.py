import unittest,tempfile,copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.unity_env import validate_planning_settings
from suika_ai.parallel_play import run_parallel
from analyze_tree_probe import validate_open_report

class OpenTreeTests(unittest.TestCase):
    def test_default_and_opt_in(self):
        self.assertEqual(validate_planning_settings({})['tree_policy'],'chance')
        s=validate_planning_settings(dict(ai_mode='mcts',tree_policy='public_open_loop'));self.assertEqual(s['rollout_policy'],'random')
    def test_invalid_combinations(self):
        for patch in [dict(tree_policy='wrong'),dict(ai_mode='value'),dict(execution_mode='frames'),dict(rollout_policy='guided'),dict(candidate_policy='board-five')]:
            s=dict(ai_mode='mcts',tree_policy='public_open_loop');s.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_planning_settings(s)
    def test_one_game_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'fake.exe';exe.write_bytes(b'fake')
            with self.assertRaises(ValueError):run_parallel(exe,p/'out',games=4,settings=dict(ai_mode='mcts',tree_policy='public_open_loop'))
            self.assertFalse((p/'out').exists())
    def report(self):
        edges=[dict(visits=1,chance_slots=[-2],chance_node_ids=[1+i]) for i in range(2)]
        nodes=[dict(visits=2,arrivals=2,actions=edges,public_context='0:1',history_key='',distinct_states=1)]+[dict(visits=0,arrivals=1,actions=[dict(visits=0)]*2,distinct_states=0) for _ in range(2)]
        its=[dict(actions=[i,1-i],chance_slots=[-2,-1],tree_node_ids=[0,-1],public_observations=['0:1','1:-1'],state_signatures=['root','hypothesis'+str(i)],rollout_steps=[False,True]) for i in range(2)]
        d=dict(held_fruit_type=0,next_fruit_type=1);m=dict(tree_policy='public_open_loop',nodes=nodes,iterations=its,max_depth=2,public_spawn_types=[0,1],leaf_cache_hits=0,skipped_physics_ticks=0)
        return d,m
    def test_public_timing_and_visit_conservation(self):validate_open_report(*self.report())
    def test_wrong_public_fruit_rejected(self):
        for depth,value in [(0,'4:1'),(0,'0:4'),(1,'0:-1')]:
            d,m=self.report();m['iterations'][0]['public_observations'][depth]=value
            with self.assertRaisesRegex(ValueError,'public'):validate_open_report(d,m)
    def test_hidden_information_or_wrong_context_rejected(self):
        d,m=self.report();m['nodes'][0]['public_context']='0:4'
        with self.assertRaisesRegex(ValueError,'contexts'):validate_open_report(d,m)
    def test_shared_leaf_cache_rejected(self):
        d,m=self.report();m['leaf_cache_hits']=1
        with self.assertRaisesRegex(ValueError,'cache'):validate_open_report(d,m)
    def test_false_state_count_rejected(self):
        d,m=self.report();m['nodes'][0]['distinct_states']=2
        with self.assertRaisesRegex(ValueError,'state'):validate_open_report(d,m)
    def test_false_rollout_or_visits_rejected(self):
        d,m=self.report();m['iterations'][0]['rollout_steps'][1]=False
        with self.assertRaises(ValueError):validate_open_report(d,m)
        d,m=self.report();m['nodes'][0]['actions'][0]['visits']=5
        with self.assertRaisesRegex(ValueError,'visits'):validate_open_report(d,m)
