import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from suika_ai.unity_env import validate_planning_settings
class ExtendedBudgetTests(unittest.TestCase):
 def settings(self,**kw):return validate_planning_settings(dict(ai_mode='mcts',mcts_extended_budget=True,mcts_iterations=32,mcts_max_depth=4,**kw))
 def test_full_bounds(self):
  for depth in [2,4,8,16,256]:
   for cap in [32,512,32768]:
    s=validate_planning_settings(dict(ai_mode='mcts',mcts_extended_budget=True,mcts_iterations=cap,mcts_max_iterations=cap,mcts_max_depth=depth,mcts_time_limit_seconds=120));self.assertEqual(s['mcts_max_depth'],depth)
 def test_reject_bad_ranges(self):
  for key,value in [('mcts_iterations',31),('mcts_iterations',32769),('mcts_max_iterations',31),('mcts_max_iterations',32769),('mcts_max_depth',1),('mcts_max_depth',257),('mcts_time_limit_seconds',121),('adaptive_initial_iterations',64),('auto_depth_max',9),('auto_depth_min',1),('mcts_auto_depth',1),('mcts_extended_budget',1),('mcts_time_limit_seconds',float('nan'))]:
   x=dict(ai_mode='mcts',mcts_extended_budget=True,mcts_max_depth=4);x[key]=value
   with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_planning_settings(x)
 def test_legacy_limits_remain(self):
  for x in [dict(mcts_max_depth=9),dict(mcts_iterations=257),dict(mcts_max_iterations=4097),dict(mcts_auto_depth=True)]:
   with self.assertRaises(ValueError):validate_planning_settings(dict(ai_mode='mcts',**x))
 def test_auto_depth_independent_of_cap(self):
  for n in [32,256,32768]:self.assertTrue(self.settings(mcts_auto_depth=True,mcts_max_iterations=n)['mcts_auto_depth'])
 def test_sync_only_no_other_search_policies(self):
  for x in [dict(execution_mode='frames'),dict(rollout_policy='guided'),dict(ai_mode='value'),dict(tree_policy='public_open_loop')]:
   with self.assertRaises(ValueError):validate_planning_settings(dict(mcts_extended_budget=True,**x))
