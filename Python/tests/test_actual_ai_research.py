import json
import tempfile
import unittest
from pathlib import Path

from analyze_actual_ai_pilot import analyze
from analyze_fresh_continuation import analyze as replay_analysis


class ActualResearchTests(unittest.TestCase):
    def game(self, root, name, mode, seed, natural, score, seconds):
        p=Path(root)/name;p.mkdir()
        g=dict(mode=mode,seed=seed,natural_go=natural,final_score=score,
               errors=[] if natural else ['not_natural_go:wall_limit'],
               environment_id='same',public_series=[1,2,3],
               startup_inclusive_wall_seconds=seconds,game_wall_seconds=seconds,
               planning_ms_per_action=[10,20],double_watermelon_known=True,
               actual_events=dict(watermelons_created=0))
        (p/'result.json').write_text(json.dumps(g))

    def test_censored_never_scores_and_cost_is_retained(self):
        with tempfile.TemporaryDirectory() as d:
            self.game(d,'h','heuristic',1,True,100,10)
            self.game(d,'cut','mcts',1,False,None,20)
            self.game(d,'retry','mcts',1,True,120,30)
            self.game(d,'unpaired','heuristic',2,True,200,10)
            r=analyze(d)
            self.assertEqual(r['pairs'][0]['difference'],20)
            self.assertEqual(len(r['pairs']),1)
            self.assertEqual(r['stats']['mcts']['total_attempt_seconds'],50)
            self.assertEqual(r['stats']['heuristic']['paired_only']['mean'],100)
            self.assertEqual(r['stats']['heuristic']['all_complete_descriptive']['mean'],150)

    def test_unfair_fruit_series_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self.game(d,'h','heuristic',1,True,100,10)
            self.game(d,'m','mcts',1,True,120,30)
            p=Path(d)/'m/result.json';g=json.loads(p.read_text());g['public_series']=[4];p.write_text(json.dumps(g))
            with self.assertRaises(ValueError):analyze(d)

    def test_replay_censored_is_not_mc_return(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cut';p.mkdir()
            end=dict(reason='wall_limit',game_over=False,mc_return_known=False,
                     prefix_complete=True,prefix_verified=True,drops=24)
            (p/'result.json').write_text(json.dumps(dict(end=end,wall_seconds=30,first_mismatch=None)))
            (p/'trace.jsonl').write_text(json.dumps(dict(evt='end',**end))+'\n')
            r=replay_analysis(d)
            self.assertEqual(r['natural_teacher_count'],0)
            self.assertFalse(r['runs'][0]['natural_go'])

    def test_interrupted_log_keeps_observed_cost_not_score(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'interrupted';p.mkdir()
            (p/'run.json').write_text(json.dumps(dict(settings=dict(ai_mode='mcts'),workers=[dict(seed=1)])))
            (p/'game_00.jsonl').write_text(json.dumps(dict(event='transition',score=999,info=dict(completion_wall=12.)))+'\n')
            r=analyze(d)
            self.assertEqual(r['stats']['mcts']['natural_games'],0)
            self.assertEqual(r['stats']['mcts']['total_attempt_seconds'],12.)
            self.assertIsNone(r['games'][0]['final_score'])
            self.assertEqual(r['interrupted'][0]['last_observed_score'],999)

    def test_mismatch_overrides_claimed_mc_return(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad';p.mkdir()
            end=dict(reason='natural_go',game_over=True,mc_return_known=True,
                     prefix_complete=True,prefix_verified=True,drops=24)
            (p/'result.json').write_text(json.dumps(dict(end=end,wall_seconds=30,first_mismatch=dict(tick=7))))
            (p/'trace.jsonl').write_text(json.dumps(dict(evt='end',**end))+'\n')
            self.assertEqual(replay_analysis(d)['natural_teacher_count'],0)

if __name__=='__main__':unittest.main()
