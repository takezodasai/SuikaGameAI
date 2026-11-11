import copy,unittest
from benchmark_physics_threads import summarize

class PhysicsThreadAuditTests(unittest.TestCase):
    def rows(self):
        base=dict(evt="search",fixture="fixture.json",iterations=32,depth=4,warmup=False,source_unchanged=True,report=dict(completed_iterations=32),lifetime=dict(retained_scenes=1,pending_unloads=0))
        a=dict(copy.deepcopy(base),threaded=False,actual_multithreading=False,actual_sorting=False,elapsed_ms=100)
        b=dict(copy.deepcopy(base),threaded=True,actual_multithreading=True,actual_sorting=True,elapsed_ms=80)
        pair=dict(evt="pair",fixture="fixture.json",iterations=32,depth=4,equal=True)
        return [a,b,pair]
    def test_matching_search_speed(self):
        r=summarize(self.rows());self.assertTrue(r["all_equal"]);self.assertAlmostEqual(r["results"][0]["time_reduction_percent"],20)
    def test_fast_but_changed_result_is_not_equivalent(self):
        rows=self.rows();rows[-1]["equal"]=False;self.assertFalse(summarize(rows)["all_equal"])
    def test_unapplied_job_settings_rejected(self):
        rows=self.rows();rows[1]["actual_sorting"]=False
        with self.assertRaisesRegex(ValueError,"not applied"):summarize(rows)
    def test_scene_leak_rejected(self):
        rows=self.rows();rows[1]["lifetime"]["retained_scenes"]=2
        with self.assertRaisesRegex(ValueError,"scene leak"):summarize(rows)
    def test_incomplete_search_rejected(self):
        rows=self.rows();rows[1]["report"]["completed_iterations"]=31
        with self.assertRaisesRegex(ValueError,"incomplete"):summarize(rows)
    def test_missing_comparison_rejected(self):
        with self.assertRaisesRegex(ValueError,"Unpaired"):summarize(self.rows()[1:])
if __name__=="__main__":unittest.main()
