import unittest
from copy import deepcopy

from branch_action_teacher import compare_trials, policy


class BranchTeacherTests(unittest.TestCase):
    def rows(self):
        state = dict(score=100, current_fruit=dict(type=1), next_fruit_type=2,
                     fruits=[], geometry=[-3,3,-4,3], drop_cooldown_remaining=0,
                     ai_move_speed=3.75, fixed_delta_time=.02)
        root = dict(evt='root', state=deepcopy(state), tick=0, rng='future-rng')
        decision = dict(evt='decision', completed_actions=0, planning=dict(selected_x=.5),
                        search=dict(root=[dict(visits=128,mean_points=10)], source_unchanged=True))
        release = dict(evt='release', state=deepcopy(state))
        action = dict(evt='action', state=deepcopy(state), completed_actions=1,
                      command=dict(x=.5, drop_tick=25), rng='after-rng')
        return [root,decision,release,action]

    def test_repeat_equality_is_not_native_checkpoint_certification(self):
        a=self.rows();r=compare_trials(a,deepcopy(a))
        self.assertTrue(r['same_initial_observed']);self.assertTrue(r['fully_equal_observed_prefix'])
        self.assertFalse(r['exact_native_state_guaranteed'])

    def test_initial_mismatch_distinct_from_later_variation(self):
        a=self.rows();b=deepcopy(a);b[0]['state']['drop_cooldown_remaining']=.02
        self.assertFalse(compare_trials(a,b)['same_initial_observed'])
        b=deepcopy(a);b[-1]['command']['drop_tick']=26
        r=compare_trials(a,b);self.assertTrue(r['same_initial_observed']);self.assertFalse(r['fully_equal_observed_prefix'])

    def test_chance_sequence_and_search_statistics_audited_separately(self):
        a=self.rows();b=deepcopy(a);b[2]['state']['next_fruit_type']=4
        self.assertFalse(compare_trials(a,b)['common_public_fruits_equal'])
        b=deepcopy(a);b[1]['search']['root'][0]['mean_points']=11
        r=compare_trials(a,b);self.assertTrue(r['common_public_fruits_equal'])
        self.assertFalse(r['search_checks'][0]['root_statistics_equal']);self.assertFalse(r['fully_equal_observed_prefix'])

    def test_supported_continuation_is_explicit(self):
        p=policy(dict(kind='legacy_mcts',iterations=128,depth=4,search_seed=8191))
        self.assertEqual(p['post_drop_ticks'],25);self.assertEqual(len(p['candidates']),5)
        self.assertEqual(policy(dict(kind='legacy_mcts',iterations=64,depth=6,search_seed=1))['iterations'],64)
        with self.assertRaises(ValueError):policy(dict(kind='unimplemented_policy',iterations=128,depth=4,search_seed=1))


if __name__=='__main__':unittest.main()
