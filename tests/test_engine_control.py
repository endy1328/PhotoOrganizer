import sys
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from photo_organizer.operation_control import OperationControl, OperationStopped


class EngineControlTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import AppSettings, OrganizeRequest
        from photo_organizer.job_store import JobState
        from photo_organizer.job_validation import capture_file_states
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='engine_control_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.sources = [self.source / f'20240101_12000{i}_CAM.jpg' for i in range(2)]
        for path in self.sources:
            Image.new('RGB', (16, 16), 'blue').save(path)
        self.engine = OrganizerEngine(self.base)
        self.request = OrganizeRequest(self.source, self.base / 'target', mobile_output_enabled=False, photo_workers=1)
        self.preview = self.engine.preview(self.request)
        self.job = JobState(phase='PREVIEW_READY', preview_bundle=self.preview,
                            settings=AppSettings(source_path=str(self.source), target_path=str(self.base / 'target'), mobile_output_enabled=False, photo_workers=1),
                            source_fingerprints=capture_file_states(self.sources))
        self.items = self.preview.preview_items
        self.control = OperationControl()

    def worker(self, operation):
        result, failures = [], []
        def run():
            try:
                result.append(operation())
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(self.control.request_stop)
        return thread, result, failures

    def finish(self, thread, failures):
        thread.join(30)
        self.assertFalse(thread.is_alive(), self.diagnostics(thread, failures))
        self.assertEqual(failures, [])

    def diagnostics(self, thread, failures):
        frame = sys._current_frames().get(thread.ident)
        stack = ''.join(traceback.format_stack(frame)) if frame is not None else ''
        return (f'worker alive={thread.is_alive()}, paused={self.control.paused}, '
                f'pause_requested={self.control.pause_requested}, failures={failures}, '
                f'ledger={self.job.ledger}\n{stack}')

    def test_stop_after_file_preserves_pending_and_saved_job_can_continue(self):
        from photo_organizer.job_store import save_job, load_job
        def progress(message, current, total):
            if current == 1:
                self.control.request_stop()
        result = self.engine.resume(self.job, 'initial', progress_callback=progress, control=self.control)
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        self.assertEqual(self.job.ledger[self.items[1].item_id]['main']['state'], 'PENDING')
        self.assertTrue(self.control.stopped)
        saved = self.base / 'stopped.pojob.json'
        save_job(self.job, saved)
        loaded = load_job(saved)
        resumed = self.engine.resume(loaded, 'continue', control=OperationControl())
        self.assertEqual(len(resumed.execution_results), 2)
        self.assertTrue(all(result.status == 'SUCCESS' for result in resumed.execution_results))

    def test_move_stop_during_output_finishes_output_and_removal_of_current_file(self):
        self.job.settings.operation_mode = 'move'
        self.job.settings.mobile_output_enabled = True
        for item in self.items:
            item.mobile_output_enabled = True
            item.mobile_output_path = str(self.engine._build_mobile_output_path(Path(item.target_directory), item.new_filename))
        def output(source, target, media_type, request):
            self.control.request_stop()
            target.write_bytes(source.read_bytes())
            return 'SUCCESS'
        with patch.object(self.engine, '_create_mobile_output', side_effect=output):
            result = self.engine.resume(self.job, 'initial', control=self.control)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        self.assertFalse(self.sources[0].exists())
        self.assertTrue(Path(self.items[0].mobile_output_path).exists())
        self.assertTrue(self.sources[1].exists())
        self.assertFalse(Path(self.items[1].target_path).exists())
        self.assertEqual(self.job.ledger[self.items[1].item_id]['main']['state'], 'PENDING')

    def test_stop_during_main_copy_still_finishes_current_mobile_and_move(self):
        import shutil
        self.job.settings.operation_mode = 'move'
        self.job.settings.mobile_output_enabled = True
        for item in self.items:
            item.mobile_output_enabled = True
            item.mobile_output_path = str(self.engine._build_mobile_output_path(Path(item.target_directory), item.new_filename))
        original_copy = shutil.copyfileobj
        def copy(reader, writer, *args, **kwargs):
            original_copy(reader, writer, *args, **kwargs)
            self.control.request_stop()
        def output(source, target, media_type, request):
            target.write_bytes(source.read_bytes())
            return 'SUCCESS'
        with patch('photo_organizer.resume_engine.shutil.copyfileobj', side_effect=copy), patch.object(self.engine, '_create_mobile_output', side_effect=output) as convert:
            result = self.engine.resume(self.job, 'initial', control=self.control)
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        convert.assert_called_once()
        self.assertFalse(self.sources[0].exists())
        self.assertTrue(Path(self.items[0].mobile_output_path).exists())
        self.assertTrue(self.sources[1].exists())

    def test_pause_waits_after_full_file_then_resume_processes_next(self):
        def progress(message, current, total):
            if current == 1:
                self.control.request_pause()
        thread, results, failures = self.worker(lambda: self.engine.resume(self.job, 'initial', progress_callback=progress, control=self.control))
        try:
            self.assertTrue(self.control.wait_until_paused(30), self.diagnostics(thread, failures))
            self.assertTrue(Path(self.items[0].target_path).exists())
            self.assertFalse(Path(self.items[1].target_path).exists())
            self.control.resume()
            self.finish(thread, failures)
            self.assertEqual(len(results[0].execution_results), 2)
        finally:
            self.control.request_stop()
            thread.join(30)

    def test_stop_while_paused_unblocks_and_leaves_next_file_pending(self):
        def progress(message, current, total):
            if current == 1:
                self.control.request_pause()
        thread, results, failures = self.worker(lambda: self.engine.resume(self.job, 'initial', progress_callback=progress, control=self.control))
        try:
            self.assertTrue(self.control.wait_until_paused(30), self.diagnostics(thread, failures))
            self.control.request_stop()
            self.finish(thread, failures)
            self.assertEqual(len(results[0].execution_results), 1)
            self.assertEqual(self.job.ledger[self.items[1].item_id]['main']['state'], 'PENDING')
        finally:
            self.control.request_stop()
            thread.join(30)

    def test_last_file_pause_request_does_not_wait_after_completion(self):
        self.items[1].included = False
        def progress(message, current, total):
            self.control.request_pause()
        thread, results, failures = self.worker(lambda: self.engine.resume(self.job, 'initial', progress_callback=progress, control=self.control))
        try:
            self.finish(thread, failures)
            self.assertEqual(results[0].execution_results[0].status, 'SUCCESS')
            self.assertFalse(self.control.paused)
            self.assertFalse(self.control.stopped)
        finally:
            self.control.request_stop()
            thread.join(30)

    def test_stop_before_first_file_does_not_mark_failed(self):
        self.control.request_stop()
        result = self.engine.resume(self.job, 'initial', control=self.control)
        self.assertEqual(result.execution_results, [])
        self.assertTrue(all(record['main']['state'] == 'PENDING' for record in self.job.ledger.values()))
        self.assertFalse(Path(self.items[0].target_path).exists())

    def test_last_file_stop_request_finishes_without_incomplete_status(self):
        self.items[1].included = False
        def progress(message, current, total):
            self.control.request_stop()
        result = self.engine.resume(self.job, 'initial', progress_callback=progress, control=self.control)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        self.assertEqual(self.job.phase, 'EXECUTION_FINISHED')
        self.assertFalse(self.control.stopped)

    def test_preview_stop_after_metadata_does_not_return_partial_preview(self):
        original = self.engine.extractor.extract
        def extract(path):
            result = original(path)
            self.control.request_stop()
            return result
        with patch.object(self.engine.extractor, 'extract', side_effect=extract) as read:
            with self.assertRaises(OperationStopped):
                self.engine.preview(self.request, control=self.control)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(len(self.preview.preview_items), 2)

    def test_preview_pause_is_between_metadata_files(self):
        original = self.engine.extractor.extract
        count = []
        def extract(path):
            result = original(path)
            count.append(path)
            if len(count) == 1:
                self.control.request_pause()
            return result
        with patch.object(self.engine.extractor, 'extract', side_effect=extract):
            thread, results, failures = self.worker(lambda: self.engine.preview(self.request, control=self.control))
            try:
                self.assertTrue(self.control.wait_until_paused(5))
                self.assertEqual(len(count), 1)
                self.control.resume()
                self.finish(thread, failures)
                self.assertEqual(len(results[0].preview_items), 2)
            finally:
                self.control.request_stop()
                thread.join(5)

    def test_direct_nonjournal_execute_honors_stop_between_files(self):
        def progress(message, current, total):
            if current == 1:
                self.control.request_stop()
        result = self.engine.execute(self.request, preview_bundle=self.preview, progress_callback=progress, control=self.control)
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, 'SUCCESS')
        self.assertFalse(Path(self.items[1].target_path).exists())

    def test_scan_stop_is_checked_before_metadata(self):
        self.control.request_stop()
        with patch.object(self.engine.extractor, 'extract') as read:
            with self.assertRaises(OperationStopped):
                self.engine.preview(self.request, control=self.control)
        read.assert_not_called()

    def test_preview_stop_at_last_metadata_does_not_publish_complete_plan(self):
        original = self.engine.extractor.extract
        count = []
        def extract(path):
            result = original(path)
            count.append(path)
            if len(count) == 2:
                self.control.request_stop()
            return result
        with patch.object(self.engine.extractor, 'extract', side_effect=extract):
            with self.assertRaises(OperationStopped):
                self.engine.preview(self.request, control=self.control)
        self.assertEqual(len(count), 2)


if __name__ == '__main__':
    unittest.main()
