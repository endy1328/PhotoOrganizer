import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from photo_organizer.phone_transfer import scan_outputs, TransferResult
from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
import test_phone_transfer_ui as fixtures


class PhoneSizeDialogTests(unittest.TestCase):
    setUp = fixtures.PhoneTransferUiTests.setUp
    setUpClass = classmethod(fixtures.PhoneTransferUiTests.setUpClass.__func__)
    wait_until = fixtures.PhoneTransferUiTests.wait_until
    _close_worker_dialogs = fixtures.PhoneTransferUiTests._close_worker_dialogs
    def test_limit_summary_and_result_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'output_day'
            folder.mkdir()
            (folder / 'big.MP4').write_bytes(b'v' * 1000000)
            (folder / 'photo.jpg').write_bytes(b'p' * 100)
            with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=scan_outputs(root)):
                dialog = PhoneTransferDialog(None, root, backend_factory=fixtures.FakeBackend, video_limit_bytes=1000000)
                self.wait_until(lambda: not dialog.busy)
                self.assertIn('1 MB', dialog.video_limit_label.text())
                self.assertEqual(dialog.output_tree.topLevelItem(0).text(1), '1')
                self.assertEqual(dialog.output_tree.topLevelItem(0).text(3), '1')
                self.assertIn('제외 1', dialog.selection_label.text())
                dialog._completed('transfer', {'results': [TransferResult(folder/'big.MP4', 'SIZE_EXCLUDED', '용량 제한으로 제외')], 'log_error': ''})
                self.assertIn('용량 제한 제외', dialog.results_table.item(0,0).text())
                self.assertIn('1개', dialog.status_label.text())
                dialog.reject()
                dialog.worker.wait(2000)

    def test_all_excluded_worker_reports_without_creating_phone_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'output_day'
            folder.mkdir()
            (folder / 'big.mp4').write_bytes(b'v' * 1000000)
            backend = fixtures.FakeBackend()
            with patch.object(backend, 'create_folder', side_effect=AssertionError('Must not create a phone folder')):
                dialog = PhoneTransferDialog(None, root, backend_factory=lambda: backend, video_limit_bytes=1000000)
                self.wait_until(lambda: not dialog.busy and dialog.device_open)
                dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
                self.wait_until(lambda: not dialog.busy)
                dialog._start_transfer()
                self.wait_until(lambda: not dialog.busy)
                self.assertEqual(dialog.results_table.rowCount(), 1)
                self.assertEqual(dialog.results_table.item(0, 0).text(), '용량 제한 제외')
                self.assertIn('SIZE_EXCLUDED', self.logger_factory.return_value.write_session_log.call_args.args[0][0].message)
                dialog.reject()
                dialog.worker.wait(2000)
