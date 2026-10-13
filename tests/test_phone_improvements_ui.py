from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import test_phone_transfer_ui as fixtures
from test_phone_transfer import MemoryPhone
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QSplitter


class PhoneImprovementsUiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PhoneTransferUiTests.setUpClass.__func__)
    setUp = fixtures.PhoneTransferUiTests.setUp
    wait_until = fixtures.PhoneTransferUiTests.wait_until
    _close_worker_dialogs = fixtures.PhoneTransferUiTests._close_worker_dialogs

    def dialog(self, preferences_dir=None):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        folder = SimpleNamespace(path=Path('target/output_20240101_CAM'), files=(), size=0)
        with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=[folder]):
            dialog = PhoneTransferDialog(None, Path('target'), backend_factory=fixtures.FakeBackend,
                preferences_dir=preferences_dir)
            self.wait_until(lambda: not dialog.busy and dialog.device_open)
        return dialog

    def test_cancel_completion_retains_last_progress(self):
        dialog = self.dialog()
        dialog._progress({'total_files':10, 'completed':3, 'bytes':30, 'total_bytes':100})
        maximum, value = dialog.progress_bar.maximum(), dialog.progress_bar.value()
        dialog._completed('transfer', {'results':[SimpleNamespace(source=Path('a.jpg'), status='CANCELLED',
            message='Cancelled', remote_id='')], 'log_error':''})
        self.assertEqual((dialog.progress_bar.maximum(), dialog.progress_bar.value()), (maximum, value))
        self.assertIn('취소', dialog.status_label.text())

    def test_busy_lists_stay_readable_but_folder_checkbox_cannot_change(self):
        from PySide6.QtTest import QTest
        dialog = self.dialog()
        dialog.show(); self.app.processEvents()
        dialog.busy = True; dialog.active_operation = 'transfer'; dialog._update_buttons()
        self.assertTrue(dialog.remote_tree.isEnabled())
        self.assertTrue(dialog.output_tree.isEnabled())
        self.assertFalse(dialog.model_selection.isEnabled())
        item = dialog.output_tree.topLevelItem(0)
        before = item.checkState(0)
        dialog.output_tree.setCurrentItem(item)
        QTest.keyClick(dialog.output_tree, Qt.Key_Space)
        self.assertEqual(item.checkState(0), before)
        with patch.object(dialog.worker, 'submit') as submit:
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
        submit.assert_not_called()

    def test_splitter_headers_and_view_preferences_survive_reopening(self):
        with tempfile.TemporaryDirectory() as temp:
            first = self.dialog(Path(temp))
            self.assertIsInstance(first.panel_splitter, QSplitter)
            self.assertTrue(first.results_table.horizontalHeader().sectionsMovable())
            self.assertEqual(first.results_table.horizontalHeader().sectionResizeMode(1), QHeaderView.Interactive)
            first.results_table.setColumnWidth(1, 280)
            first.results_table.horizontalHeader().moveSection(1, 0)
            first.reject(); self.wait_until(lambda: not first.worker.isRunning())
            second = self.dialog(Path(temp))
            self.assertEqual(second.results_table.columnWidth(1), 280)
            self.assertEqual(second.results_table.horizontalHeader().logicalIndex(0), 1)

    def test_progress_uses_bytes_for_one_large_video(self):
        dialog = self.dialog()
        dialog._progress({'total_files':1, 'completed':0, 'bytes':50, 'total_bytes':100, 'file':'large.mp4'})
        self.assertEqual(dialog.progress_bar.value() / dialog.progress_bar.maximum(), 0.5)
        self.assertIn('large.mp4', dialog.status_label.text())

    def retry_dialog(self, target):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        from photo_organizer.phone_transfer import RemoteEntry

        class RetryPhone(MemoryPhone):
            cancel_after_upload = None
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def list_devices(self): return [SimpleNamespace(id='phone', name='Test phone')]
            def open_device(self, device): self.children.setdefault('storage', [])
            def list_children(self, parent):
                return [RemoteEntry('storage', 'Internal storage', True)] if parent == 'DEVICE' else super().list_children(parent)
            def upload_new(self, *args):
                entry = super().upload_new(*args)
                if self.cancel_after_upload is not None:
                    callback, self.cancel_after_upload = self.cancel_after_upload, None
                    callback()
                return entry

        backend = RetryPhone()
        folder = target / 'output_20240101_CAM'
        folder.mkdir()
        (folder / 'a.jpg').write_bytes(b'photo-a')
        (folder / 'b.jpg').write_bytes(b'photo-b')
        dialog = PhoneTransferDialog(None, target, backend_factory=lambda: backend)
        self.wait_until(lambda: not dialog.busy and dialog.device_open)
        dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
        self.wait_until(lambda: not dialog.busy)
        backend.cancel_after_upload = dialog.worker.cancel_event.set
        dialog._start_transfer()
        self.wait_until(lambda: not dialog.busy)
        return dialog, backend, folder

    def test_retry_only_cancelled_files_preserves_completed_results(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog, backend, folder = self.retry_dialog(Path(temp))
            self.assertEqual([entry.status for entry in dialog.last_results], ['COPIED', 'CANCELLED'])
            self.assertTrue(dialog.retry_button.isEnabled())
            dialog.retry_button.click()
            self.wait_until(lambda: not dialog.busy)
            self.assertEqual([entry.status for entry in dialog.last_results], ['COPIED', 'COPIED'])
            self.assertEqual(backend.overwrites, [])
            self.assertEqual(set(backend.data.values()), {b'photo-a', b'photo-b'})
            self.assertEqual(dialog.results_table.rowCount(), 2)

    def test_retry_requires_same_destination_and_unchanged_source(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog, backend, folder = self.retry_dialog(Path(temp))
            dialog.destination_stack[-1] = ('other', 'Other destination')
            dialog._update_buttons()
            self.assertFalse(dialog.retry_button.isEnabled())
            dialog.destination_stack[-1] = ('storage', 'Internal storage')
            (folder / 'b.jpg').write_bytes(b'changed-photo')
            dialog._update_buttons()
            dialog.retry_button.click()
            self.wait_until(lambda: not dialog.busy)
            self.assertFalse(dialog.device_open)
            self.assertEqual(set(backend.data.values()), {b'photo-a'})
            self.assertIn('변경', dialog.status_label.text())

    def test_phase_and_cancelled_progress_do_not_advance_the_bar(self):
        dialog = self.dialog()
        dialog.busy = True; dialog.active_operation = 'transfer'
        dialog._progress({'total_files':10,'completed':3,'bytes':30,'total_bytes':100})
        dialog._phase_changed('waiting:swap', False)
        self.assertIn('응답 대기', dialog.phase_label.text())
        dialog._cancel()
        value = dialog.progress_bar.value()
        dialog._progress({'total_files':10,'completed':10,'bytes':30,'total_bytes':100})
        self.assertEqual(dialog.progress_bar.value(), value)
        self.assertIn('교체 확인', dialog.phase_label.text())

    def test_same_name_different_device_cannot_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog, backend, folder = self.retry_dialog(Path(temp))
            dialog.device_combo.setItemData(0, 'different-connected-phone')
            dialog._update_buttons()
            self.assertFalse(dialog.retry_button.isEnabled())

    def test_small_window_keeps_bottom_controls_inside(self):
        dialog = self.dialog()
        dialog.resize(640, 600)
        dialog.show(); self.app.processEvents()
        self.assertLessEqual(dialog.minimumSizeHint().height(), 600)
        self.assertLessEqual(dialog.height(), 600)
        self.assertLessEqual(dialog.close_button.geometry().bottom(), dialog.height())

    def test_fullscreen_close_preserves_preceding_maximized_state(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            dialog = self.dialog(Path(temp))
            dialog.showMaximized(); self.app.processEvents()
            dialog.fullscreen_button.click(); self.app.processEvents()
            dialog.reject(); self.wait_until(lambda: not dialog.worker.isRunning())
            saved = json.loads((Path(temp) / 'phone_view_preferences.json').read_text(encoding='utf-8'))
            self.assertTrue(saved['maximized'])


if __name__ == '__main__':
    unittest.main()
