from pathlib import Path
import tempfile
from itertools import count
import unittest
from unittest.mock import Mock,patch
from suika_ai.parallel_play import run_parallel

class PlayerErrorVisibilityTests(unittest.TestCase):
    def test_only_opted_in_error_keeps_the_owned_gui_player(self):
        for enabled,status in ((True,'error'),(False,'error'),(True,'completed')):
            with self.subTest(enabled=enabled,status=status),tempfile.TemporaryDirectory() as tmp:
                exe=Path(tmp)/'player.exe';exe.write_bytes(b'fake')
                child=Mock(pid=43210);child.poll.return_value=None
                result=dict(game_id='game_00',status=status,steps=0,elapsed_seconds=.1)
                with patch('suika_ai.parallel_play.time.monotonic',side_effect=count(1)),patch('suika_ai.parallel_play.check_ports'),patch('suika_ai.parallel_play.UnityEnv'),patch('suika_ai.parallel_play.subprocess.Popen',return_value=child),patch('suika_ai.parallel_play.collect_worker',return_value=result),patch('suika_ai.presentation.PresentationControls'):
                    summary=run_parallel(exe,Path(tmp)/'run',games=1,view_games=0,keep_player_on_error=enabled)
                self.assertEqual(summary['workers'][0]['status'],status)
                self.assertEqual(child.terminate.called,not(enabled and status=='error'))

    def test_headless_failures_cannot_leave_hidden_players(self):
        with self.assertRaisesRegex(ValueError,'visible GUI'):
            run_parallel('unused.exe','unused',headless=True,keep_player_on_error=True)
