import copy
import unittest
from suika_ai.unity_env import parse_state, validate_reward_accounting
from test_unity_env import state
from suika_ai.prediction_evaluation import reward_accounting_summary


def interval(phase, start, end, action=0, t0=0, t1=1):
    return dict(phase=phase, action_id=action, score_before=start, score_after=end,
                reward=end-start, game_time_start=t0, game_time_end=t1,
                fixed_time_start=t0, fixed_time_end=t1)


def ledger():
    return dict(version=1, episode_id="episode1", episode_start_score=0, episode_score=18,
                step_reward_total=6, between_steps_reward_total=7, conserved=True,
                last_step=interval("in_step", 10, 13, 2),
                last_between_steps=interval("between_steps", 6, 10),
                open_interval=interval("between_steps", 13, 18))


class RewardAccountingTests(unittest.TestCase):
    def test_closed_and_open_intervals_conserve_score(self):
        value=ledger()
        self.assertEqual(validate_reward_accounting(value), value)
        value["open_interval"]=interval("in_step",13,18,3)
        self.assertEqual(validate_reward_accounting(value),value)

    def test_double_count_and_missing_points_rejected(self):
        for amount in (5,7):
            value=ledger();value["step_reward_total"]=amount
            with self.assertRaises(ValueError):validate_reward_accounting(value)
        value=ledger();value["open_interval"]["reward"]=0
        with self.assertRaises(ValueError):validate_reward_accounting(value)

    def test_gap_does_not_claim_an_action_or_reverse_time(self):
        value=ledger();value["open_interval"]["action_id"]=3
        with self.assertRaises(ValueError):validate_reward_accounting(value)
        value=ledger();value["open_interval"]["game_time_end"]=-1
        with self.assertRaises(ValueError):validate_reward_accounting(value)

    def test_snapshot_episode_and_score_must_match(self):
        observation=state();observation.update(score=18,reward_accounting=ledger())
        self.assertEqual(parse_state(observation)["score"],18)
        for key,bad in (("episode_id","old"),("episode_score",17)):
            broken=copy.deepcopy(observation);broken["reward_accounting"][key]=bad
            with self.assertRaises(ValueError):parse_state(broken)

    def test_unity_empty_class_placeholders_are_not_intervals(self):
        observation=state()
        accounting=ledger()
        accounting['last_step']={'present':False,'phase':'','reward':0}
        accounting['last_between_steps']={'present':False,'phase':'','reward':0}
        observation.update(score=18,reward_accounting=accounting,
                           previous_episode_reward_accounting={'present':False,'episode_id':''})
        self.assertEqual(parse_state(observation),observation)
        accounting['open_interval']['present']=False
        with self.assertRaises(ValueError):parse_state(observation)

    def test_summary_deduplicates_cumulative_ledgers_and_retains_open_gap(self):
        current=ledger()
        rows=[dict(state=dict(reward_accounting=current))]*3
        result=reward_accounting_summary(rows)
        self.assertEqual(result['episodes'],1)
        self.assertEqual(result['episode_score'],18)
        self.assertEqual(result['open_between_steps_reward'],5)
        self.assertTrue(result['conserved'])
        later=copy.deepcopy(current)
        later['episode_score']=20
        later['open_interval'].update(score_after=20,reward=7,game_time_end=2)
        rows.append(dict(state=dict(previous_episode_reward_accounting=later)))
        self.assertEqual(reward_accounting_summary(rows)['episode_score'],20)
        self.assertFalse(reward_accounting_summary([dict(state={})])['available'])

    def test_previous_episode_preserved_and_legacy_accepted(self):
        observation=state()
        observation["previous_episode_reward_accounting"]=ledger()
        self.assertEqual(parse_state(observation),observation)
        self.assertEqual(parse_state(state()),state())
