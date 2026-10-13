import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

from photo_organizer.engine import OrganizerEngine
from photo_organizer.job_store import load_job
from photo_organizer.job_validation import capture_file_states
from photo_organizer.metadata_writer import ModelMetadataWriter, read_exiftool_model
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import MainWindow
from photo_organizer.ui.original_metadata import OriginalModelDialog


class OriginalMetadataUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.target = self.base / 'target'
        self.paths = []
        for index in range(2):
            path = self.source / f'20240501_12000{index}.jpg'
            exif = Image.Exif()
            exif[306] = f'2024:05:01 12:00:0{index}'
            Image.new('RGB', (16, 12), (25, 50, 75)).save(path, exif=exif)
            self.paths.append(path)
        self.engine = OrganizerEngine(self.base)
        settings = AppSettings(source_path=str(self.source), target_path=str(self.target),
                               mobile_output_enabled=False, restore_last_job=False,
                               autosave_job_changes=False,
                               model_name_mappings={'SM-TEST': 'Family_Phone'})
        config = Mock()
        config.load.return_value = settings
        for name in ('information', 'warning'):
            mocked = patch(f'photo_organizer.ui.original_metadata.QMessageBox.{name}')
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)
        transition = patch.object(MainWindow, '_confirm_job_transition', new=lambda window: True)
        transition.start()
        self.addCleanup(transition.stop)
        self.window = MainWindow(self.engine, config)
        self.addCleanup(self.window.close)
        request = self.window._request_from_inputs(preview_only=True)
        self.window.last_preview_bundle = self.engine.preview(request)
        self.window.last_preview_signature = self.window._request_signature(request)
        self.window.model_selection_panel.set_items(self.window.last_preview_bundle.preview_items,
                                                   self.window.last_preview_bundle.selected_models)
        self.window._fill_preview_table(self.window.last_preview_bundle.preview_items)
        self.window._job_preview_completed()
        self.window.preview_table.selectRow(0)
        self.writer = ModelMetadataWriter(self.base)

    def test_writer_exception_after_publish_invalidates_old_preview(self):
        writer = self.writer
        class PartialFailure:
            def write_model(inner, path, model):
                writer.write_model(path, model)
                raise OSError('journal failed after publishing modified original')
        self.window._apply_original_metadata(PartialFailure(), self.paths[0], 'SM-TEST')
        self.assertEqual(read_exiftool_model(self.paths[0]), 'SM-TEST')
        self.assertIsNone(self.window.last_preview_signature)
        self.assertFalse(self.window._busy)
        self.warning.assert_called_once()

    def test_native_write_replans_alias_preserves_exclusion_manual_name_and_fingerprints(self):
        bundle = self.window.last_preview_bundle
        first = bundle.preview_items[0]
        self.engine.edit_preview_filename(bundle, first.item_id, 'chosen_name.jpg')
        self.engine.set_selected_files(bundle, {first.item_id}, False)
        self.window._fill_preview_table(bundle.preview_items)
        before = dict(self.window._job_state.source_fingerprints[str(self.paths[0])])
        self.window._detail_metadata_cache['stale'] = 'cached'
        self.window._video_thumbnail_cache['stale'] = 'cached'
        self.window._apply_original_metadata(self.writer, self.paths[0], 'SM-TEST')
        after = self.window.last_preview_bundle.preview_items[0]
        self.assertEqual(read_exiftool_model(self.paths[0]), 'SM-TEST')
        self.assertEqual(after.model_name, 'SM-TEST')
        self.assertEqual(after.output_model_name, 'Family_Phone')
        self.assertIn('Family_Phone', after.target_directory)
        self.assertFalse(after.file_selected)
        self.assertFalse(after.included)
        self.assertEqual(after.new_filename, 'chosen_name.jpg')
        fingerprints = capture_file_states([str(self.paths[0])])
        self.assertEqual(self.window._job_state.source_fingerprints[str(self.paths[0])],
                         fingerprints[str(self.paths[0])])
        self.assertNotEqual(before, fingerprints[str(self.paths[0])])
        self.assertNotIn('stale', self.window._detail_metadata_cache)
        self.assertNotIn('stale', self.window._video_thumbnail_cache)
        self.assertFalse(self.target.exists())
        self.information.assert_called_once()
        self.warning.assert_not_called()

    def test_replan_failure_keeps_written_original_and_backup_but_blocks_old_plan(self):
        with patch.object(self.engine, 'refresh_preview_after_metadata', side_effect=ValueError('replan failed')):
            self.window._apply_original_metadata(self.writer, self.paths[0], 'SM-TEST')
        self.assertEqual(read_exiftool_model(self.paths[0]), 'SM-TEST')
        self.assertTrue(Path(self.writer.inspect(self.paths[0])['backup_path']).is_file())
        self.assertIsNone(self.window.last_preview_signature)
        self.assertFalse(self.window._busy)
        self.assertIn('다시 미리보기', self.warning.call_args.args[2])
        self.assertFalse(self.target.exists())

    def test_writer_failure_before_write_keeps_original_bytes(self):
        before = self.paths[0].read_bytes()
        writer = Mock()
        writer.write_model.side_effect = OSError('read-only original')
        self.window._apply_original_metadata(writer, self.paths[0], 'SM-TEST')
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertEqual(self.window.last_preview_bundle.preview_items[0].model_name, 'UNKNOWN')
        self.assertFalse(self.window._busy)
        self.warning.assert_called_once()

    def test_inspection_fingerprint_is_forwarded_for_write_and_restore(self):
        info = self.writer.inspect(self.paths[0])
        dialog = Mock()
        dialog.exec.return_value = QDialog.Accepted
        dialog.model_input.currentText.return_value = 'SM-TEST'
        with patch.object(self.window, '_metadata_inspect', return_value=(self.writer, info)), \
                patch('photo_organizer.ui.original_metadata.OriginalModelDialog', return_value=dialog), \
                patch.object(self.window, '_apply_original_metadata') as apply:
            self.window._open_original_metadata()
        apply.assert_called_once_with(self.writer, self.paths[0], 'SM-TEST',
                                      expected_fingerprint=info['fingerprint'])
        info['backup_path'] = str(self.base / 'original-backup.bak')
        with patch.object(self.window, '_metadata_inspect', return_value=(self.writer, info)), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
                patch.object(self.window, '_apply_original_metadata') as apply:
            self.window._restore_original_metadata()
        apply.assert_called_once_with(self.writer, self.paths[0], restore=True,
                                      expected_fingerprint=info['fingerprint'])

    def test_journal_exception_invalidation_survives_job_save_and_load(self):
        writer = self.writer
        class PartialFailure:
            def write_model(inner, path, model):
                writer.write_model(path, model)
                raise OSError('journal failed after publication')
        self.window._apply_original_metadata(PartialFailure(), self.paths[0], 'SM-TEST')
        self.assertTrue(self.window._job_state.metadata_refresh_required)
        self.window._job_path = self.base / 'invalidated.pojob.json'
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(self.window._job_path), self.warning.call_args)
        self.assertTrue(self.window._job_state.metadata_refresh_required)
        self.assertIsNone(self.window.last_preview_signature)
        self.assertFalse(self.window.execute_button.isEnabled())
        with patch.object(self.window, '_build_request') as build_request, \
                patch.object(self.engine, 'execute') as execute:
            self.window._handle_execute()
        build_request.assert_not_called()
        execute.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_blocked_checkpoint_is_on_disk_before_original_writer_starts(self):
        self.window._job_path = self.base / 'active.pojob.json'
        self.assertTrue(self.window._save_job())
        self.window._write_recent_job()
        checkpoint_paths = [self.window._recent_job_path(), self.window._job_path]
        self.assertTrue(all(not load_job(path).metadata_refresh_required for path in checkpoint_paths))
        observations = []
        write_model = self.writer.write_model
        def observe_checkpoint(path, model):
            observations.extend(load_job(checkpoint).metadata_refresh_required
                                for checkpoint in checkpoint_paths)
            return write_model(path, model)
        with patch.object(self.writer, 'write_model', side_effect=observe_checkpoint):
            self.window._apply_original_metadata(self.writer, self.paths[0], 'SM-TEST')
        self.assertEqual(observations, [True, True])
        self.assertEqual(read_exiftool_model(self.paths[0]), 'SM-TEST')
        for checkpoint in checkpoint_paths:
            restored = load_job(checkpoint)
            self.assertFalse(restored.metadata_refresh_required)
            self.assertEqual(restored.preview_bundle.preview_items[0].model_name, 'SM-TEST')
            self.assertEqual(restored.source_fingerprints[str(self.paths[0])],
                             capture_file_states([str(self.paths[0])])[str(self.paths[0])])

    def test_checkpoint_storage_failure_prevents_original_writer(self):
        self.window._job_path = self.base / 'active.pojob.json'
        self.assertTrue(self.window._save_job())
        # A file occupying the recovery directory causes a real mkdir failure,
        # independent of which helper or save_job import the implementation uses.
        self.window._recent_job_path().parent.write_text('blocked checkpoint', encoding='utf-8')
        original_bytes = self.paths[0].read_bytes()
        writer = Mock()
        self.window._apply_original_metadata(writer, self.paths[0], 'SM-TEST')
        writer.write_model.assert_not_called()
        self.assertEqual(self.paths[0].read_bytes(), original_bytes)
        self.assertFalse(self.window._busy)
        self.warning.assert_called_once()

    def test_busy_and_started_jobs_lock_edits_and_file_checks(self):
        writer = Mock()
        for started, busy in ((False, True), (True, False)):
            self.window._job_state.execution_started = started
            self.window._set_busy(busy)
            self.window._refresh_file_checks()
            self.assertFalse(self.window.metadata_edit_button.isEnabled())
            self.assertFalse(self.window.metadata_restore_button.isEnabled())
            cell = self.window.preview_table.item(0, 9)
            self.assertFalse(cell.flags() & Qt.ItemIsUserCheckable)
            self.window._apply_original_metadata(writer, self.paths[0], 'SM-TEST')
        writer.write_model.assert_not_called()
        self.window._job_state.execution_started = False
        self.window._set_busy(False)

    def test_raw_model_and_output_alias_are_separate_in_dialog(self):
        row = self.window.last_preview_bundle.preview_items[0]
        row.model_name = 'SM-TEST'
        row.model_source = '사진 메타'
        row.output_model_name = 'Family_Phone'
        dialog = OriginalModelDialog(self.window, row,
                                     {'model': 'SM-TEST', 'supported': True}, ['SM-TEST'])
        labels = {label.text() for label in dialog.findChildren(QLabel)}
        self.assertIn('SM-TEST', labels)
        self.assertIn('Family_Phone', labels)
        self.assertIn('출력 별칭', labels)
        self.assertEqual(dialog.model_input.currentText(), 'SM-TEST')
        dialog.close()

    def test_actual_worker_keeps_ui_locked_during_native_write(self):
        observations = []
        main_thread = threading.get_ident()
        write_model = self.writer.write_model
        def write_in_worker(path, model):
            observations.append(('worker', threading.get_ident()))
            return write_model(path, model)
        def observe_ui():
            observations.append(('busy', self.window._busy))
            observations.append(('edit_enabled', self.window.metadata_edit_button.isEnabled()))
        QTimer.singleShot(0, observe_ui)
        with patch.object(self.writer, 'write_model', side_effect=write_in_worker):
            self.window._apply_original_metadata(self.writer, self.paths[0], 'SM-TEST')
        self.assertIn(('busy', True), observations)
        self.assertIn(('edit_enabled', False), observations)
        worker_thread = next(value for key, value in observations if key == 'worker')
        self.assertNotEqual(worker_thread, main_thread)
        self.assertIsNone(self.window._original_metadata_worker)
        self.assertFalse(self.window._busy)


if __name__ == '__main__':
    unittest.main()
