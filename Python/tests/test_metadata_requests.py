import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv
from test_unity_env import state

META=dict(schema_version=1,unity_version='2022.3.21f1',build_guid='b',fixed_delta_time=.02,physics_profiles=[{}],boundaries=[{}])
class MetadataRequestTests(unittest.TestCase):
    def test_correlated_reply_rejects_stale_complete_metadata(self):
        with UnityEnv(local=('127.0.0.1',0)) as env:
            sent=[];reads=[]
            def receive(timeout):
                reads.append(1)
                return dict(state(),environment=META,metadata_request_ids_supported=True,
                    environment_request_id='older-request' if len(reads)==1 else sent[-1]['request_id'])
            with patch.object(env,'_send',side_effect=sent.append),patch.object(env,'receive_state',side_effect=receive):
                self.assertEqual(env.get_environment(),META)
            self.assertEqual(len(reads),2)
            self.assertEqual(len(sent),1)
            self.assertTrue(sent[0]['request_id'])

    def test_retries_share_request_id_and_old_players_remain_supported(self):
        clock=[1.0];sent=[]
        with UnityEnv(local=('127.0.0.1',0)) as env:
            def receive(timeout):
                clock[0]+=.5
                if len(sent)<3:raise TimeoutError()
                return dict(state(),environment=META) # Old Player: no capability marker.
            with patch('suika_ai.unity_env.time.monotonic',side_effect=lambda:clock[0]),patch.object(env,'_send',side_effect=sent.append),patch.object(env,'receive_state',side_effect=receive):
                self.assertEqual(env.get_environment(),META)
            self.assertEqual(len(sent),3)
            self.assertEqual(len({x['request_id'] for x in sent}),1)

    def test_overlapping_operations_do_not_send_a_second_request(self):
        with UnityEnv(local=('127.0.0.1',0)) as env,patch.object(env,'_send') as send:
            env._operation_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError,'in progress'):env.get_environment()
            finally:env._operation_lock.release()
            send.assert_not_called()

    def test_lock_is_released_after_timeout(self):
        with UnityEnv(local=('127.0.0.1',0)) as env,patch.object(env,'_get_environment',side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):env.get_environment()
            self.assertFalse(env._operation_lock.locked())
