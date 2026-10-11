import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from photo_organizer.models import AppSettings, PreviewBundle, ExecutionBundle
from photo_organizer.ui.main_window import MainWindow, SettingsDialog


class JobUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        confirmation = patch('photo_organizer.ui.execution_controller.ExecutionConfirmDialog.exec', return_value=1)
        confirmation.start()
        self.addCleanup(confirmation.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Mock()
        self.engine.base_dir = Path(self.temp.name)
        self.config = Mock()
        self.config.load.return_value = AppSettings(restore_last_job=False)
        self.window = MainWindow(self.engine, self.config)
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window._job_dirty = False
        self.window.close()

    def test_buttons_and_default_preferences(self):
        self.assertEqual(self.window.job_open_button.text(), '작업 열기')
        dialog = SettingsDialog(None, AppSettings())
        self.assertTrue(dialog.restore_last_job_checkbox.isChecked())
        self.assertTrue(dialog.autosave_job_checkbox.isChecked())
        dialog.restore_last_job_checkbox.setChecked(False)
        self.assertFalse(dialog.to_settings(AppSettings()).restore_last_job)

    def test_failed_open_preserves_current_work(self):
        sentinel = PreviewBundle()
        self.window.last_preview_bundle = sentinel
        before = self.window.source_edit.text()
        with patch('photo_organizer.ui.job_controller.load_job', side_effect=ValueError('invalid')), patch.object(QMessageBox, 'warning'):
            self.assertFalse(self.window._open_job_path(Path(self.temp.name) / 'bad.pojob.json'))
        self.assertIs(self.window.last_preview_bundle, sentinel)
        self.assertEqual(self.window.source_edit.text(), before)

    def test_completed_job_blocks_preview_and_execute_without_request_writes(self):
        from photo_organizer.job_store import JobState
        self.window._job_state = JobState(phase='EXECUTION_FINISHED', execution_started=True)
        with patch.object(QMessageBox, 'information'), patch.object(QMessageBox, 'warning'), patch.object(self.window, '_build_request') as request:
            self.window._handle_preview()
            self.window._handle_execute()
        request.assert_not_called()
        self.engine.execute.assert_not_called()

    def test_busy_close_is_ignored_and_job_buttons_disabled(self):
        self.window._set_busy(True)
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.window.job_open_button.isEnabled())
        self.window._set_busy(False)

    def test_loaded_job_settings_are_not_saved_to_global(self):
        self.window._job_loaded = True
        self.window.source_edit.setText('작업경로')
        self.config.save.reset_mock()
        self.window._save_current_inputs()
        self.config.save.assert_not_called()

    def test_checkpoint_failure_prevents_execution(self):
        from photo_organizer.job_store import JobState
        self.window._job_state = JobState(phase='PREVIEW_READY')
        with patch('photo_organizer.ui.job_controller.save_job', side_effect=OSError('disk full')), patch.object(QMessageBox, 'warning'):
            self.assertFalse(self.window._job_execution_checkpoint())
        self.assertFalse(self.window._job_state.execution_started)
        self.assertEqual(self.window._job_state.phase, 'PREVIEW_READY')

    def test_dirty_new_cancel_preserves_preview(self):
        self.window._job_dirty = True
        sentinel = PreviewBundle()
        self.window.last_preview_bundle = sentinel
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.window._new_job()
        self.assertIs(self.window.last_preview_bundle, sentinel)

    def test_settings_current_preserves_preferences(self):
        self.window._global_settings.autosave_job_changes = False
        self.assertFalse(self.window._current_settings().autosave_job_changes)

    def _prepare_real_preview(self):
        from photo_organizer.engine import OrganizerEngine
        base = Path(self.temp.name)
        source, target = base / 'source', base / 'target'
        source.mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        (source / '20240101_120000_SM-A.jpg').write_bytes(b'filename fallback')
        self.window.engine = OrganizerEngine(base)
        self.window.settings.mobile_output_enabled = False
        self.window.source_edit.setText(str(source))
        self.window.target_edit.setText(str(target))
        self.window._handle_preview()
        self.assertEqual(self.window._job_state.phase, 'PREVIEW_READY')
        return base / 'saved.pojob.json'

    def test_save_open_preview_and_execute_once(self):
        path = self._prepare_real_preview()
        with patch('photo_organizer.ui.job_controller.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(path))
        self.assertFalse(self.window._job_dirty)
        self.assertTrue(self.window.execute_button.isEnabled())
        self.window._handle_execute()
        self.assertEqual(self.window._job_state.phase, 'EXECUTION_FINISHED')
        self.assertTrue(Path(self.window.last_execution_bundle.execution_results[0].target_path).is_file())
        self.assertFalse(self.window.execute_button.isEnabled())
        self.assertFalse(self.window.preview_table.item(0, 3).flags() & Qt.ItemIsEditable)

    def test_changed_source_blocks_loaded_preview_before_request(self):
        path = self._prepare_real_preview()
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(path))
        source = Path(self.window.last_preview_bundle.preview_items[0].source_path)
        source.write_bytes(b'changed')
        with patch.object(QMessageBox, 'warning') as warning, patch.object(self.window, '_build_request') as request:
            self.window._handle_execute()
        warning.assert_called_once()
        request.assert_not_called()

    def test_opaque_metadata_is_not_deepcopied_for_checkpoint_or_save(self):
        from photo_organizer.models import MediaItem
        class Opaque:
            def __deepcopy__(self, memo):
                raise AssertionError('raw EXIF deepcopy')
        path = self._prepare_real_preview()
        self.window.last_preview_bundle.media_items[0].metadata['opaque'] = Opaque()
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._job_execution_checkpoint())

    def test_save_as_has_independent_id_and_does_not_touch_first_file(self):
        path = self._prepare_real_preview()
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        old_id, old_bytes = self.window._job_state.job_id, path.read_bytes()
        other = path.with_name('other.pojob.json')
        with patch('photo_organizer.ui.job_controller.QFileDialog.getSaveFileName', return_value=(str(other), '')):
            self.assertTrue(self.window._save_job(save_as=True))
        self.assertNotEqual(self.window._job_state.job_id, old_id)
        self.assertEqual(path.read_bytes(), old_bytes)

    def test_new_draft_replaces_recent_completed_work(self):
        from photo_organizer.job_store import load_job
        self._prepare_real_preview()
        self.window._handle_execute()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.window._new_job()
        self.window._autosave_job()
        recent = load_job(self.window._recent_job_path())
        self.assertEqual(recent.phase, 'DRAFT')
        self.assertIsNone(recent.preview_bundle)

    def test_completed_restore_displays_current_missing_separately(self):
        path = self._prepare_real_preview()
        self.window._handle_execute()
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        result = self.window.last_execution_bundle.execution_results[0]
        Path(result.target_path).unlink()
        self.assertTrue(self.window._open_job_path(path))
        self.assertIn('누락 1건', self.window.status_label.text())
        self.assertEqual(self.window.last_execution_bundle.execution_results[0].status, 'SUCCESS')

    def test_engine_exception_keeps_pending_checkpoint_and_unlocks_busy(self):
        from photo_organizer.job_store import load_job
        self._prepare_real_preview()
        with patch.object(self.window.engine, 'execute', side_effect=RuntimeError('unexpected')), patch.object(QMessageBox, 'warning'):
            self.window._handle_execute()
        self.assertFalse(self.window._busy)
        self.assertEqual(self.window._job_state.phase, 'EXECUTION_PARTIAL')
        self.assertTrue(self.window._job_state.execution_started)
        self.assertFalse(self.window.execute_button.isEnabled())
        self.assertEqual(load_job(self.window._recent_job_path()).phase, 'EXECUTION_PARTIAL')

    def test_restored_delete_candidates_are_unchecked_and_revalidated(self):
        from photo_organizer.models import DeleteReviewItem
        path = self._prepare_real_preview()
        self.window._handle_execute()
        item = self.window.last_preview_bundle.preview_items[0]
        self.window.last_execution_bundle.delete_review_items = [DeleteReviewItem(item.item_id, item.source_path, '복사 확인')]
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(path))
        self.assertFalse(self.window.delete_table.cellWidget(0, 0).isChecked())
        Path(item.source_path).write_bytes(b'changed source')
        self.window.delete_table.cellWidget(0, 0).setChecked(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(QMessageBox, 'warning'), patch.object(self.window.engine, 'delete_selected') as delete:
            self.window._handle_delete_review()
        delete.assert_not_called()

    def test_completed_processing_inputs_locked_but_transfer_settings_available(self):
        self._prepare_real_preview()
        self.window._handle_execute()
        for widget in (self.window.source_edit, self.window.target_edit, self.window.device_name_edit,
                       self.window.mode_combo, self.window.source_select_button, self.window.target_select_button):
            self.assertFalse(widget.isEnabled())
        settings = self.window._current_settings()
        settings.mobile_output_jpeg_quality = 37
        settings.model_name_mappings = {'SM-A': '별칭'}
        settings.phone_conflict_policy = 'skip'
        dialog = SettingsDialog(self.window, settings)
        self.assertFalse(dialog.mapping_table.isEnabled())
        self.assertFalse(dialog.model_mapping_scope_combo.isEnabled())
        self.assertFalse(dialog.video_quality_combo.isEnabled())
        self.assertFalse(dialog.jpeg_quality_spin.isEnabled())
        self.assertTrue(dialog.phone_conflict_combo.isEnabled())
        self.assertTrue(dialog.phone_video_limit_checkbox.isEnabled())
        self.assertTrue(dialog.restore_last_job_checkbox.isEnabled())
        self.assertTrue(dialog.autosave_job_checkbox.isEnabled())
        dialog._restore_defaults()
        updated = dialog.to_settings(settings)
        self.assertEqual(updated.mobile_output_jpeg_quality, 37)
        self.assertEqual(updated.model_name_mappings, settings.model_name_mappings)
        self.assertEqual(updated.phone_conflict_policy, 'overwrite')

    def test_new_job_unlocks_completed_processing_inputs(self):
        self._prepare_real_preview()
        self.window._handle_execute()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.window._new_job()
        self.assertTrue(self.window.source_edit.isEnabled())
        self.assertTrue(self.window.target_edit.isEnabled())
        self.assertFalse(SettingsDialog(self.window, self.window._current_settings())._processing_locked)

