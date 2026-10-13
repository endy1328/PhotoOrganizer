import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class IsolatedWorkTests(unittest.TestCase):
    def test_cleanup_attempts_every_worker_after_one_close_fails(self):
        from photo_organizer.isolated_work import close_workers
        from photo_organizer.operation_control import OperationControl
        from unittest.mock import Mock
        control = OperationControl()
        first, second = Mock(), Mock()
        first.close.side_effect = RuntimeError('cleanup failed')
        control._isolated_workers = {1: first, 2: second}
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            close_workers(control)
        second.close.assert_called_once()
        self.assertEqual(control._isolated_workers, {})

    def test_slow_native_worker_is_terminated_on_pause(self):
        from photo_organizer.isolated_work import IsolatedWorker, worker_executable
        from photo_organizer.operation_control import OperationControl, OperationInterrupted
        original = subprocess.Popen
        script = ('from photo_organizer.metadata import MetadataExtractor; '
                  'import time; MetadataExtractor.extract=lambda self,*args: time.sleep(20); '
                  'from photo_organizer.isolated_work import worker_main; worker_main()')
        def launch(command, **options):
            return original([worker_executable(), '-c', script], **options)
        control = OperationControl()
        with patch('photo_organizer.isolated_work.subprocess.Popen', side_effect=launch):
            with IsolatedWorker() as worker:
                start = time.monotonic()
                timer = threading.Timer(.4, control.request_pause)
                timer.start()
                try:
                    with control.file_activity('test', 'test.jpg', 'metadata'):
                        with self.assertRaises(OperationInterrupted):
                            worker.call('metadata', (Path('test.jpg'),))
                    self.assertIsNotNone(worker.process.poll())
                    self.assertLess(time.monotonic() - start, 3)
                finally:
                    timer.cancel()

    def test_metadata_worker_reuses_process_and_returns_media_item(self):
        from photo_organizer.isolated_work import IsolatedWorker
        with tempfile.TemporaryDirectory() as folder, IsolatedWorker() as worker:
            path = Path(folder) / '20241012_123456_SM-Test.jpg'
            path.write_bytes(b'invalid image')
            first = worker.call('metadata', (path,))
            pid = worker.process.pid
            second = worker.call('metadata', (path,))
            self.assertEqual(worker.process.pid, pid)
            self.assertEqual(first.captured_at, second.captured_at)
            self.assertEqual(first.model_name, 'SM-Test')

    def test_child_process_is_killed_before_slow_command_finishes(self):
        from photo_organizer.isolated_work import worker_executable
        from photo_organizer.operation_control import OperationControl, OperationInterrupted
        from photo_organizer.process_utils import run_process
        control = OperationControl()
        threading.Timer(.2, control.request_stop).start()
        start = time.monotonic()
        with control.file_activity('test', 'test', 'output'):
            with self.assertRaises(OperationInterrupted):
                run_process([worker_executable(), '-c', 'import time; time.sleep(20)'],
                            capture_output=True, check=True)
        self.assertLess(time.monotonic() - start, 3)

    def test_photo_worker_writes_resized_image(self):
        from PIL import Image
        from photo_organizer.isolated_work import IsolatedWorker
        with tempfile.TemporaryDirectory() as folder, IsolatedWorker() as worker:
            source, target = Path(folder) / 'source.jpg', Path(folder) / 'target.jpg'
            Image.new('RGB', (400, 200), 'blue').save(source)
            worker.call('photo', (source, target, 100, 75, True, 'balanced'))
            with Image.open(target) as image:
                self.assertEqual(image.size, (100, 50))


if __name__ == '__main__':
    unittest.main()
