"""Windows worker/descendant lifetime; not a frozen EXE protocol test."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@unittest.skipUnless(os.name == 'nt', 'Windows Job Object regression')
class IsolatedProcessTreeTests(unittest.TestCase):
    def test_pause_kills_worker_and_its_confirmed_running_descendant(self):
        import ctypes
        from ctypes import wintypes
        from photo_organizer.isolated_work import IsolatedWorker
        from photo_organizer.operation_control import OperationControl, OperationInterrupted

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Hold the descendant handle to avoid treating PID reuse as survival.
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'descendant.pid'
            descendant_script = (
                'import os,time; from pathlib import Path; '
                f'Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)')
            worker_script = (
                'import subprocess,sys; from photo_organizer.metadata import MetadataExtractor; '
                f'definition = {("def extract(self,*args):\n p=subprocess.Popen([sys.executable,\"-c\", " + repr(descendant_script) + "])\n p.communicate()\n")!r}; '
                'exec(definition); MetadataExtractor.extract=extract; '
                'from photo_organizer.isolated_work import worker_main; worker_main()')
            original_popen = subprocess.Popen
            def launch(command, **options):
                from photo_organizer.isolated_work import worker_executable
                return original_popen([worker_executable(), '-c', worker_script], **options)
            control = OperationControl()
            errors = []
            with patch('photo_organizer.isolated_work.subprocess.Popen', side_effect=launch):
                with IsolatedWorker() as worker:
                    def run():
                        try:
                            with control.file_activity('test', 'test.jpg', 'metadata'):
                                worker.call('metadata', (Path('test.jpg'),))
                        except BaseException as exc:
                            errors.append(exc)
                    thread = threading.Thread(target=run, daemon=True)
                    thread.start()
                    descendant_handle = None
                    try:
                        deadline = time.monotonic() + 10
                        while not marker.exists() and thread.is_alive() and time.monotonic() < deadline:
                            time.sleep(.025)
                        self.assertTrue(marker.exists(), f'descendant did not start: {errors!r}')
                        pid = int(marker.read_text())
                        descendant_handle = kernel.OpenProcess(0x00100001, False, pid)
                        self.assertTrue(descendant_handle, f'cannot open descendant PID {pid}')
                        self.assertEqual(kernel.WaitForSingleObject(descendant_handle, 0), 258,
                                         'descendant must actually be running before pause')
                        control.request_pause()
                        thread.join(5)
                        stack = ''.join(traceback.format_stack(sys._current_frames()[thread.ident])) if thread.is_alive() else ''
                        self.assertFalse(thread.is_alive(),
                                         f'worker call did not cancel; worker={worker.process.poll()}; '
                                         f'descendant wait={kernel.WaitForSingleObject(descendant_handle, 0)}; {stack}')
                        self.assertEqual(len(errors), 1)
                        self.assertIsInstance(errors[0], OperationInterrupted)
                        self.assertIsNotNone(worker.process.poll(), 'worker survived cancellation')
                        self.assertEqual(kernel.WaitForSingleObject(descendant_handle, 3000), 0,
                                         'descendant survived Job Object close')
                    finally:
                        control.request_stop()
                        # Failure cleanup only: do not leave our synthetic sleeper alive.
                        if descendant_handle and kernel.WaitForSingleObject(descendant_handle, 0) == 258:
                            kernel.TerminateProcess(descendant_handle, 99)
                            kernel.WaitForSingleObject(descendant_handle, 3000)
                        worker.close()
                        thread.join(5)
                        if descendant_handle:
                            kernel.CloseHandle(descendant_handle)
