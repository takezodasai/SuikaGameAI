import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_unity_prediction import compare, meets_tolerance
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
if __name__=='__main__': unittest.main()
