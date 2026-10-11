import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ParallelPhotoTests(unittest.TestCase):
    def setUp(self):
        from uuid import uuid4
        # Synthetic unit executions must not compete with a user's live app.
        namespace = patch('photo_organizer.execution_lock.MUTEX_NAME', 'Global\\PhotoOrganizerParallelTest_' + str(uuid4()))
        namespace.start()
        self.addCleanup(namespace.stop)
        from PIL import Image
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import AppSettings, OrganizeRequest
        from photo_organizer.job_store import JobState
        from photo_organizer.job_validation import capture_file_states
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='parallel_photos_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        source = self.base / 'source'
        source.mkdir()
        self.sources = [source / f'20240101_12000{i}_CAM.jpg' for i in range(4)]
        for path in self.sources:
            Image.new('RGB', (32, 16), 'blue').save(path)
        self.engine = OrganizerEngine(self.base)
        self.request = OrganizeRequest(source, self.base / 'target', mobile_output_enabled=True, photo_workers=2)
        self.job = JobState(phase='PREVIEW_READY', settings=AppSettings(source_path=str(source), target_path=str(self.base / 'target'),
                            mobile_output_enabled=True, photo_workers=2), preview_bundle=self.engine.preview(self.request),
                            source_fingerprints=capture_file_states(self.sources))
        self.items = self.job.preview_bundle.preview_items

    @staticmethod
    def convert(source, target, media_type, request):
        target.write_bytes(source.read_bytes())
        return 'SUCCESS'

    def test_reverse_completion_preserves_planned_names_and_results_order(self):
        from photo_organizer.execution_journal import ExecutionJournal
        second_done = threading.Event()
        planned = [item.new_filename for item in self.items]
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            result = original(journal, job, item_id, stage, record)
            if item_id == self.items[1].item_id and stage == 'output' and record['state'] == 'DONE':
                second_done.set()
            return result
        def convert(source, target, media_type, request):
            if source.name == planned[0]:
                if not second_done.wait(30):
                    raise RuntimeError(f'second photo did not finish concurrently; ledger={self.job.ledger}')
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertTrue(second_done.is_set())
        self.assertTrue(all(r.status == 'SUCCESS' for r in result.execution_results),
                        [(r.status, r.message, r.mobile_output_message) for r in result.execution_results])
        self.assertEqual([r.source_path for r in result.execution_results], [str(p) for p in self.sources])
        self.assertEqual([i.new_filename for i in result.preview_items], planned)

    def test_stop_finishes_started_pair_and_leaves_tail_pending(self):
        from photo_organizer.operation_control import OperationControl
        control = OperationControl()
        both = threading.Barrier(2)
        def convert(source, target, media_type, request):
            both.wait(30)
            control.request_stop()
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial', control=control)
        self.assertEqual(len(result.execution_results), 2)
        self.assertTrue(all(r.status == 'SUCCESS' for r in result.execution_results))
        self.assertTrue(control.stopped)
        self.assertTrue(all(self.job.ledger[i.item_id]['main']['state'] == 'PENDING' for i in self.items[2:]))

    def test_failed_photo_does_not_recopy_successful_neighbours_on_retry(self):
        def convert(source, target, media_type, request):
            if source.name == self.items[0].new_filename:
                raise RuntimeError('first output failed')
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            self.engine.resume(self.job, 'initial')
        times = {i.item_id: Path(i.target_path).stat().st_mtime_ns for i in self.items if Path(i.target_path).exists()}
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.convert):
            self.engine.resume(self.job, 'retry')
        for item in self.items:
            if item.item_id in times:
                self.assertEqual(Path(item.target_path).stat().st_mtime_ns, times[item.item_id])
        self.assertEqual(self.job.ledger[self.items[0].item_id]['output']['state'], 'DONE')

    def test_move_output_failure_preserves_original(self):
        self.job.settings.operation_mode = 'move'
        def convert(source, target, media_type, request):
            if source.name == self.items[0].new_filename:
                raise RuntimeError('first output failed')
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            self.engine.resume(self.job, 'initial')
        self.assertTrue(self.sources[0].exists())
        self.assertEqual(self.job.ledger[self.items[0].item_id]['source_remove']['state'], 'PENDING')

    def test_journal_failure_prevents_other_staged_output_publication(self):
        from photo_organizer.execution_journal import ExecutionJournal
        from photo_organizer.resume_engine import JournalCommitError
        self.job.settings.operation_mode = 'move'
        both = threading.Barrier(2)
        failure = threading.Event()
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            if item_id == self.items[0].item_id and stage == 'output' and record['state'] == 'DONE':
                failure.set()
                raise OSError('completion journal unavailable')
            return original(journal, job, item_id, stage, record)
        def convert(source, target, media_type, request):
            both.wait(30)
            if source.name == self.items[1].new_filename:
                if not failure.wait(30):
                    raise RuntimeError('journal fault not observed')
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            with self.assertRaises(JournalCommitError):
                self.engine.resume(self.job, 'initial')
        self.assertTrue(Path(self.items[0].mobile_output_path).exists())
        self.assertFalse(Path(self.items[1].mobile_output_path).exists())
        self.assertTrue(self.sources[0].exists())
        self.assertTrue(self.sources[1].exists())
        self.assertEqual(self.job.ledger[self.items[2].item_id]['main']['state'], 'PENDING')

    def test_duplicate_destinations_rejected_before_media_changes(self):
        self.items[1].new_filename = self.items[0].new_filename
        self.items[1].target_path = self.items[0].target_path
        self.items[1].mobile_output_path = self.items[0].mobile_output_path
        self.items[1].filename_edited = True
        with self.assertRaises(ValueError):
            self.engine.resume(self.job, 'initial')
        self.assertFalse(Path(self.items[0].target_path).exists())

    def test_queued_photo_skipped_on_pause_is_resubmitted_after_resume(self):
        from concurrent.futures import ThreadPoolExecutor
        from photo_organizer.operation_control import OperationControl
        control = OperationControl()
        results, failures = [], []
        def convert(source, target, media_type, request):
            if source.name == self.items[0].new_filename:
                control.request_pause()
            return self.convert(source, target, media_type, request)
        def run():
            try:
                results.append(self.engine.resume(self.job, 'initial', control=control))
            except BaseException as exc:
                failures.append(exc)
        # Force a submitted second item to stay queued until pause is requested.
        def single_worker(*args, **kwargs):
            return ThreadPoolExecutor(max_workers=1)
        with patch('photo_organizer.resume_engine.ThreadPoolExecutor', side_effect=single_worker), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                self.assertTrue(control.wait_until_paused(30),
                                f'alive={thread.is_alive()}, pause_requested={control.pause_requested}, '
                                f'failures={failures}, ledger={self.job.ledger}')
                self.assertEqual(self.job.ledger[self.items[1].item_id]['main']['state'], 'PENDING')
                control.resume()
                thread.join(30)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(len(results[0].execution_results), 4)
                self.assertTrue(all(r.status == 'SUCCESS' for r in results[0].execution_results))
            finally:
                control.request_stop()
                thread.join(10)

    def test_photos_and_video_never_overlap_and_unknown_sequence_stays_fixed(self):
        from photo_organizer.models import MediaItem
        from photo_organizer.job_validation import capture_file_states
        from datetime import datetime
        video_dir = self.sources[0].parent / 'video'
        video_dir.mkdir()
        video = video_dir / '20240101_120001.mp4'
        video.write_bytes(b'video')
        original = self.engine.extractor.extract
        def extract(path):
            if path.suffix == '.mp4':
                return MediaItem(path, 'video', '.mp4', datetime(2024, 1, 1, 12, 0, 1), '영상 메타')
            return original(path)
        with patch.object(self.engine.extractor, 'extract', side_effect=extract):
            self.job.preview_bundle = self.engine.preview(self.request)
        self.job.source_fingerprints = capture_file_states([*self.sources, video])
        planned = [(i.item_id, i.new_filename) for i in self.job.preview_bundle.preview_items]
        active = []
        lock = threading.Lock()
        def convert(source, target, media_type, request):
            with lock:
                self.assertFalse(media_type == 'video' and active)
                self.assertFalse(media_type == 'photo' and 'video' in active)
                active.append(media_type)
            try:
                return self.convert(source, target, media_type, request)
            finally:
                with lock:
                    active.remove(media_type)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertTrue(all(r.status == 'SUCCESS' for r in result.execution_results))
        self.assertEqual([(i.item_id, i.new_filename) for i in result.preview_items], planned)
        video_item = next(i for i in result.preview_items if i.media_type == 'video')
        self.assertEqual(video_item.model_name, 'UNKNOWN')
        self.assertEqual([int(Path(i.new_filename).stem.rsplit('_', 1)[1]) for i in result.preview_items], [1, 2, 3, 4, 5])

    def test_video_report_kept_when_output_is_policy_skipped(self):
        from photo_organizer.models import MediaItem
        from photo_organizer.job_validation import capture_file_states
        from datetime import datetime
        video = self.sources[0].parent / '20240101_120010.mp4'
        video.write_bytes(b'video')
        original = self.engine.extractor.extract
        with patch.object(self.engine.extractor, 'extract', side_effect=lambda path: MediaItem(path, 'video', '.mp4', datetime(2024, 1, 1, 12, 0, 10), '영상 메타') if path == video else original(path)):
            self.job.preview_bundle = self.engine.preview(self.request)
        self.job.source_fingerprints = capture_file_states([*self.sources, video])
        def convert(source, target, media_type, request):
            if media_type == 'video':
                return 'SKIPPED'
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert), patch('photo_organizer.video_output.get_last_video_encoder_report', return_value='GPU 실패 후 CPU 사용'):
            result = self.engine.resume(self.job, 'initial')
        video_result = next(r for r in result.execution_results if r.source_path == str(video))
        self.assertEqual(video_result.mobile_output_status, 'SKIPPED')
        self.assertIn('GPU 실패 후 CPU 사용', video_result.mobile_output_message)

    def test_overwrite_rechecks_existing_file_after_durable_publish_intent(self):
        from photo_organizer.execution_journal import ExecutionJournal
        self.job.settings.photo_workers = 1
        for item in self.items[1:]:
            item.included = False
        first = self.items[0]
        first.write_mode = 'OVERWRITE'
        target = Path(first.target_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'existing')
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            original(journal, job, item_id, stage, record)
            if stage == 'main' and record['message'] == '최종 파일 게시 시작':
                target.write_bytes(b'external writer changed existing file')
        with patch.object(ExecutionJournal, 'update', new=update):
            result = self.engine.resume(self.job, 'initial')
        self.assertEqual(target.read_bytes(), b'external writer changed existing file')
        self.assertEqual(result.execution_results[0].status, 'ERROR')
        self.assertEqual(self.job.ledger[first.item_id]['main']['state'], 'FAILED')

    def test_move_rechecks_source_after_waiting_for_publication_gate(self):
        from contextlib import contextmanager
        from photo_organizer.resume_engine import _JournalCoordinator
        self.job.settings.operation_mode = 'move'
        self.job.settings.photo_workers = 1
        for item in self.items[1:]:
            item.included = False
        original = _JournalCoordinator.publication
        first = self.items[0]
        @contextmanager
        def publication(coordinator):
            if self.job.ledger[first.item_id]['source_remove']['state'] == 'IN_PROGRESS':
                self.sources[0].write_bytes(b'externally modified original')
            with original(coordinator):
                yield
        with patch.object(_JournalCoordinator, 'publication', new=publication), patch.object(self.engine, '_create_mobile_output', side_effect=self.convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertEqual(self.sources[0].read_bytes(), b'externally modified original')
        self.assertEqual(self.job.ledger[first.item_id]['source_remove']['state'], 'FAILED')
        self.assertEqual(result.execution_results[0].status, 'ERROR')

    def test_video_failure_before_converter_does_not_attach_previous_report(self):
        from photo_organizer.models import MediaItem
        from photo_organizer.job_validation import capture_file_states
        from photo_organizer import resume_engine
        from datetime import datetime
        video = self.sources[0].parent / '20240101_120010.mp4'
        video.write_bytes(b'video')
        original_extract = self.engine.extractor.extract
        with patch.object(self.engine.extractor, 'extract', side_effect=lambda path: MediaItem(path, 'video', '.mp4', datetime(2024, 1, 1, 12, 0, 10), '영상 메타') if path == video else original_extract(path)):
            self.job.preview_bundle = self.engine.preview(self.request)
        self.job.source_fingerprints = capture_file_states([*self.sources, video])
        item = next(i for i in self.job.preview_bundle.preview_items if i.media_type == 'video')
        for other in self.job.preview_bundle.preview_items:
            other.included = other is item
        original_assert = resume_engine._assert_baseline
        def check(path, baselines):
            if self.job.ledger[item.item_id]['output']['state'] == 'IN_PROGRESS':
                raise ValueError('변환 전 원본 검사 실패')
            return original_assert(path, baselines)
        with patch.object(resume_engine, '_assert_baseline', side_effect=check), patch('photo_organizer.video_output.get_last_video_encoder_report', return_value='이전 영상 GPU 보고'), patch.object(self.engine, '_create_mobile_output') as converter:
            result = self.engine.resume(self.job, 'initial')
        converter.assert_not_called()
        self.assertNotIn('이전 영상', result.execution_results[0].mobile_output_message)
        self.assertIn('변환 전', result.execution_results[0].mobile_output_message)


if __name__ == '__main__':
    unittest.main()
