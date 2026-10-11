import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from photo_organizer.models import AppSettings
from photo_organizer.engine import OrganizerEngine
from photo_organizer.ui.main_window import MainWindow


class ResumeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        confirmation = patch('photo_organizer.ui.execution_controller.ExecutionConfirmDialog.exec', return_value=1)
        confirmation.start()
        self.addCleanup(confirmation.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.target = self.base / 'source', self.base / 'target'
        self.source.mkdir()
        self.target.mkdir()
        self.file = self.source / '20240101_120000_SM-A.jpg'
        self.file.write_bytes(b'filename fallback')
        config = Mock()
        config.load.return_value = AppSettings(source_path=str(self.source), target_path=str(self.target),
                                               restore_last_job=False, mobile_output_enabled=False, photo_workers=1)
        self.window = MainWindow(OrganizerEngine(self.base), config)
        warning = patch.object(QMessageBox, 'warning', return_value=None)
        warning.start()
        self.addCleanup(warning.stop)
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window._job_dirty = False
        self.window.close()
        # The test QApplication keeps running after a window closes. Input
        # persistence in closeEvent can mark it dirty again; do not let a queued
        # worker-finished callback restart autosave in a later test's event loop.
        self.window._job_dirty = False

    def test_resume_buttons_disabled_before_execution_and_after_success(self):
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertFalse(self.window.retry_button.isEnabled())
        self.window._handle_preview()
        self.window._handle_execute()
        self.assertTrue(self.window._job_state.execution_id)
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertFalse(self.window.retry_button.isEnabled())

    def test_save_as_keeps_execution_and_plan_identity(self):
        self.window._handle_preview()
        self.window._handle_execute()
        job = self.window._job_state
        job_id, plan_id, execution_id = job.job_id, job.plan_id, job.execution_id
        with patch('photo_organizer.ui.job_controller.QFileDialog.getSaveFileName', return_value=(str(self.base / 'copy.pojob.json'), '')):
            self.assertTrue(self.window._save_job(save_as=True))
        self.assertNotEqual(job_id, self.window._job_state.job_id)
        self.assertEqual(plan_id, self.window._job_state.plan_id)
        self.assertEqual(execution_id, self.window._job_state.execution_id)

    def test_old_ready_copy_restores_latest_started_journal_and_blocks_reexecute(self):
        self.window._handle_preview()
        path = self.base / 'ready.pojob.json'
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        self.window._handle_execute()
        self.assertTrue(self.window._open_job_path(path))
        self.assertTrue(self.window._job_state.execution_started)
        self.assertFalse(self.window.execute_button.isEnabled())
        self.assertEqual(len(self.window.last_execution_bundle.execution_results), 1)
        self.assertTrue(self.window._job_dirty)

    def test_journal_missing_started_file_is_view_only(self):
        self.window._handle_preview()
        self.window._handle_execute()
        path = self.base / 'finished.pojob.json'
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        other = self.base / 'different_app_folder'
        other.mkdir()
        self.window.engine = OrganizerEngine(other)
        self.assertTrue(self.window._open_job_path(path))
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertFalse(self.window.retry_button.isEnabled())
        self.assertIn('조회 전용', self.window.job_status_label.text())

    def test_plan_dialog_lists_readonly_actions_and_requires_confirmation(self):
        from photo_organizer.resume_validation import ResumeAction
        from photo_organizer.ui.resume_dialog import ResumePlanDialog
        actions = [ResumeAction('one', 'main', 'KEEP', '완료', False),
                   ResumeAction('two', 'output', 'RUN', '출력만 재시도', True),
                   ResumeAction('three', 'main', 'BLOCK', '확인 필요', False)]
        dialog = ResumePlanDialog(self.window, actions, mode='retry')
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertIn('1', dialog.summary_label.text())
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        blocked = ResumePlanDialog(self.window, actions[:1], mode='continue')
        self.assertFalse(blocked.run_button.isEnabled())

    def test_failed_output_save_open_retry_keeps_main_and_finishes_move(self):
        self.window.settings.mobile_output_enabled = True
        self.window.mode_combo.setCurrentText('move')
        self.window._handle_preview()
        with patch.object(self.window.engine, '_create_mobile_output', side_effect=OSError('converter failed')):
            self.window._handle_execute()
        preview = self.window.last_preview_bundle.preview_items[0]
        target = Path(preview.target_path)
        original = (target.read_bytes(), target.stat().st_mtime_ns)
        self.assertTrue(self.file.exists())
        self.assertTrue(self.window.retry_button.isEnabled())
        self.window._job_path = self.base / 'failed.pojob.json'
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(self.window._job_path))
        baseline = dict(self.window._job_state.result_fingerprints[preview.target_path])
        def successful_output(source, destination, media_type, request):
            self.assertEqual(Path(source), target)
            Path(destination).write_bytes(b'mobile')
            return 'SUCCESS'
        with patch('photo_organizer.ui.resume_dialog.ResumePlanDialog.exec', return_value=QDialog.Accepted), patch.object(self.window.engine, '_create_mobile_output', side_effect=successful_output):
            self.window._handle_resume('retry')
        self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), original)
        self.assertFalse(self.file.exists())
        self.assertTrue(Path(preview.mobile_output_path).exists())
        self.assertEqual(self.window._job_state.result_fingerprints[preview.target_path], baseline)
        self.assertEqual(len(self.window.last_execution_bundle.execution_results), 1)
        self.assertEqual(self.window.last_execution_bundle.execution_results[0].status, 'SUCCESS')
        self.assertFalse(self.window.retry_button.isEnabled())

    def test_recovery_confirmation_cancel_never_runs_engine(self):
        self.window.settings.mobile_output_enabled = True
        self.window._handle_preview()
        with patch.object(self.window.engine, '_create_mobile_output', side_effect=OSError('failed')):
            self.window._handle_execute()
        with patch('photo_organizer.ui.resume_dialog.ResumePlanDialog.exec', return_value=QDialog.Rejected), patch.object(self.window.engine, 'resume') as resume:
            self.window._handle_resume('retry')
        resume.assert_not_called()

    def test_started_transfer_settings_change_keeps_plan_and_saves(self):
        self.window._handle_preview()
        self.window._handle_execute()
        plan = self.window._job_state.plan_id
        self.window.settings.phone_conflict_policy = 'skip'
        self.window.settings.phone_video_limit_enabled = True
        self.window.settings.phone_video_limit_mb = 100
        self.window._job_path = self.base / 'changed-transfer.pojob.json'
        self.assertTrue(self.window._save_job())
        self.assertEqual(self.window._job_state.plan_id, plan)

    def test_continue_processes_pending_tail_and_keeps_failed_item(self):
        (self.source / '20240101_120001_SM-A.jpg').write_bytes(b'second fallback')
        self.window.settings.mobile_output_enabled = True
        self.window._handle_preview()
        with patch.object(self.window.engine, '_create_mobile_output', side_effect=OSError('first output failed')):
            self.window._handle_execute()
        first = self.window.last_preview_bundle.preview_items[0]
        baseline = Path(first.target_path).read_bytes()
        self.assertTrue(self.window.resume_button.isEnabled())
        def output(source, destination, media_type, request):
            self.assertNotEqual(Path(source), Path(first.target_path))
            Path(destination).write_bytes(b'second mobile')
            return 'SUCCESS'
        with patch('photo_organizer.ui.resume_dialog.ResumePlanDialog.exec', return_value=QDialog.Accepted), patch.object(self.window.engine, '_create_mobile_output', side_effect=output):
            self.window._handle_resume('continue')
        self.assertEqual(Path(first.target_path).read_bytes(), baseline)
        self.assertEqual([result.status for result in self.window.last_execution_bundle.execution_results], ['ERROR', 'SUCCESS'])
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertTrue(self.window.retry_button.isEnabled())

    def test_in_progress_stage_is_confirmation_only_not_resume_or_retry(self):
        from photo_organizer.execution_journal import ExecutionJournal
        from photo_organizer.resume_models import stage_record
        self.window._handle_preview()
        self.assertTrue(self.window._job_execution_checkpoint())
        item = self.window.last_preview_bundle.preview_items[0]
        ExecutionJournal(self.base).update(self.window._job_state, item.item_id, 'main', stage_record('IN_PROGRESS'))
        path = self.base / 'in-progress.pojob.json'
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        self.assertTrue(self.window._open_job_path(path))
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertFalse(self.window.retry_button.isEnabled())
        self.assertIn('확인 필요', self.window.job_status_label.text())

    def test_schema1_completed_job_stays_view_only_even_with_local_journal(self):
        self.window._handle_preview()
        self.window._handle_execute()
        path = self.base / 'legacy.pojob.json'
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        data = json.loads(path.read_text(encoding='utf-8'))
        data['schema_version'] = 1
        for key in ('plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'):
            del data[key]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertTrue(self.window._open_job_path(path))
        self.assertTrue(self.window._job_state.legacy_unverified)
        self.assertFalse(self.window.resume_button.isEnabled())
        self.assertFalse(self.window.retry_button.isEnabled())
        self.assertEqual(len(self.window.last_execution_bundle.execution_results), 1)

    def test_corrupt_journal_open_preserves_current_job(self):
        self.window._handle_preview()
        self.window._handle_execute()
        path = self.base / 'finished.pojob.json'
        self.window._job_path = path
        self.assertTrue(self.window._save_job())
        original = self.window._job_state
        (self.base / 'sessions' / 'execution_journal.sqlite').write_bytes(b'corrupt')
        self.assertFalse(self.window._open_job_path(path))
        self.assertIs(self.window._job_state, original)

    def test_ui_recent_json_is_not_rewritten_per_stage(self):
        from photo_organizer.job_store import save_job
        for second in range(1, 5):
            (self.source / f'20240101_12000{second}_SM-A.jpg').write_bytes(b'additional fallback')
        self.window._handle_preview()
        plan_id = self.window._job_state.plan_id
        writes = []
        def record_write(job, path):
            if job.plan_id == plan_id:
                writes.append((job.checkpoint, self.window._operation_active))
            return save_job(job, path)
        with patch('photo_organizer.ui.job_controller.save_job', side_effect=record_write):
            self.window._handle_execute()
        final_checkpoint = self.window._job_state.checkpoint
        self.assertGreater(final_checkpoint, 1)
        self.assertGreaterEqual(len(writes), 2)
        self.assertIn((0, False), writes)
        self.assertIn((final_checkpoint, False), writes)
        # Idle debounce writes before/after execution are allowed. UI writes must
        # never occur while the worker is executing or capture an intermediate
        # checkpoint. Other windows' delayed callbacks are outside this plan.
        self.assertTrue(all(not active and checkpoint in {0, final_checkpoint}
                            for checkpoint, active in writes), writes)

    def test_registered_checkpoint_json_failure_locks_processing_and_prevents_execution(self):
        self.window._handle_preview()
        self.window._job_path = self.base / 'ready.pojob.json'
        self.assertTrue(self.window._save_job())
        with patch('photo_organizer.ui.job_controller.save_job', side_effect=OSError('cache full')), patch.object(self.window.engine, 'execute') as execute:
            self.window._handle_execute()
        execute.assert_not_called()
        self.assertTrue(self.window._job_state.execution_started)
        self.assertTrue(self.window._job_dirty)
        self.assertTrue(self.file.exists())
        self.assertFalse(Path(self.window.last_preview_bundle.preview_items[0].target_path).exists())
        self.assertFalse(self.window._busy)
        for widget in (self.window.source_edit, self.window.target_edit, self.window.device_name_edit,
                       self.window.mode_combo, self.window.source_select_button, self.window.target_select_button):
            self.assertFalse(widget.isEnabled())
        self.assertFalse(self.window.execute_button.isEnabled())
        with patch.object(QMessageBox, 'information'), patch.object(self.window.engine, 'execute') as execute:
            self.window._handle_execute()
        execute.assert_not_called()
