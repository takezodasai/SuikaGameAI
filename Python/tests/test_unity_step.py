import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv
from test_unity_env import state


def completed(sequence=2, action=1, x=0.5):
    result = state(sequence)
    result["score"] = 3
    result["step_result"] = dict(action_id=action, requested_x=x, applied_x=-2+4*x,
        applied_normalized_x=x, min_x=-2, max_x=2, dropped_fruit_id=10,
        drop_success=True, status="completed", reward=3, score_before=0, physics_steps=25)
    return result


class StepTests(unittest.TestCase):
    def test_invalid_x_sends_nothing(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env, patch.object(env, "_send") as send:
            for x in (-0.1, 1.1, float("nan"), float("inf"), True, "0.5", None):
                with self.assertRaises(ValueError):
                    env.step(x)
            send.assert_not_called()

    def test_endpoints_and_reward(self):
        for x in (0, 0.5, 1):
            with self.subTest(x=x), UnityEnv(local=("127.0.0.1", 0)) as env:
                env._action_episode = "episode1"
                with patch.object(env, "receive_state", side_effect=[state(), completed(x=x)]), patch.object(env, "_send") as send:
                    observation, reward, done, info = env.step(x)
                    self.assertEqual(reward, 3)
                    self.assertFalse(done)
                    self.assertEqual(info["applied_x"], -2+4*x)
                    self.assertEqual(send.call_args.args[0]["action_id"], 1)
                    self.assertIsNone(env._pending_step)

    def test_timeout_blocks_new_steps(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            env._action_episode = "episode1"
            calls = []
            def receive(*args, **kwargs):
                if kwargs:
                    raise TimeoutError()
                return state()
            with patch.object(env, "receive_state", side_effect=receive), patch.object(env, "_send", side_effect=calls.append):
                with self.assertRaises(TimeoutError):
                    env.step(0.5, timeout=0.27)
                self.assertGreaterEqual(len(calls), 2)
                self.assertTrue(all(c == calls[0] for c in calls))
                with self.assertRaises(RuntimeError):
                    env.step(0.5)
                with self.assertRaises(RuntimeError):
                    env.send_action(2)

    def test_terminal_and_rejected_reply(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            env._action_episode = "episode1"
            terminal = state()
            terminal["game_over"] = True
            with patch.object(env, "receive_state", return_value=terminal), patch.object(env, "_send") as send:
                _, reward, done, info = env.step(0.5)
                self.assertTrue(done)
                self.assertFalse(info["drop_success"])
                self.assertEqual(reward, 0)
                send.assert_not_called()
            bad = completed()
            bad["step_result"]["status"] = "busy"
            with patch.object(env, "receive_state", side_effect=[state(), bad]), patch.object(env, "_send"):
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    env.step(0.5)

    def test_cached_completion_not_discarded_as_old_observation(self):
        import json
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            env.stream_id = "stream"
            env.last_state_id = 100
            with patch.object(env, "socket") as sock:
                sock.recvfrom.return_value = (json.dumps(completed()).encode(), ("127.0.0.1", 1234))
                self.assertEqual(env.receive_state(step_action_id=1)["state_id"], 2)
                self.assertEqual(env.last_state_id, 100)

    def test_concurrent_operation_and_reset_requirement(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            with self.assertRaisesRegex(RuntimeError, "reset"):
                env.step(0.5)
            env._operation_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "progress"):
                    env.step(0.5)
            finally:
                env._operation_lock.release()

    def test_old_episode_result_with_reused_action_id_is_ignored(self):
        import json
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            env.stream_id = "stream"
            env.last_state_id = 100
            old = completed(2)
            fresh = completed(101)
            fresh["episode_id"] = "new-episode"
            with patch.object(env, "socket") as sock:
                sock.recvfrom.side_effect = [(json.dumps(s).encode(), ("127.0.0.1", 1234))
                                            for s in (old, fresh)]
                result = env.receive_state(step_action_id=1, step_episode_id="new-episode")
                self.assertEqual(result["episode_id"], "new-episode")

    def test_slow_movement_expands_default_timeout(self):
        before = state()
        before.update(drop_range=dict(valid=True, min_x=-3, max_x=3),
                      ai_move_speed=0.5, fixed_delta_time=0.02, time_scale=1)
        self.assertGreater(UnityEnv._movement_timeout(before, 0), 10)
        before["time_scale"] = 0.5
        self.assertGreater(UnityEnv._movement_timeout(before, 0), 17)
        before["ai_move_speed"] = 0
        with self.assertRaises(RuntimeError):
            UnityEnv._movement_timeout(before, 0)

    def test_game_over_during_movement_returns_terminal_without_drop(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            env._action_episode = "episode1"
            terminal = completed()
            terminal["game_over"] = True
            terminal["step_result"].update(drop_success=False, dropped_fruit_id=0,
                                           physics_steps=0, movement_steps=10)
            with patch.object(env, "receive_state", side_effect=[state(), terminal]), patch.object(env, "_send"):
                result, reward, done, info = env.step(0.5)
                self.assertTrue(done)
                self.assertFalse(info["drop_success"])
                self.assertEqual(reward, 3)
                self.assertIsNone(env._pending_step)


if __name__ == "__main__":
    unittest.main()
