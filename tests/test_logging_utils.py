import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.logging_utils import AppLogger


class SessionLogTests(unittest.TestCase):
    def test_multiple_same_time_sessions_do_not_overwrite(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as temporary:
            logger = AppLogger(Path(temporary))
            with patch('photo_organizer.logging_utils.datetime') as clock:
                clock.now.return_value = datetime(2026, 10, 10, 10, 0, 0)
                clock.fromtimestamp.side_effect = datetime.fromtimestamp
                first = logger.write_session_log([])
                first.write_text('existing session', encoding='utf-8')
                second = logger.write_session_log([])
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding='utf-8'), 'existing session')
