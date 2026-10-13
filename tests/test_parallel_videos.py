import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.execution_journal import ExecutionJournal
from photo_organizer.job_store import JobState
from photo_organizer.job_validation import capture_file_states
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem
from photo_organizer.operation_control import OperationControl


class ParallelVideoTests(unittest.TestCase):
    def setUp(self):
        namespace = patch('photo_organizer.execution_lock.MUTEX_NAME', 'Local\\PhotoOrganizerVideoTest_' + str(uuid4()))
        namespace.start()
        self.addCleanup(namespace.stop)
        tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='parallel_videos_')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        source = self.base / 'source'
        source.mkdir()
        folder = self.base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_CAM'
        self.items = []
        self.sources = []
        for i in range(2):
            path = source / f'20240101_12000{i}_CAM.mp4'
            path.write_bytes(b'synthetic video ' + bytes([i]))
            name = f'20240101_12000{i}_CAM_{i + 1:04d}.mp4'
            self.sources.append(path)
            self.items.append(PreviewItem(str(i), 'video', str(path), str(folder), str(folder / name), name,
                                         'NEW', f'2024-01-01T12:00:0{i}', 'filename', 'CAM', 'filename', [],
                                         mobile_output_enabled=True,
                                         mobile_output_path=str(folder / f'output_{folder.name}' / name)))
        self.job = JobState(phase='PREVIEW_READY', settings=AppSettings(
            source_path=str(source), target_path=str(self.base / 'target'), video_workers=2),
            preview_bundle=PreviewBundle(preview_items=self.items), source_fingerprints=capture_file_states(self.sources))
        self.engine = OrganizerEngine(self.base)

    @staticmethod
    def convert(source, target, media_type, request):
        target.write_bytes(source.read_bytes())
        return 'SUCCESS'

    def test_two_actual_video_workers_and_reverse_completion_preserve_sequence(self):
        # Synchronization proves overlapping workers and reverse durable
        # completion; the timeout only bounds a deadlock, not disk performance.
        synchronization_timeout = 60
        both = threading.Barrier(2)
        second_done = threading.Event()
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            result = original(journal, job, item_id, stage, record)
            if item_id == self.items[1].item_id and stage == 'output' and record['state'] == 'DONE':
                second_done.set()
            return result
        def convert(source, target, media_type, request):
            both.wait(synchronization_timeout)
            if source.name == self.items[0].new_filename:
                self.assertTrue(second_done.wait(synchronization_timeout),
                                'Second video durable completion was not observed')
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertTrue(second_done.is_set())
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS', 'SUCCESS'],
                         [(r.source_path, r.message, r.mobile_output_message)
                          for r in result.execution_results])
        self.assertEqual([r.source_path for r in result.execution_results], list(map(str, self.sources)))
        self.assertEqual([i.new_filename[-8:] for i in result.preview_items], ['0001.mp4', '0002.mp4'])

    def test_stop_pair_requeues_without_completion_and_continue_preserves_main(self):
        self.job.settings.operation_mode = 'move'
        control = OperationControl()
        both = threading.Barrier(2)
        def convert(source, target, media_type, request):
            both.wait(3)
            control.request_stop()
            control.raise_if_interrupted()
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial', control=control)
        self.assertEqual(result.execution_results, [])
        self.assertEqual(control.result_summary().completed_keys, frozenset())
        fingerprints = capture_file_states([i.target_path for i in self.items])
        for item in self.items:
            self.assertEqual(self.job.ledger[item.item_id]['main']['state'], 'DONE')
            self.assertEqual(self.job.ledger[item.item_id]['output']['state'], 'PENDING')
            self.assertEqual(self.job.ledger[item.item_id]['source_remove']['state'], 'PENDING')
            self.assertTrue(Path(item.source_path).exists())
            self.assertFalse(Path(item.mobile_output_path).exists())
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.convert):
            result = self.engine.resume(self.job, 'continue', control=OperationControl())
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS', 'SUCCESS'])
        self.assertEqual(capture_file_states([i.target_path for i in self.items]), fingerprints)

    def test_retry_does_not_repeat_done_video(self):
        both = threading.Barrier(2)
        done = threading.Event()
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            result = original(journal, job, item_id, stage, record)
            if item_id == self.items[0].item_id and stage == 'output' and record['state'] == 'DONE':
                done.set()
            return result
        def convert(source, target, media_type, request):
            both.wait(3)
            if source.name == self.items[1].new_filename:
                self.assertTrue(done.wait(5))
                raise RuntimeError('second encode failed')
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            self.engine.resume(self.job, 'initial')
        first = self.items[0]
        before = capture_file_states([first.target_path, first.mobile_output_path])
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.convert) as convert_mock:
            result = self.engine.resume(self.job, 'retry')
        self.assertEqual(convert_mock.call_count, 1)
        self.assertEqual(capture_file_states([first.target_path, first.mobile_output_path]), before)
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS', 'SUCCESS'])
        self.assertTrue(all(p.exists() for p in self.sources))

    def test_video_workers_rejects_bool_and_unsupported_count(self):
        for value in (True, 3):
            with self.subTest(value=value):
                self.job.settings.video_workers = value
                with self.assertRaises(ValueError):
                    self.engine.resume(self.job, 'initial')
        self.assertFalse(Path(self.items[0].target_path).exists())

    def test_photo_and_video_batches_never_overlap(self):
        import copy
        for i in range(2):
            item = copy.deepcopy(self.items[i])
            item.item_id = f'photo{i}'
            item.media_type = 'photo'
            item.source_path = item.source_path.replace('.mp4', '.jpg')
            item.target_path = item.target_path.replace('.mp4', '.jpg')
            item.new_filename = item.new_filename.replace('.mp4', '.jpg')
            item.mobile_output_path = item.mobile_output_path.replace('.mp4', '.jpg')
            Path(item.source_path).write_bytes(b'synthetic photo')
            self.items.append(item)
            self.sources.append(Path(item.source_path))
        self.job.source_fingerprints = capture_file_states(self.sources)
        barriers = {kind: threading.Barrier(2) for kind in ('photo', 'video')}
        active = []
        observed = []
        lock = threading.Lock()
        def convert(source, target, media_type, request):
            with lock:
                active.append(media_type)
                observed.append(tuple(active))
            try:
                barriers[media_type].wait(10)
                return self.convert(source, target, media_type, request)
            finally:
                with lock:
                    active.remove(media_type)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertTrue(all(len(set(kinds)) == 1 for kinds in observed))
        self.assertIn(('photo', 'photo'), observed)
        self.assertIn(('video', 'video'), observed)
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS'] * 4)

    def test_pause_pair_retries_current_outputs_after_resume(self):
        control = OperationControl()
        both = threading.Barrier(2)
        initial_calls = []
        lock = threading.Lock()
        results, failures = [], []
        def convert(source, target, media_type, request):
            with lock:
                initial = len(initial_calls) < 2
                initial_calls.append(source.name)
            if initial:
                both.wait(10)
                control.request_pause()
                control.raise_if_interrupted()
            return self.convert(source, target, media_type, request)
        def run():
            try:
                results.append(self.engine.resume(self.job, 'initial', control=control))
            except BaseException as exc:
                failures.append(exc)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                self.assertTrue(control.wait_until_paused(20), str(failures))
                self.assertEqual(control.result_summary().completed_keys, frozenset())
                self.assertTrue(all(self.job.ledger[i.item_id]['output']['state'] == 'PENDING' for i in self.items))
                control.resume()
                thread.join(20)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual([r.status for r in results[0].execution_results], ['SUCCESS', 'SUCCESS'])
                self.assertEqual(len(initial_calls), 4)
            finally:
                control.request_stop()
                thread.join(10)

    def test_default_one_video_worker_is_serial(self):
        self.assertEqual(AppSettings().video_workers, 1)
        self.job.settings.video_workers = 1
        first_done = threading.Event()
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            result = original(journal, job, item_id, stage, record)
            if item_id == self.items[0].item_id and stage == 'output' and record['state'] == 'DONE':
                first_done.set()
            return result
        def convert(source, target, media_type, request):
            if source.name == self.items[1].new_filename:
                self.assertTrue(first_done.is_set())
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS', 'SUCCESS'])
