import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ResumeEngineTests(unittest.TestCase):
    def setUp(self):
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import AppSettings, OrganizeRequest
        from photo_organizer.job_store import JobState
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='resume_engine_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        source = self.base / 'source'
        source.mkdir()
        self.source = source / '20240101_120000_CAM.jpg'
        self.source.write_bytes(b'original-media')
        self.engine = OrganizerEngine(self.base)
        self.request = OrganizeRequest(source, self.base / 'target', mobile_output_enabled=False, photo_workers=1)
        self.job = JobState(settings=AppSettings(source_path=str(source), target_path=str(self.base / 'target'), mobile_output_enabled=False, photo_workers=1),
                            phase='PREVIEW_READY', preview_bundle=self.engine.preview(self.request))
        from photo_organizer.job_validation import capture_file_states
        self.job.source_fingerprints = capture_file_states([self.source])
        self.item = self.job.preview_bundle.preview_items[0]
        self.target = Path(self.item.target_path)

    def enable_output(self, move=False):
        self.job.settings.mobile_output_enabled = True
        self.job.settings.operation_mode = 'move' if move else 'copy'
        self.item.mobile_output_enabled = True
        self.item.mobile_output_path = str(self.engine._build_mobile_output_path(Path(self.item.target_directory), self.item.new_filename))
        self.output = Path(self.item.mobile_output_path)

    @staticmethod
    def output_success(source_path, target_path, media_type, request):
        target_path.write_bytes(b'converted-media')
        return 'SUCCESS'

    def test_initial_copy_is_journalled_and_completed(self):
        result = self.engine.resume(self.job, 'initial')
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        self.assertEqual(self.target.read_bytes(), b'original-media')
        self.assertTrue(self.source.exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['main']['state'], 'DONE')

    def test_output_failure_keeps_main_and_retry_does_not_copy_again(self):
        self.enable_output()
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('encoder failed')):
            first = self.engine.resume(self.job, 'initial')
        self.assertEqual(first.execution_results[0].status, 'ERROR')
        original_target = self.target.stat().st_mtime_ns
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.output_success):
            retried = self.engine.resume(self.job, 'retry')
        self.assertEqual(retried.execution_results[0].status, 'SUCCESS')
        self.assertEqual(self.target.stat().st_mtime_ns, original_target)
        self.assertTrue(self.output.exists())
        from datetime import datetime
        self.assertEqual(datetime.fromtimestamp(self.output.stat().st_mtime), datetime(2024, 1, 1, 12, 0))

    def test_move_preserves_original_when_output_fails_then_finishes(self):
        self.enable_output(move=True)
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('encoder failed')):
            self.engine.resume(self.job, 'initial')
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.output_success):
            self.engine.resume(self.job, 'retry')
        self.assertFalse(self.source.exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['source_remove']['state'], 'DONE')

    def test_size_excluded_is_terminal_and_move_can_finish(self):
        from photo_organizer.engine import MobileOutputSizeExcluded
        self.enable_output(move=True)
        with patch.object(self.engine, '_create_mobile_output', side_effect=MobileOutputSizeExcluded('too large')):
            self.engine.resume(self.job, 'initial')
        self.assertEqual(self.job.ledger[self.item.item_id]['output']['state'], 'SIZE_EXCLUDED')
        self.assertFalse(self.source.exists())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.parent.exists())

    def test_success_target_changed_is_blocked_without_recopy(self):
        self.engine.resume(self.job, 'initial')
        self.target.write_bytes(b'changed')
        self.engine.resume(self.job, 'continue')
        self.assertEqual(self.target.read_bytes(), b'changed')

    def test_existing_new_destination_is_preserved(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'preexisting')
        self.engine.resume(self.job, 'initial')
        self.assertEqual(self.target.read_bytes(), b'preexisting')

    def test_public_execute_routes_to_job_engine(self):
        result = self.engine.execute(self.request, preview_bundle=self.job.preview_bundle, job_state=self.job)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')

    def test_main_done_commit_failure_stops_before_output(self):
        from photo_organizer.execution_journal import ExecutionJournal
        from photo_organizer.resume_engine import JournalCommitError
        self.enable_output()
        original = ExecutionJournal.update
        def fail_done(journal, job, item_id, stage, record):
            if stage == 'main' and record['state'] == 'DONE':
                raise OSError('DB disk full after publication')
            return original(journal, job, item_id, stage, record)
        with patch.object(ExecutionJournal, 'update', fail_done), patch.object(self.engine, '_create_mobile_output') as convert:
            with self.assertRaises(JournalCommitError):
                self.engine.resume(self.job, 'initial')
        self.assertTrue(self.target.exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['main']['state'], 'UNCERTAIN')
        convert.assert_not_called()
        self.engine.resume(self.job, 'retry')
        self.assertTrue(self.target.exists())

    def test_intent_commit_failure_never_creates_target(self):
        from photo_organizer.execution_journal import ExecutionJournal
        from photo_organizer.resume_engine import JournalCommitError
        with patch.object(ExecutionJournal, 'update', side_effect=OSError('DB unavailable')):
            with self.assertRaises(JournalCommitError):
                self.engine.resume(self.job, 'initial')
        self.assertFalse(self.target.exists())
        self.assertTrue(self.source.exists())

    def test_output_skipped_is_not_retried(self):
        self.enable_output()
        with patch.object(self.engine, '_create_mobile_output', return_value='SKIPPED'):
            self.engine.resume(self.job, 'initial')
        with patch.object(self.engine, '_create_mobile_output') as convert:
            self.engine.resume(self.job, 'retry')
        convert.assert_not_called()
        self.assertEqual(self.job.ledger[self.item.item_id]['output']['state'], 'SKIPPED')

    def test_continue_skips_failed_output_and_processes_pending_tail(self):
        from photo_organizer.models import OrganizeRequest
        from photo_organizer.job_validation import capture_file_states
        self.enable_output()
        second = self.source.parent / '20240101_120100_CAM.jpg'
        second.write_bytes(b'second-media')
        request = OrganizeRequest(self.source.parent, Path(self.job.settings.target_path), mobile_output_enabled=True)
        self.job.preview_bundle = self.engine.preview(request)
        self.job.source_fingerprints = capture_file_states([self.source, second])
        self.item = self.job.preview_bundle.preview_items[0]
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('first encoder failed')):
            self.engine.resume(self.job, 'initial')
        second_item = self.job.preview_bundle.preview_items[1]
        self.assertFalse(Path(second_item.target_path).exists())
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.output_success):
            self.engine.resume(self.job, 'continue')
        self.assertTrue(Path(second_item.target_path).exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['output']['state'], 'FAILED')

    def test_publication_race_preserves_existing_file(self):
        from photo_organizer.resume_engine import _publish
        def collide(staged, target, overwrite=False):
            target.write_bytes(b'external-race')
            return _publish(staged, target, overwrite)
        with patch('photo_organizer.resume_engine._publish', side_effect=collide):
            self.engine.resume(self.job, 'initial')
        self.assertEqual(self.target.read_bytes(), b'external-race')
        self.assertEqual(self.job.ledger[self.item.item_id]['main']['state'], 'UNCERTAIN')

    def test_interrupted_copy_is_not_automatically_retried(self):
        with patch('photo_organizer.resume_engine.shutil.copyfileobj', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.resume(self.job, 'initial')
        self.assertEqual(self.job.ledger[self.item.item_id]['main']['state'], 'IN_PROGRESS')
        with patch('photo_organizer.resume_engine.shutil.copyfileobj') as copy:
            self.engine.resume(self.job, 'continue')
        copy.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_move_removal_done_record_failure_stays_uncertain(self):
        from photo_organizer.execution_journal import ExecutionJournal
        from photo_organizer.resume_engine import JournalCommitError
        self.job.settings.operation_mode = 'move'
        original = ExecutionJournal.update
        def fail_done(journal, job, item_id, stage, record):
            if stage == 'source_remove' and record['state'] == 'DONE':
                raise OSError('DB full after source removal')
            return original(journal, job, item_id, stage, record)
        with patch.object(ExecutionJournal, 'update', fail_done):
            with self.assertRaises(JournalCommitError):
                self.engine.resume(self.job, 'initial')
        self.assertFalse(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['source_remove']['state'], 'UNCERTAIN')
        self.engine.resume(self.job, 'retry')
        self.assertTrue(self.target.exists())

    def test_manual_filename_is_kept_through_failed_output_retry(self):
        self.enable_output()
        self.item = self.engine.edit_preview_filename(self.job.preview_bundle, self.item.item_id, '사용자_파일.jpg')
        self.target = Path(self.item.target_path)
        self.output = Path(self.item.mobile_output_path)
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('failed')):
            self.engine.resume(self.job, 'initial')
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.output_success):
            self.engine.resume(self.job, 'retry')
        self.assertEqual(self.target.name, '사용자_파일.jpg')
        self.assertEqual(self.output.name, '사용자_파일.jpg')
        self.assertTrue(self.target.exists())
        self.assertTrue(self.output.exists())

    def test_retry_records_executing_checkpoint_before_conversion(self):
        from photo_organizer.job_store import load_job
        self.enable_output()
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('first failure')):
            self.engine.resume(self.job, 'initial')
        def inspect_checkpoint(source_path, target_path, media_type, request):
            self.assertEqual(self.job.phase, 'EXECUTING')
            saved = load_job(self.base / 'sessions' / 'last_session.pojob.json')
            self.assertEqual(saved.phase, 'EXECUTING')
            self.assertEqual(saved.ledger[self.item.item_id]['output']['state'], 'FAILED')
            return self.output_success(source_path, target_path, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=inspect_checkpoint):
            result = self.engine.resume(self.job, 'retry')
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')

    def test_retry_checkpoint_failure_does_not_start_conversion(self):
        self.enable_output()
        with patch.object(self.engine, '_create_mobile_output', side_effect=RuntimeError('first failure')):
            self.engine.resume(self.job, 'initial')
        with patch('photo_organizer.job_store.save_job', side_effect=OSError('checkpoint unavailable')), patch.object(self.engine, '_create_mobile_output') as convert:
            with self.assertRaises(OSError):
                self.engine.resume(self.job, 'retry')
        convert.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.job.ledger[self.item.item_id]['output']['state'], 'FAILED')

    def test_initial_conflict_records_error_without_changing_files(self):
        self.item.write_mode = 'CONFLICT'
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'keep-existing')
        result = self.engine.resume(self.job, 'initial')
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, 'ERROR')
        self.assertEqual(self.job.ledger[self.item.item_id]['main']['state'], 'FAILED')
        self.assertEqual(self.target.read_bytes(), b'keep-existing')
        self.assertEqual(self.source.read_bytes(), b'original-media')


if __name__ == '__main__':
    unittest.main()
