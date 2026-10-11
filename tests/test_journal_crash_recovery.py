"""SQLite recovery only: no organizer execution or media mutations."""
import copy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.execution_journal import ExecutionJournal
from photo_organizer.job_store import JobState
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem
from photo_organizer.resume_models import ensure_plan


class JournalCrashRecoveryTests(unittest.TestCase):
    def test_restore_recovers_hot_rollback_journal_and_committed_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source' / '20240101_120000_X.jpg'
            folder = base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
            name = '20240101_120000_X_0001.jpg'
            row = PreviewItem('one', 'photo', str(source), str(folder), str(folder / name), name, 'NEW', '2024-01-01T12:00:00', 'filename', 'X', 'filename', [])
            job = JobState(phase='PREVIEW_READY', settings=AppSettings(source_path=str(source.parent), target_path=str(base / 'target')), preview_bundle=PreviewBundle(preview_items=[row]))
            ensure_plan(job)
            older = copy.deepcopy(job)
            journal = ExecutionJournal(base)
            journal.register(job)
            attempt = str(uuid4())
            journal.update(job, 'one', 'main', {'state': 'IN_PROGRESS', 'attempt_id': attempt})
            journal.update(job, 'one', 'main', {'state': 'DONE', 'attempt_id': attempt, 'fingerprint': {'exists': True, 'is_file': True, 'size': 3, 'mtime_ns': 4}})
            connection = sqlite3.connect(journal.db_path)
            try:
                connection.execute('CREATE TABLE crash_padding(payload BLOB)')
                connection.execute('INSERT INTO crash_padding VALUES(zeroblob(5000000))')
                connection.commit()
            finally:
                connection.close()
            script = '''import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute('PRAGMA journal_mode=DELETE')
connection.execute('PRAGMA synchronous=FULL')
connection.execute('PRAGMA cache_size=1')
connection.execute('BEGIN IMMEDIATE')
connection.execute("UPDATE plans SET manifest='uncommitted'")
connection.execute('UPDATE crash_padding SET payload=randomblob(5000000)')
print('dirty pages spilled', flush=True)
sys.stdin.read()
'''
            process = subprocess.Popen([sys.executable, '-c', script, str(journal.db_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'dirty pages spilled')
            finally:
                process.kill()
                process.communicate(timeout=10)
            rollback = Path(str(journal.db_path) + '-journal')
            self.assertTrue(rollback.is_file())
            self.assertNotEqual(rollback.read_bytes()[:8], b'\0' * 8)
            self.assertTrue(ExecutionJournal(base).restore(older))
            self.assertEqual(older.checkpoint, 2)
            self.assertEqual(older.plan_signature, job.plan_signature)
            self.assertEqual(older.ledger['one']['main']['state'], 'DONE')
            self.assertFalse(rollback.exists())
            self.assertFalse(source.exists())
            self.assertFalse((folder / name).exists())

    def test_recovery_connection_never_creates_missing_database_or_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'missing-app-directory'
            journal = ExecutionJournal(base)
            with self.assertRaises(ValueError):
                journal._connect(write=False)
            self.assertFalse(base.exists())
