import sys
import threading
import unittest
import subprocess
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.execution_lock import ExecutionLock


class ExecutionLockTests(unittest.TestCase):
    def test_separate_folder_process_is_blocked_and_crash_releases_lock(self):
        module_path = str(Path(__file__).resolve().parents[1] / 'src')
        script = ("import sys; sys.path.insert(0, sys.argv[1]); "
                  "from photo_organizer.execution_lock import ExecutionLock; "
                  "lock=ExecutionLock(); lock.__enter__(); print('held', flush=True); sys.stdin.read()")
        with tempfile.TemporaryDirectory() as other_folder:
            process = subprocess.Popen([sys.executable, '-c', script, module_path], cwd=other_folder,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'held')
                with self.assertRaises(RuntimeError):
                    with ExecutionLock():
                        pass
            finally:
                process.kill()
                process.communicate(timeout=10)
        with ExecutionLock():
            pass

    def test_concurrent_thread_cannot_execute_and_release_allows_next(self):
        observed = []
        def other():
            try:
                with ExecutionLock():
                    observed.append('acquired')
            except RuntimeError:
                observed.append('blocked')
        with ExecutionLock():
            thread = threading.Thread(target=other)
            thread.start()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed, ['blocked'])
        other()
        self.assertEqual(observed, ['blocked', 'acquired'])

    def test_exception_releases_mutex(self):
        with self.assertRaises(ValueError):
            with ExecutionLock():
                raise ValueError('test')
        with ExecutionLock():
            pass


if __name__ == '__main__':
    unittest.main()
