import io
from pathlib import Path
import sys
from threading import Event, RLock
from types import SimpleNamespace
import unittest
import copy
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.operation_control import OperationControl, OperationInterrupted, current_control
from photo_organizer import resume_engine
from photo_organizer.execution_journal import ExecutionJournal, CANCELED_PENDING_MESSAGE
from photo_organizer.job_store import JobState
from photo_organizer.job_validation import capture_file_states
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem
from photo_organizer.resume_models import ensure_plan


class OperationInterruptTests(unittest.TestCase):
    def test_cancellation_cannot_reset_publication_intent(self):
        previous = {'state': 'IN_PROGRESS', 'attempt_id': 'same',
                    'fingerprint': {'exists': True, 'is_file': True, 'size': 4, 'mtime_ns': 5},
                    'message': '최종 파일 게시 시작', 'temp_path': 'staging'}
        canceled = {'state': 'PENDING', 'attempt_id': 'same', 'fingerprint': {},
                    'message': CANCELED_PENDING_MESSAGE, 'temp_path': ''}
        with self.assertRaises(ValueError):
            ExecutionJournal._transition(previous, canceled)

    def setup_stage(self, directory):
        base = Path(directory)
        source = base / 'source' / '20240101_120000_X.jpg'
        source.parent.mkdir()
        source.write_bytes(b'original bytes')
        folder = base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
        name = '20240101_120000_X_0001.jpg'
        item = PreviewItem('one', 'photo', str(source), str(folder), str(folder / name), name, 'NEW', '2024-01-01T12:00:00', 'filename', 'X', 'filename', [])
        settings = AppSettings(source_path=str(source.parent), target_path=str(base / 'target'), mobile_output_enabled=False)
        job = JobState(phase='PREVIEW_READY', settings=settings, preview_bundle=PreviewBundle(preview_items=[item]), source_fingerprints=capture_file_states([source]))
        ensure_plan(job)
        journal = ExecutionJournal(base)
        journal.register(job)
        return job, item, resume_engine._JournalCoordinator(journal)

    def test_generation_cancellation_survives_fast_resume_and_rebinds_retry(self):
        control = OperationControl()
        with control.file_activity('one', 'one.jpg', 'copy'):
            self.assertIs(current_control(), control)
            control.request_pause()
            control.resume()
            with self.assertRaises(OperationInterrupted):
                control.raise_if_interrupted()
        self.assertIsNone(current_control())
        with control.file_activity('one', 'one.jpg', 'copy'):
            control.raise_if_interrupted()

    def test_large_copy_checks_interruption_between_chunks(self):
        control = OperationControl()
        class Writer(io.BytesIO):
            def write(self, data):
                result = super().write(data)
                control.request_stop()
                return result
        writer = Writer()
        with control.file_activity('one', 'one.jpg', 'copy'):
            with self.assertRaises(OperationInterrupted):
                resume_engine._copy_interruptible(io.BytesIO(b'x' * 3000000), writer)
        self.assertLess(len(writer.getvalue()), 3000000)

    def test_interrupted_resume_item_is_not_completed_and_is_retryable(self):
        control = OperationControl()
        item = SimpleNamespace(item_id='one', source_path='one.jpg')
        job = SimpleNamespace(ledger={'one': {stage: {'state': 'PENDING'} for stage in ('main', 'output', 'source_remove')}})
        journal = SimpleNamespace(lock=RLock(), failure=None)
        actions = [SimpleNamespace(item_id='one', stage='main', allowed=True, action='RUN')]
        def interrupted(*args):
            control.request_pause()
            control.raise_if_interrupted()
        with patch.object(resume_engine, 'build_resume_plan', return_value=actions), patch.object(resume_engine, '_run_stage', side_effect=interrupted):
            self.assertEqual(resume_engine._run_item(None, journal, job, item, None, 'initial', control, Event()), (False, False))
        self.assertEqual(control.activity_snapshot(), ())

    def test_unpublished_partial_copy_cleans_temp_and_restores_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            job, item, journal = self.setup_stage(directory)
            control = OperationControl()
            def partial(reader, writer):
                writer.write(reader.read(4))
                control.request_pause()
                control.raise_if_interrupted()
            with control.file_activity(item.item_id, item.source_path, 'copy'), patch.object(resume_engine, '_copy_interruptible', side_effect=partial):
                with self.assertRaises(OperationInterrupted):
                    resume_engine._run_stage(None, journal, job, item, 'main', None, 'initial')
            self.assertEqual(Path(item.source_path).read_bytes(), b'original bytes')
            self.assertFalse(Path(item.target_path).exists())
            self.assertEqual(job.ledger[item.item_id]['main']['state'], 'PENDING')
            self.assertFalse(list(Path(item.target_directory).glob('.photoorganizer_*')))
            restored = copy.deepcopy(job)
            self.assertTrue(ExecutionJournal(Path(directory)).restore(restored))
            self.assertEqual(restored.ledger, job.ledger)

    def test_request_during_atomic_publish_keeps_done_target(self):
        with tempfile.TemporaryDirectory() as directory:
            job, item, journal = self.setup_stage(directory)
            control = OperationControl()
            original = resume_engine._publish
            def publish(*args):
                control.request_stop()
                return original(*args)
            with control.file_activity(item.item_id, item.source_path, 'copy'), patch.object(resume_engine, '_publish', side_effect=publish):
                self.assertTrue(resume_engine._run_stage(None, journal, job, item, 'main', None, 'initial'))
            self.assertEqual(job.ledger[item.item_id]['main']['state'], 'DONE')
            self.assertEqual(Path(item.target_path).read_bytes(), b'original bytes')
            self.assertTrue(Path(item.source_path).is_file())


if __name__ == '__main__':
    unittest.main()
