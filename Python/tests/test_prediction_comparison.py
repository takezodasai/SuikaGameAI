import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_unity_prediction import compare, meets_tolerance, summarize_trace
import unittest
class PredictionComparisonTests(unittest.TestCase):
 def fruit(self, id, x=0):
  return dict(id=id,type=0,x=x,y=0,vx=0,vy=0,angle=0,angular_velocity=0)
 def check(self,p,a):
  return compare(dict(fruits=p,score=0,game_over=False,physics_steps=26),dict(fruits=a,score=0,game_over=False,actual_total_physics_steps=26))
 def test_exact_and_new_id_assignment(self):
  self.assertTrue(meets_tolerance(self.check([self.fruit(-1,2),self.fruit(-2,0)],[self.fruit(5,0),self.fruit(6,2)])))
 def test_source_identity_preserved(self):
  r=self.check([self.fruit(1,0),self.fruit(2,2)],[self.fruit(1,2),self.fruit(2,0)])
  self.assertEqual(r['max_position_error'],2)
  self.assertFalse(meets_tolerance(r))
 def test_missing_fruit_not_zero_error(self):
  r=self.check([self.fruit(1)],[])
  self.assertIsNone(r['max_position_error']);self.assertFalse(meets_tolerance(r))
 def test_transient_divergence_not_hidden_by_final_agreement(self):
  d=dict(first_numeric_tick=1,first_tolerance_tick=1,actual_ticks=2,predicted_ticks=2,truncated=False,
         errors=[dict(tick=0,position=0,velocity=0),dict(tick=1,position=0.1,velocity=2),dict(tick=2,position=0,velocity=0)])
  summary=summarize_trace(d)
  self.assertEqual(summary['max_position_over_time'],0.1)
  self.assertEqual(summary['first_numeric_tick'],1)
 def test_trace_truncation_and_tick_mismatch_are_visible(self):
  d=dict(first_numeric_tick=-1,first_tolerance_tick=-1,actual_ticks=4,predicted_ticks=3,truncated=True,errors=[])
  summary=summarize_trace(d)
  self.assertFalse(summary['ticks_match']);self.assertTrue(summary['truncated'])
 def test_wrong_next_controlled_fruit_is_rejected(self):
  prediction=dict(fruits=[],score=0,game_over=False,physics_steps=26,
   current_fruit=dict(present=True,type=2,x=1.0),drop_range=dict(valid=True,min_x=-2,max_x=2))
  state=dict(fruits=[],score=0,game_over=False,actual_total_physics_steps=26,
   current_fruit=dict(present=True,type=1,x=1.0),drop_range=dict(valid=True,min_x=-2,max_x=2))
  row=compare(prediction,state)
  self.assertFalse(row['preview_type_match']);self.assertFalse(meets_tolerance(row))
 def test_next_preview_position_and_range_are_checked(self):
  prediction=dict(fruits=[],score=0,game_over=False,physics_steps=26,
   current_fruit=dict(present=True,type=2,x=1.0),drop_range=dict(valid=True,min_x=-2,max_x=2))
  state=dict(fruits=[],score=0,game_over=False,actual_total_physics_steps=26,
   current_fruit=dict(present=True,type=2,x=1.0),drop_range=dict(valid=True,min_x=-2,max_x=2))
  self.assertTrue(meets_tolerance(compare(prediction,state)))
  state['current_fruit']['x']=1.1
  self.assertFalse(meets_tolerance(compare(prediction,state)))
  state['current_fruit']['x']=1.0;state['drop_range']['max_x']=1.8
  self.assertFalse(meets_tolerance(compare(prediction,state)))
if __name__=='__main__': unittest.main()
