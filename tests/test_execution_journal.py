import copy
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.job_store import JobState
from photo_organizer.execution_journal import ExecutionJournal
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem
from photo_organizer.resume_models import ensure_plan


class ExecutionJournalTests(unittest.TestCase):
    def update(self, journal, job, item_id, stage, record):
        record = dict(record)
        if 'attempt_id' not in record:
            previous = job.ledger[item_id][stage]
            record['attempt_id'] = previous['attempt_id'] if previous['state'] == 'IN_PROGRESS' else str(uuid4())
        journal.update(job, item_id, stage, record)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def job(self):
        source = self.base / 'source' / '20240101_120000_X.jpg'
        directory = self.base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
        name = '20240101_120000_X_0001.jpg'
        row = PreviewItem('one', 'photo', str(source), str(directory), str(directory / name), name, 'NEW', '2024-01-01T12:00:00', 'filename', 'X', 'filename', [])
        job = JobState(phase='PREVIEW_READY', settings=AppSettings(source_path=str(source.parent), target_path=str(self.base / 'target')), preview_bundle=PreviewBundle(preview_items=[row]))
        ensure_plan(job)
        return job

    def test_ctor_restore_missing_no_files_created(self):
        journal = ExecutionJournal(self.base / 'missing')
        self.assertFalse(journal.restore(self.job()))
        self.assertFalse((self.base / 'missing').exists())

    def test_register_update_and_older_snapshot_restore(self):
        job = self.job()
        older = copy.deepcopy(job)
        journal = ExecutionJournal(self.base)
        journal.register(job)
        attempt = str(uuid4())
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS', 'attempt_id': attempt})
        self.assertEqual(job.checkpoint, 1)
        self.update(journal, job, 'one', 'main', {'state': 'DONE', 'attempt_id': attempt, 'fingerprint': {'exists': True, 'is_file': True, 'size': 3, 'mtime_ns': 4}})
        self.assertTrue(journal.restore(older))
        self.assertEqual(older.execution_id, job.execution_id)
        self.assertEqual(older.ledger, job.ledger)
        self.assertEqual(older.checkpoint, 2)
        self.assertTrue(older.execution_started)

    def test_prefix_conflict_and_json_ahead_rejected(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        branched = copy.deepcopy(job)
        branched.ledger['one']['main']['message'] = 'different'
        with self.assertRaises(ValueError):
            journal.restore(branched)
        ahead = copy.deepcopy(job)
        ahead.checkpoint += 1
        with self.assertRaises(ValueError):
            journal.restore(ahead)

    def test_manifest_mismatch_and_duplicate_registration_blocked(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        duplicate = copy.deepcopy(job)
        duplicate.execution_id = ''
        duplicate.execution_started = False
        with self.assertRaises(ValueError):
            journal.register(duplicate)
        changed = copy.deepcopy(job)
        changed.settings.mobile_output_jpeg_quality = 90
        with self.assertRaises(ValueError):
            journal.restore(changed)

    def test_corrupt_db_not_replaced(self):
        journal = ExecutionJournal(self.base)
        journal.db_path.parent.mkdir()
        journal.db_path.write_bytes(b'corrupt')
        with self.assertRaises((ValueError, OSError)):
            journal.restore(self.job())
        self.assertEqual(journal.db_path.read_bytes(), b'corrupt')

    def test_registration_prepared_checkpoint_is_idempotent(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        identity = job.execution_id
        journal.register(job)
        self.assertEqual(job.execution_id, identity)
        self.assertEqual(job.checkpoint, 0)

    def test_missing_history_rejected_and_existing_snapshot_unchanged(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.update(journal, job, 'one', 'main', {'state': 'FAILED', 'message': 'safe failure'})
        before = copy.deepcopy(job)
        with closing(sqlite3.connect(journal.db_path)) as connection:
            connection.execute('DELETE FROM events WHERE seq=1')
            connection.commit()
        with self.assertRaises(ValueError):
            journal.restore(job)
        self.assertEqual(job, before)

    def test_update_write_failure_does_not_mutate_job(self):
        from unittest.mock import patch
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        before = copy.deepcopy(job)
        connection = journal._connect(write=True)
        class FailingConnection:
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, sql, *args):
                if sql == 'COMMIT':
                    raise sqlite3.OperationalError('disk full')
                return connection.execute(sql, *args)
        with patch.object(journal, '_connect', return_value=FailingConnection()), self.assertRaises(ValueError):
            self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.assertEqual(job, before)
        with closing(sqlite3.connect(journal.db_path)) as verify:
            self.assertEqual(verify.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_per_stage_event_contains_only_record_not_entire_job(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS', 'attempt_id': str(uuid4())})
        with closing(sqlite3.connect(journal.db_path)) as connection:
            record = connection.execute('SELECT record FROM events').fetchone()[0]
            self.assertNotIn('preview_items', record)
            self.assertNotIn('settings', record)
            self.assertLess(len(record), 300)

    def test_done_stage_cannot_be_reverted_by_forged_history(self):
        import json
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.update(journal, job, 'one', 'main', {'state': 'DONE', 'fingerprint': {'exists': True, 'is_file': True, 'size': 3, 'mtime_ns': 4}})
        with closing(sqlite3.connect(journal.db_path)) as connection:
            connection.execute('INSERT INTO events VALUES (?,?,?,?,?)', (job.plan_id, 3, 'one', 'main', json.dumps({'state': 'PENDING', 'attempt_id': '', 'fingerprint': {}, 'message': '', 'temp_path': ''})))
            connection.commit()
        with self.assertRaises(ValueError):
            journal.restore(job)

    def test_update_validates_one_item_and_does_not_rebuild_full_manifest(self):
        from unittest.mock import patch
        from photo_organizer.resume_models import validate_ledger as real_validate
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        with patch('photo_organizer.resume_models.plan_manifest', side_effect=AssertionError('full manifest rebuilt')), patch('photo_organizer.resume_models.validate_ledger', wraps=real_validate) as validate:
            self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.assertEqual(len(validate.call_args.args[0].ledger), 1)
        self.assertEqual(len(validate.call_args.args[0].preview_bundle.preview_items), 1)

    def test_snapshot_same_checkpoint_tampering_update_rejected(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        job.ledger['one']['main']['message'] = 'tampered'
        with self.assertRaises(ValueError):
            self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.assertEqual(job.checkpoint, 0)

    def test_in_progress_cannot_reset_pending_or_change_attempt(self):
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        attempt = str(uuid4())
        self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS', 'attempt_id': attempt})
        for record in ({'state': 'PENDING'}, {'state': 'IN_PROGRESS', 'attempt_id': str(uuid4())}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.update(journal, job, 'one', 'main', record)
        self.assertEqual(job.checkpoint, 1)

    def test_update_rejects_tampered_sibling_stage(self):
        from photo_organizer.resume_models import stage_record
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        self.update(journal, job, 'one', 'main', stage_record('IN_PROGRESS'))
        job.ledger['one']['output']['message'] = 'forged sibling'
        # A retryable failed stage is permitted structurally but must match DB too.
        with self.assertRaises(ValueError):
            self.update(journal, job, 'one', 'main', stage_record('IN_PROGRESS', attempt_id=job.ledger['one']['main']['attempt_id']))

    def test_rollback_failure_does_not_mask_original_write_error(self):
        from unittest.mock import patch
        job = self.job()
        journal = ExecutionJournal(self.base)
        journal.register(job)
        connection = journal._connect(write=True)
        class FailingConnection:
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, sql, *args):
                if sql == 'COMMIT':
                    raise sqlite3.OperationalError('original commit failure')
                if sql == 'ROLLBACK':
                    raise sqlite3.OperationalError('secondary rollback failure')
                return connection.execute(sql, *args)
        with patch.object(journal, '_connect', return_value=FailingConnection()):
            with self.assertRaises(ValueError) as caught:
                self.update(journal, job, 'one', 'main', {'state': 'IN_PROGRESS'})
        self.assertIn('original commit failure', str(caught.exception.__cause__))
        self.assertEqual(job.checkpoint, 0)


if __name__ == '__main__':
    unittest.main()
