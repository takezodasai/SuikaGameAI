import base64
import copy
import json
import socket
import threading
import unittest
from unittest.mock import patch

from suika_ai.unity_env import UnityEnv, parse_state


def state(sequence=1, episode="episode1", request="", fruits=None):
    return dict(protocol_version=2, stream_id="stream", episode_id=episode,
                state_id=sequence, reset_request_id=request, game_over=False,
                score=0, fruits=[] if fruits is None else fruits,
                current_fruit=dict(present=True, type=0, x=0.5), next_fruit_type=2)


class ProtocolTests(unittest.TestCase):
    def test_variable_fruit_count_and_physics(self):
        fruit = dict(id=42, type=6, x=-1.5, y=2, vx=0.2, vy=-1,
                     angle=120, angular_velocity=-30)
        self.assertEqual(parse_state(state(fruits=[fruit]))["fruits"][0], fruit)
        self.assertEqual(parse_state(state())["fruits"], [])
        for field in fruit:
            broken = copy.deepcopy(fruit)
            del broken[field]
            with self.assertRaises(ValueError):
                parse_state(state(fruits=[broken]))
        with self.assertRaises(ValueError):
            parse_state(state(fruits=[fruit, fruit]))
        fruit["vx"] = float("nan")
        with self.assertRaises(ValueError):
            parse_state(state(fruits=[fruit]))

    def test_fragments_out_of_order_and_duplicate(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            raw = json.dumps(state()).encode()
            fragments = [dict(message_type="state_fragment", stream_id="stream",
                              state_id=1, count=2, index=i,
                              data=base64.b64encode(part).decode())
                         for i, part in enumerate((raw[:80], raw[80:]))]
            self.assertIsNone(env._decode(json.dumps(fragments[1])))
            self.assertIsNone(env._decode(json.dumps(fragments[1])))
            self.assertEqual(env._decode(json.dumps(fragments[0])), state())
            # JSON arrays in a fully assembled payload must not crash receive_state.
            invalid = dict(message_type="state_fragment", stream_id="stream", state_id=2,
                           count=1, index=0, data=base64.b64encode(b"[]").decode())
            with self.assertRaises(ValueError):
                env._decode(json.dumps(invalid))

    def test_stale_and_malformed_packets_are_ignored(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            packets = [b"bad json", json.dumps(state(2)).encode(),
                       json.dumps(state(1)).encode(), json.dumps(state(3)).encode()]
            with patch.object(env, "socket") as sock:
                sock.recvfrom.side_effect = [(p, ("127.0.0.1", 9999)) for p in packets]
                self.assertEqual(env.receive_state()["state_id"], 2)
                self.assertEqual(env.receive_state()["state_id"], 3)

    def test_reset_retries_same_id_and_waits_for_completion(self):
        with UnityEnv(local=("127.0.0.1", 0)) as env:
            sent = []
            with patch.object(env, "_send", side_effect=sent.append), patch.object(env, "receive_state") as receive:
                def observation(*args):
                    if not any(m.get("command") == "reset" for m in sent):
                        return state()
                    requests = [m for m in sent if m.get("command") == "reset"]
                    if len(requests) == 1:
                        raise TimeoutError()
                    return state(3, "episode2", requests[-1]["request_id"])
                receive.side_effect = observation
                result = env.reset()
                self.assertEqual(result["episode_id"], "episode2")
                requests = [m for m in sent if m.get("command") == "reset"]
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[0], requests[1])
                self.assertEqual(requests[0]["episode_id"], "episode1")

    def test_local_udp_round_trip(self):
        # A real loopback server; no Unity required. Bound receive port is configurable.
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(2)
        errors = []
        def serve():
            try:
                _, peer = server.recvfrom(65535)  # observe
                server.sendto(json.dumps(state()).encode(), peer)
                while True:
                    packet, peer = server.recvfrom(65535)
                    command = json.loads(packet)
                    if command.get("command") == "observe":
                        server.sendto(json.dumps(state(2)).encode(), peer)
                    elif command.get("command") == "reset":
                        server.sendto(json.dumps(state(3, "episode2", command["request_id"])).encode(), peer)
                        return
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with UnityEnv(server=server.getsockname(), local=("127.0.0.1", 0)) as env:
                self.assertEqual(env.receive_state()["episode_id"], "episode1")
                self.assertEqual(env.reset()["episode_id"], "episode2")
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
