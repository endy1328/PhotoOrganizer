import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.operation_control import OperationControl


class OperationResultsTests(unittest.TestCase):
    def test_parallel_results_are_immutable_and_drained_once(self):
        control = OperationControl()
        threads = [threading.Thread(target=control.report_file_result,
                   args=(str(i), f'{i}.jpg', 'SUCCESS', '완료')) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        results = control.drain_file_results()
        self.assertEqual({r.key for r in results}, {'0', '1', '2', '3'})
        with self.assertRaises(AttributeError):
            results[0].status = 'ERROR'
        self.assertEqual(control.drain_file_results(), ())

    def test_queue_is_bounded_and_keeps_latest_fifty(self):
        control = OperationControl()
        for i in range(80):
            control.report_file_result(str(i), f'{i}.mp4', 'ERROR', '오류')
        results = control.drain_file_results()
        self.assertEqual(len(results), 50)
        self.assertEqual(results[0].key, '30')

    def test_burst_does_not_lose_error_or_completed_ids(self):
        control = OperationControl()
        control.report_file_result('failed', 'bad.mp4', 'ERROR')
        for i in range(80):
            control.report_file_result(str(i), f'{i}.jpg', 'SUCCESS')
        control.drain_file_results()
        summary = control.result_summary()
        self.assertEqual(len(summary.completed_keys), 81)
        self.assertTrue(summary.had_error)
        self.assertEqual(summary.succeeded, 80)
        self.assertEqual(summary.failed, 1)


if __name__ == '__main__':
    unittest.main()
