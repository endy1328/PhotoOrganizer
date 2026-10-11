import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from photo_organizer.models import AppSettings, OrganizeRequest, PreviewBundle, PreviewItem, ExecutionBundle
from photo_organizer.engine import OrganizerEngine
from photo_organizer.ui.main_window import MainWindow
from photo_organizer.ui.execution_controller import ExecutionConfirmDialog


def preview():
    return PreviewBundle(preview_items=[PreviewItem(
        item_id='one', media_type='photo', source_path='one.jpg', target_directory='out',
        target_path='out/one.jpg', new_filename='one.jpg', write_mode='NEW',
        captured_at='2026-10-12', datetime_source='파일명', model_name='A', model_source='메타', warnings=[])])


class ExecutionControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        config = Mock()
        config.load.return_value = AppSettings(restore_last_job=False, autosave_job_changes=False)
        self.window = MainWindow(OrganizerEngine(Path.cwd()), config)
        self.addCleanup(self.close_window)
        self.request = OrganizeRequest(Path('source'), Path('target'), preview_only=False)

    def close_window(self):
        self.window._job_dirty = False
        self.window.close()

    def test_cancel_precedes_execution_checkpoint_and_media_operation(self):
        w = self.window
        w.last_preview_bundle = preview()
        w.last_preview_signature = w._request_signature(self.request)
        with patch.object(w, '_request_from_inputs', return_value=self.request), \
             patch.object(w, '_build_request', return_value=self.request), \
             patch.object(w, '_job_validate_before_execute', return_value=True), \
             patch.object(w, '_job_execution_checkpoint') as checkpoint, \
             patch.object(w.engine, 'execute') as execute, \
             patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Rejected):
            w._handle_execute()
        checkpoint.assert_not_called()
        execute.assert_not_called()
        self.assertFalse(w._job_state.execution_started)
        self.assertFalse(w._busy)

    def test_accept_and_snapshot_use_only_included_items(self):
        bundle = preview()
        second = preview().preview_items[0]
        second.item_id = 'excluded'
        second.included = False
        bundle.preview_items.append(second)
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            self.assertTrue(self.window._confirm_execution(self.request, bundle))
        self.assertEqual(self.window._pending_execution_estimate.photo_count, 1)

    def test_progress_dock_close_does_not_stop_worker_and_can_reopen(self):
        w = self.window
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        checks = []
        def operation(*, control, progress_callback):
            with control.file_activity('one', 'one.jpg', 'output'):
                threading.Event().wait(.18)
            control.report_file_result('one', 'one.jpg', 'SUCCESS')
            progress_callback('정리', 1, 1)
            return ExecutionBundle()
        def inspect():
            w._show_execution_progress()
            w.execution_progress_dock.close()
            checks.append(w._operation_control.stop_requested)
            w._show_execution_progress()
            checks.append(not w.execution_progress_dock.isHidden())
        QTimer.singleShot(40, inspect)
        w._run_engine_operation(operation, execution_progress=True)
        self.assertEqual(checks, [False, True])
        self.assertIn('1/1', w.execution_summary_label.text())
        self.assertEqual(w.execution_progress_dock.history_table.rowCount(), 1)
        self.assertFalse(w._execution_tracking)

    def test_preview_does_not_reset_last_execution_details(self):
        w = self.window
        w.execution_progress_dock.begin(1)
        w.execution_progress_dock.note_result('old.jpg', 'SUCCESS')
        w._run_engine_operation(lambda **kwargs: PreviewBundle())
        self.assertEqual(w.execution_progress_dock.history_table.rowCount(), 1)

    def test_error_finishes_tracking_without_learning_from_failure(self):
        w = self.window
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        def fail(**kwargs):
            raise ValueError('failed')
        with patch.object(w._estimate_history, 'record') as record:
            with self.assertRaisesRegex(ValueError, 'failed'):
                w._run_engine_operation(fail, execution_progress=True)
        record.assert_not_called()
        self.assertFalse(w._execution_tracking)
        self.assertIn('오류', w.execution_summary_label.text())

    def test_second_result_poll_and_burst_preserve_failure_totals(self):
        from photo_organizer.operation_control import OperationControl
        w = self.window
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        w._operation_control = OperationControl()
        w._begin_execution_progress()
        w._operation_control.report_file_result('one', 'one.jpg', 'SUCCESS')
        w._refresh_execution_progress(force=True)
        w._operation_control.report_file_result('bad', 'bad.jpg', 'ERROR')
        for i in range(70):
            w._operation_control.report_file_result(str(i), f'{i}.jpg', 'SUCCESS')
        w._refresh_execution_progress(force=True)
        self.assertTrue(w._execution_had_error)
        self.assertEqual(len(w._execution_completed_ids), 72)
        self.assertIn('실패 1', w.execution_progress_dock.summary_label.text())
        w._finish_execution_progress()

    def test_reset_restores_progress_dock_to_bottom_and_hidden(self):
        from PySide6.QtCore import Qt
        w = self.window
        w.execution_progress_dock.setFloating(True)
        w._show_execution_progress()
        w.restore_default_dock_layout()
        self.assertFalse(w.execution_progress_dock.isFloating())
        self.assertTrue(w.execution_progress_dock.isHidden())
        self.assertEqual(w.dockWidgetArea(w.execution_progress_dock), Qt.BottomDockWidgetArea)
        self.assertFalse(w._dock_user_visibility['execution_progress'])

    def test_finish_display_exception_does_not_hold_worker_or_busy_state(self):
        w = self.window
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        with patch.object(w, '_finish_execution_progress', side_effect=ValueError('display failed')):
            self.assertEqual(w._run_engine_operation(lambda **kwargs: 'done', execution_progress=True), 'done')
        self.assertFalse(w._operation_active)
        self.assertFalse(w._busy)
        self.assertFalse(w._execution_tracking)

    def test_pause_is_visible_in_detached_progress_panel(self):
        from photo_organizer.operation_control import OperationControl
        w = self.window
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        w._operation_control = OperationControl()
        w._begin_execution_progress()
        w._operation_control.request_pause()
        w._refresh_execution_progress(force=True)
        self.assertIn('일시정지 요청', w.execution_progress_dock.status_label.text())
        w._operation_control.resume()
        w._finish_execution_progress()

    def test_paused_wait_is_excluded_from_eta_learning_elapsed(self):
        from photo_organizer.operation_control import OperationControl
        w = self.window
        now = [100.0]
        w._execution_clock = lambda: now[0]
        with patch.object(ExecutionConfirmDialog, 'exec', return_value=QDialog.Accepted):
            w._confirm_execution(self.request, preview())
        w._operation_control = OperationControl()
        w._begin_execution_progress()
        now[0] = 110.0
        w._operation_control._paused = True
        w._refresh_execution_progress(force=True)
        now[0] = 210.0
        w._refresh_execution_progress(force=True)
        self.assertEqual(w._execution_active_elapsed, 10.0)
        self.assertIn('일시정지', w.execution_progress_dock.status_label.text())
        now[0] = 220.0
        w._operation_control._paused = False
        w._refresh_execution_progress(force=True)
        now[0] = 230.0
        w._refresh_execution_progress(force=True)
        self.assertEqual(w._execution_active_elapsed, 20.0)
        w._finish_execution_progress()

    def test_progress_visibility_is_saved_without_showing_hidden_detail_panels(self):
        import tempfile
        from photo_organizer.ui.view_preferences import ViewPreferences
        w = self.window
        w.show()
        self.app.processEvents()
        w._set_all_docks_visible(False)
        w._show_execution_progress()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'view.json'
            prefs = ViewPreferences(w, path)
            self.assertTrue(prefs.save())
            w.execution_progress_dock.hide()
            prefs.restore()
            self.assertFalse(w.execution_progress_dock.isHidden())
            self.assertTrue(w.image_dock.isHidden())
            self.assertTrue(w.detail_dock.isHidden())
            self.assertFalse(w.details_toggle.isChecked())

    def test_default_progress_open_spans_bottom_and_resize_preserves_it(self):
        w = self.window
        w.resize(1204, 1032)
        w.show()
        self.app.processEvents()
        w._show_execution_progress()
        self.app.processEvents()
        self.assertGreater(w.execution_progress_dock.width(), w.width() * .9)
        w.resize(1920, 1000)
        self.app.processEvents()
        w.resize(1204, 1032)
        self.app.processEvents()
        self.assertGreater(w.execution_progress_dock.width(), w.width() * .9)


if __name__ == '__main__':
    unittest.main()
