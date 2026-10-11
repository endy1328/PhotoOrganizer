import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QTimer, QThread, QEventLoop
from PySide6.QtWidgets import QApplication
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import AppSettings, PreviewBundle
from photo_organizer.operation_control import OperationStopped
from photo_organizer.job_store import JobState
from photo_organizer.ui.main_window import MainWindow


class OperationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        config = Mock()
        config.load.return_value = AppSettings(restore_last_job=False, autosave_job_changes=False)
        self.window = MainWindow(OrganizerEngine(Path.cwd()), config)
        self.window._global_settings.autosave_job_changes = False
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window._job_dirty = False
        self.window.close()

    def test_worker_keeps_ui_responsive_and_progress_on_ui_thread(self):
        ui_thread = threading.get_ident()
        seen = []
        self.window._update_progress = lambda *args: seen.append(threading.get_ident())
        ticks = []
        timer = QTimer(self.window)
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        def operation(*, control, progress_callback):
            self.assertNotEqual(threading.get_ident(), ui_thread)
            threading.Event().wait(.05)
            progress_callback('진행', 1, 1)
            return 'result'
        result = self.window._run_engine_operation(operation)
        timer.stop()
        self.assertEqual(result, 'result')
        self.assertGreater(len(ticks), 2)
        self.assertEqual(seen, [ui_thread])

    def test_pause_then_resume_and_stop_is_responsive(self):
        observed = []
        def operation(*, control, progress_callback):
            threading.Event().wait(.05)
            observed.append('file done')
            if not control.checkpoint():
                return 'stopped'
            observed.append('resumed')
            threading.Event().wait(.1)
            return 'stopped' if not control.checkpoint() else 'done'
        QTimer.singleShot(5, self.window._toggle_operation_pause)
        def resume():
            observed.append('paused' if self.window._operation_control.paused else 'not paused')
            self.window._toggle_operation_pause()
        QTimer.singleShot(80, resume)
        QTimer.singleShot(100, self.window._request_operation_stop)
        result = self.window._run_engine_operation(operation)
        self.assertEqual(result, 'stopped')
        self.assertEqual(observed, ['file done', 'paused', 'resumed'])
        self.assertTrue(self.window._operation_stopped)
        self.assertFalse(self.window.pause_button.isEnabled())
        self.assertFalse(self.window.stop_button.isEnabled())

    def test_busy_tables_and_autosave_are_locked(self):
        self.window._set_busy(True)
        def operation(*, control, progress_callback):
            threading.Event().wait(.06)
            return 'done'
        seen = []
        def inspect():
            seen.append(self.window.preview_table.isEnabled())
            seen.append(self.window.results_table.isEnabled())
            seen.append(self.window.phone_transfer_button.isEnabled())
            self.window._autosave_job()
        with patch.object(self.window, '_write_recent_job') as save:
            QTimer.singleShot(5, inspect)
            self.window._run_engine_operation(operation)
        save.assert_not_called()
        self.assertEqual(seen, [False, False, False])
        self.window._set_busy(False)

    def test_stop_releases_paused_worker(self):
        def operation(*, control, progress_callback):
            threading.Event().wait(.02)
            return 'done' if control.checkpoint() else 'stopped'
        paused = []
        QTimer.singleShot(5, self.window._toggle_operation_pause)
        def stop():
            paused.append(self.window._operation_control.paused)
            self.window._request_operation_stop()
        QTimer.singleShot(60, stop)
        self.assertEqual(self.window._run_engine_operation(operation), 'stopped')
        self.assertEqual(paused, [True])
        self.assertTrue(self.window._operation_stopped)

    def test_busy_image_metadata_and_tabs_do_not_start_detail_work(self):
        self.window._set_busy(True)
        with patch.object(self.window, '_metadata_entries_for_path') as metadata, patch.object(self.window, '_selected_image_source_path') as selected:
            self.window._update_selection_detail('preview')
            self.window._update_preview_image('preview')
        metadata.assert_not_called()
        selected.assert_not_called()
        self.assertFalse(self.window.tabs.tabBar().isEnabled())
        self.window._set_busy(False)
        self.assertTrue(self.window.tabs.tabBar().isEnabled())

    def test_preview_worker_error_is_shown_without_message_box(self):
        sentinel = PreviewBundle()
        self.window.last_preview_bundle = sentinel
        self.window._build_request = Mock(return_value=Mock())
        self.window._request_signature = Mock(return_value=('source', 'target'))
        with patch.object(self.window, '_run_engine_operation', side_effect=ValueError('worker failed')), patch('photo_organizer.ui.main_window.QMessageBox.warning') as warning:
            self.window._handle_preview()
        self.assertIs(self.window.last_preview_bundle, sentinel)
        self.assertIn('worker failed', self.window.status_label.text())
        self.assertEqual(self.window.error_table.rowCount(), 1)
        self.assertFalse(self.window._busy)
        warning.assert_not_called()

    def test_worker_error_is_raised_without_foreground_dialog(self):
        def operation(*, control, progress_callback):
            raise ValueError('failed')
        with self.assertRaisesRegex(ValueError, 'failed'):
            self.window._run_engine_operation(operation)
        self.assertFalse(self.window._operation_active)
        self.assertFalse(self.window._busy)

    def test_last_file_stop_request_does_not_report_stopped_without_checkpoint(self):
        def operation(*, control, progress_callback):
            threading.Event().wait(.03)
            return 'complete'
        QTimer.singleShot(5, self.window._request_operation_stop)
        self.assertEqual(self.window._run_engine_operation(operation), 'complete')
        self.assertFalse(self.window._operation_stopped)

    def test_stopped_preview_preserves_previous_bundle_and_has_no_warning(self):
        sentinel = PreviewBundle()
        self.window.last_preview_bundle = sentinel
        self.window._build_request = Mock(return_value=Mock())
        self.window._request_signature = Mock(return_value=('source', 'target'))
        with patch.object(self.window, '_run_engine_operation', side_effect=OperationStopped()), patch('photo_organizer.ui.main_window.QMessageBox.warning') as warning:
            self.window._handle_preview()
        self.assertIs(self.window.last_preview_bundle, sentinel)
        self.assertIn('중단', self.window.status_label.text())
        warning.assert_not_called()

    def test_preview_stop_and_error_restore_pending_autosave(self):
        for error in (OperationStopped(), ValueError('preview failed')):
            with self.subTest(error=type(error).__name__):
                self.window._global_settings.autosave_job_changes = True
                self.window._job_state = JobState()
                self.window._job_dirty = True
                self.window._job_timer.setInterval(15)
                self.window._job_timer.start()
                self.window._build_request = Mock(return_value=Mock())
                self.window._request_signature = Mock(return_value=('source', 'target'))
                def operation(*args, **kwargs):
                    threading.Event().wait(.03)
                    raise error
                with patch.object(self.window.engine, 'preview', side_effect=operation), patch.object(self.window, '_write_recent_job') as save:
                    self.window._handle_preview()
                    loop = QEventLoop()
                    QTimer.singleShot(60, loop.quit)
                    loop.exec()
                    save.assert_called_once()
                self.window._global_settings.autosave_job_changes = False

    def test_autosave_waits_for_outer_completion_and_next_ui_event(self):
        self.window._global_settings.autosave_job_changes = True
        self.window._job_state = JobState()
        self.window._job_dirty = True
        self.window._job_timer.setInterval(15)
        self.window._job_timer.start()
        self.window._set_busy(True)
        with patch.object(self.window, '_write_recent_job') as save:
            self.window._run_engine_operation(lambda **kwargs: 'done')
            self.app.processEvents()
            self.assertFalse(self.window._job_timer.isActive())
            save.assert_not_called()
            self.window._set_busy(False)
            save.assert_not_called()
            loop = QEventLoop()
            QTimer.singleShot(60, loop.quit)
            loop.exec()
            save.assert_called_once()
        self.window._global_settings.autosave_job_changes = False
