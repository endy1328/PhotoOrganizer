import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.operation_control import OperationControl


class OperationControlTests(unittest.TestCase):
    def test_pause_waits_and_resume_releases(self):
        control = OperationControl()
        control.request_pause()
        result = []
        worker = threading.Thread(target=lambda: result.append(control.checkpoint()))
        worker.start()
        self.addCleanup(control.request_stop)
        self.assertTrue(control.wait_until_paused(2))
        self.assertFalse(result)
        control.resume()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])

    def test_stop_releases_pause_and_remains_stopped(self):
        control = OperationControl()
        control.request_pause()
        result = []
        worker = threading.Thread(target=lambda: result.append(control.checkpoint()))
        worker.start()
        self.addCleanup(control.request_stop)
        self.assertTrue(control.wait_until_paused(2))
        control.request_stop()
        worker.join(2)
        self.assertEqual(result, [False])
        self.assertTrue(control.stopped)
        control.resume()
        self.assertFalse(control.checkpoint())

    def test_cancel_pause_request_before_boundary(self):
        control = OperationControl()
        control.request_pause()
        control.resume()
        self.assertTrue(control.checkpoint())
        self.assertFalse(control.paused)


if __name__ == '__main__':
    unittest.main()
