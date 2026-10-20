import argparse
from contextlib import redirect_stdout
import io
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from suika_ai.prediction_evaluation import distribution,rate,merge_events,compare_fruits,evaluate,summarize
from evaluate_unity_prediction import append_record,load_records,export_results
import evaluate_unity_prediction as cli


def fruit(alias="f1",type_=2,x=0,y=-2,preview=False,angle=0):
    return dict(id=alias,type=type_,preview=preview,merging=False,position=dict(x=x,y=y),
                velocity=dict(x=0,y=0),angle=angle,angular_velocity=0,contacts=[])


def state():
    initial=dict(score=0,game_over=False,fruits=[fruit(preview=True,y=3)])
    final=dict(score=0,game_over=False,fruits=[fruit()])
    zero=dict(ids_types_match=True,score_match=True,game_over_match=True,
              position=0,velocity=0,angle=0,angular_velocity=0,mass=0,inertia=0,center_of_mass=0)
    diagnostics=dict(initial_actual=initial,initial_prediction=copy.deepcopy(initial),
        final_actual=final,final_prediction=copy.deepcopy(final),errors=[zero],actual_events=[],predicted_events=[],
        truncated=False,actual_ticks=26,predicted_ticks=26,first_numeric_tick=-1)
    prediction=dict(source_unchanged=True,fixed_delta_time=.02,physics_steps=26,post_drop_steps=25,movement_steps=0,
        drop_success=True,applied_x=.65,reward=0,score=0,game_over=False,diagnostics=diagnostics,
        fruits=[],reference_fruits=[],reference_score=0,reference_game_over=False,
        initial_next_fruit_type=2,game_over_height=4,
        **{k:1 for k in ("elapsed_ms","reference_elapsed_ms","scene_create_ms","copy_ms","simulation_ms","cleanup_schedule_ms")})
    return dict(prediction=prediction,fixed_delta_time=.02,score=0,game_over=False,actual_total_physics_steps=26,
                step_result=dict(movement_steps=0,drop_success=True,applied_x=.65,reward=0,physics_steps=25))


def record(value=None,index=0):
    return dict(index=index,x=.65,episode_id="episode-a",status="completed",metrics=evaluate(value or state()))


class EvaluationTests(unittest.TestCase):
    def test_distribution_empty_percentiles_histogram(self):
        self.assertIsNone(distribution([])["mean"])
        d=distribution([0,1,2,3,4]);self.assertEqual(d["median"],2);self.assertAlmostEqual(d["p95"],3.8)
        self.assertEqual(sum(b["count"] for b in d["histogram"]),5)
        with self.assertRaises(ValueError):distribution([math.nan])
        self.assertIsNone(rate(0,0)["rate"])
        self.assertLess(rate(95,100)["wilson95"][0],.95)

    def test_alias_matching_does_not_guess_nearby_fruit(self):
        r=compare_fruits(dict(fruits=[fruit("new")]),dict(fruits=[fruit("old")]))
        self.assertFalse(r["complete"]);self.assertEqual(r["per_fruit"],[])
        self.assertEqual(r["missing_predicted_aliases"],["old"])

    def test_vector_and_wrapped_angle_errors(self):
        p=fruit(x=.003,y=-1.996,angle=359);a=fruit(angle=1)
        r=compare_fruits(dict(fruits=[p]),dict(fruits=[a]))
        self.assertAlmostEqual(r["per_fruit"][0]["position"],.005)
        self.assertEqual(r["per_fruit"][0]["angle"],2)

    def test_merges_cascade_and_watermelon(self):
        events=merge_events(["59:merge:m(f1,f2):2->3","60:merge:m(f3,m(f1,f2)):3->4","61:merge:m(f4,f5):10->-1"])
        self.assertEqual(len(events),3);self.assertEqual(events[-1]["to"],-1)
        self.assertGreater(events[1]["lineage"].count("m("),1)
        with self.assertRaises(ValueError):merge_events(["1:merge:unrecognized"])

    def test_exact_comparison_and_empty_strata_not_claimed(self):
        r=record();self.assertTrue(r["metrics"]["eligible"])
        s=summarize([r]);self.assertEqual(s["all"]["reward"]["all"]["exact"]["rate"],1)
        self.assertIsNone(s["all"]["reward"]["actual_nonzero"]["exact"]["rate"])
        self.assertIsNone(s["all"]["merge"]["actual_positive"]["presence_match"]["rate"])
        self.assertIsNone(s["all"]["game_over"]["miss_rate"]["rate"])
        self.assertFalse(s["candidate_ranking"]["available"])

    def test_positive_merge_and_score_miss_not_diluted(self):
        a=state();a["score"]=6;a["step_result"]["reward"]=6
        a["prediction"]["diagnostics"]["actual_events"]=["20:merge:m(f1,f2):2->3"]
        s=summarize([record(a),record(index=1)])
        self.assertEqual(s["all"]["merge"]["actual_positive"]["presence_match"]["rate"],0)
        self.assertEqual(s["all"]["merge"]["recall"]["rate"],0)
        self.assertEqual(s["all"]["reward"]["actual_nonzero"]["absolute_error"]["mean"],6)
        self.assertEqual(s["all"]["reward"]["all"]["exact"]["rate"],.5)
        self.assertEqual(s["all"]["episodes"],1)

    def test_terminal_tick_mismatch_remains_visible(self):
        a=state();a["game_over"]=True;a["actual_total_physics_steps"]=20
        r=record(a);self.assertFalse(r["metrics"]["eligible"])
        s=summarize([r]);self.assertEqual(s["eligible"],0)
        self.assertEqual(s["game_over_all_completed_screening"]["fn"],1)
        self.assertEqual(len(s["terminal_disagreements_for_review"]),1)
        self.assertIsNone(s["all"]["physical"]["per_fruit"]["position"]["mean"])

    def test_truncation_and_initial_mismatch_excluded(self):
        for change in ("truncated","initial"):
            a=state();d=a["prediction"]["diagnostics"]
            if change=="truncated":d["truncated"]=True
            else:d["errors"][0]["velocity"]=.1
            self.assertFalse(evaluate(a)["eligible"])

    def test_clock_movement_and_requested_horizon_mismatch(self):
        a=state();a["fixed_delta_time"]=.01
        self.assertIn("fixed_dt_mismatch",evaluate(a)["ineligible_reasons"])
        a=state();a["step_result"]["movement_steps"]=2
        self.assertIn("movement_ticks_mismatch",evaluate(a)["ineligible_reasons"])
        self.assertIn("requested_horizon_mismatch",evaluate(state(),requested_post_drop_steps=100)["ineligible_reasons"])

    def test_instrumentation_difference_is_not_silently_accepted(self):
        a=state();a["prediction"]["reference_score"]=1
        self.assertIn("instrumentation_changed_prediction",evaluate(a)["ineligible_reasons"])

    def test_contact_label_uses_aliases_not_name_prefix(self):
        a=state();f=fruit();f["contacts"]=[dict(other="floor")]
        a["prediction"]["diagnostics"]["initial_actual"]["fruits"].append(f)
        self.assertNotIn("fruit_contact",evaluate(a)["labels"])

    def test_collector_resume_preserves_raw_and_starts_new_episode(self):
        class FakeEnv:
            episodes=0
            sent=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def _send(self,message):self.sent.append(message)
            def reset(self,timeout):
                FakeEnv.episodes+=1
                self.episode=f"fake-{FakeEnv.episodes}"
                return dict(episode_id=self.episode,stream_id="stream",state_id=1,score=0,game_over=False,
                            fruits=[],current_fruit=dict(type=2,x=.5,present=True),next_fruit_type=2,
                            ai_move_speed=2.5,fixed_delta_time=.02,time_scale=1)
            def step(self,x,timeout):
                self._send(dict(command="step",x=x))
                value=state();value.update(self.reset_context())
                value["step_result"]["action_id"]=1
                return value,0,False,value["step_result"]
            def reset_context(self):return dict(episode_id=self.episode,stream_id="stream",state_id=2,fruits=[],
                current_fruit=dict(type=2,x=.5,present=True),next_fruit_type=2,ai_move_speed=2.5,time_scale=1)
        with tempfile.TemporaryDirectory() as temp,patch.object(cli,"UnityEnv",FakeEnv),patch.object(cli,"provenance",lambda:{"version":"test"}),redirect_stdout(io.StringIO()):
            root=Path(temp)/"experiment"
            args=argparse.Namespace(positions="0.65",post_drop_steps=25,episode_steps=6,random_x=False,
                seed=123,near_over_margin=.5,timeout=30,output=root,resume=False,samples=1)
            self.assertEqual(cli.collect(args),0)
            before=(root/"trials.jsonl").read_bytes()
            args.resume=True;args.samples=2
            self.assertEqual(cli.collect(args),0)
            self.assertTrue((root/"trials.jsonl").read_bytes().startswith(before))
            rows,_=load_records(root/"trials.jsonl")
            self.assertNotEqual(rows[0]["episode_id"],rows[1]["episode_id"])
            self.assertTrue(all(m["command"]=="compare_step" for m in FakeEnv.sent))
            args.seed=999
            with self.assertRaises(ValueError):cli.collect(args)

    def test_durable_jsonl_and_offline_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/"trials.jsonl";r=record()
            append_record(path,r);append_record(path,dict(index=1,x=0,status="failed",error="timeout"))
            records,partial=load_records(path);self.assertFalse(partial);self.assertEqual(len(records),2)
            result=export_results(root,records);self.assertEqual(result["excluded"],1)
            self.assertTrue((root/"fruits.csv").exists())
            with path.open("a",encoding="utf-8") as file:file.write('{"partial":')
            records,partial=load_records(path);self.assertTrue(partial);self.assertEqual(len(records),2)


if __name__=="__main__":unittest.main()
