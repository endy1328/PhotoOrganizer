import sys
import tempfile
import unittest
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.models import AppSettings, MediaItem, OrganizeRequest
from photo_organizer.engine import OrganizerEngine
from photo_organizer.job_store import JobState
from photo_organizer.job_validation import capture_file_states
from photo_organizer.resume_models import ensure_plan, initial_ledger, stage_record, bundle_from_ledger, validate_ledger
from photo_organizer.resume_validation import build_resume_plan


def make_job(root, mobile=True, operation='copy'):
    root = Path(root)
    source = root / 'source'
    source.mkdir(exist_ok=True)
    original = source / '20240101_120000_CAM.jpg'
    original.write_bytes(b'original media')
    target = root / 'target'
    settings = AppSettings(source_path=str(source), target_path=str(target), operation_mode=operation,
                           mobile_output_enabled=mobile)
    engine = OrganizerEngine(root)
    with patch.object(engine.extractor, 'extract', return_value=MediaItem(original, 'photo', '.jpg', datetime(2024, 1, 1, 12), '사진 메타', 'CAM', '사진 메타')):
        preview = engine.preview(OrganizeRequest(source, target, operation_mode=operation, mobile_output_enabled=mobile))
    job = JobState(settings=settings, phase='PREVIEW_READY', preview_bundle=preview,
                   source_fingerprints=capture_file_states([original]))
    ensure_plan(job)
    job.ledger = initial_ledger(job)
    return job, engine, preview.preview_items[0]


def finish_main(job, item):
    path = Path(item.target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.source_path, path)
    job.ledger[item.item_id]['main'] = stage_record('DONE', fingerprint=capture_file_states([path])[str(path)])


class ResumeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job, self.engine, self.item = make_job(self.temp.name)

    def actions(self, mode='continue'):
        return {a.stage: a for a in build_resume_plan(self.job, mode)}

    def test_initial_main_runs_without_creating_directories(self):
        actions = self.actions()
        self.assertTrue(actions['main'].allowed)
        self.assertFalse(actions['output'].allowed)
        self.assertFalse(Path(self.item.target_path).exists())

    def test_pending_output_waits_for_main_and_failed_main_blocks_it(self):
        self.assertEqual(self.actions()['output'].action, 'WAIT')
        self.job.ledger[self.item.item_id]['main'] = stage_record('FAILED')
        self.assertEqual(self.actions()['output'].action, 'BLOCK')
        self.assertEqual(self.actions('retry')['output'].action, 'WAIT')

    def test_active_record_requires_attempt_and_complete_file_baseline(self):
        finish_main(self.job, self.item)
        record = self.job.ledger[self.item.item_id]['main']
        record['attempt_id'] = ''
        with self.assertRaises(ValueError):
            validate_ledger(self.job)
        record['attempt_id'] = stage_record('DONE')['attempt_id']
        record['fingerprint']['mtime_ns'] = None
        with self.assertRaises(ValueError):
            validate_ledger(self.job)

    def test_ledger_without_preview_is_rejected_cleanly(self):
        self.job.preview_bundle = None
        with self.assertRaises(ValueError):
            validate_ledger(self.job)

    def test_completed_main_kept_and_only_failed_output_retried(self):
        finish_main(self.job, self.item)
        self.job.ledger[self.item.item_id]['output'] = stage_record('FAILED', message='ffmpeg missing')
        actions = self.actions('retry')
        self.assertEqual(actions['main'].action, 'KEEP')
        self.assertTrue(actions['output'].allowed)
        self.assertEqual(actions['output'].action, 'RUN')

    def test_changed_success_target_blocks_output_without_recreating_it(self):
        finish_main(self.job, self.item)
        Path(self.item.target_path).write_bytes(b'changed')
        actions = self.actions()
        self.assertEqual(actions['main'].action, 'BLOCK')
        self.assertFalse(actions['output'].allowed)

    def test_in_progress_is_uncertain_even_when_final_exists(self):
        finish_main(self.job, self.item)
        self.job.ledger[self.item.item_id]['main'] = stage_record('IN_PROGRESS')
        self.assertEqual(self.actions()['main'].action, 'BLOCK')

    def test_existing_destination_and_source_change_block(self):
        Path(self.item.source_path).write_bytes(b'changed source')
        self.assertFalse(self.actions()['main'].allowed)
        finish_main(self.job, self.item)
        self.job.ledger[self.item.item_id]['main'] = stage_record('PENDING')
        self.assertFalse(self.actions()['main'].allowed)

    def test_skipped_output_is_terminal_and_not_retryable(self):
        finish_main(self.job, self.item)
        self.job.ledger[self.item.item_id]['output'] = stage_record('SIZE_EXCLUDED')
        self.assertEqual(self.actions('retry')['output'].action, 'KEEP')

    def test_move_removal_requires_output_completion_and_unchanged_source(self):
        self.job.settings.operation_mode = 'move'
        self.job.ledger[self.item.item_id]['source_remove'] = stage_record('PENDING')
        finish_main(self.job, self.item)
        self.assertFalse(self.actions()['source_remove'].allowed)
        self.job.ledger[self.item.item_id]['output'] = stage_record('SKIPPED')
        self.assertTrue(self.actions()['source_remove'].allowed)
        # Different size makes the change deterministic even when Windows
        # gives consecutive writes the same filesystem timestamp.
        Path(self.item.source_path).write_bytes(b'changed source content')
        self.assertFalse(self.actions()['source_remove'].allowed)

    def test_schema1_started_records_are_not_retry_evidence(self):
        self.job.legacy_unverified = True
        self.assertTrue(all(not a.allowed for a in build_resume_plan(self.job, 'retry')))

    def test_plan_id_preserves_phone_preferences_and_changes_with_manual_name(self):
        before = self.job.plan_id
        self.job.settings.phone_conflict_policy = 'skip'
        ensure_plan(self.job)
        self.assertEqual(self.job.plan_id, before)
        self.item.new_filename = 'manual.jpg'
        self.item.target_path = str(Path(self.item.target_directory) / 'manual.jpg')
        self.item.mobile_output_path = str(Path(self.item.mobile_output_path).parent / 'manual.jpg')
        ensure_plan(self.job)
        self.assertNotEqual(self.job.plan_id, before)

    def test_legacy_plan_identity_stable_independent_of_document_id(self):
        self.job.plan_id = self.job.plan_signature = ''
        ensure_plan(self.job, legacy=True)
        before = self.job.plan_id
        self.job.plan_id = self.job.plan_signature = ''
        self.job.job_id = '8cdd9a3b-5808-4085-9691-906e07ba841f'
        ensure_plan(self.job, legacy=True)
        self.assertEqual(self.job.plan_id, before)

    def test_bundle_keeps_fixed_done_fingerprints_and_copy_delete_unchecked(self):
        finish_main(self.job, self.item)
        self.job.ledger[self.item.item_id]['output'] = stage_record('SKIPPED')
        baseline = dict(self.job.ledger[self.item.item_id]['main']['fingerprint'])
        self.job.execution_started = True
        bundle = bundle_from_ledger(self.job)
        self.assertEqual(bundle.execution_results[0].status, 'SUCCESS')
        self.assertFalse(bundle.delete_review_items[0].selected)
        self.assertEqual(self.job.result_fingerprints[self.item.target_path], baseline)


if __name__ == '__main__':
    unittest.main()
