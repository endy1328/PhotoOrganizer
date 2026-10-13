import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_organizer.models import AppSettings
from photo_organizer.performance_benchmark import BenchmarkCase, recommend, run_benchmark
from photo_organizer.operation_control import OperationControl, OperationInterrupted


class PerformanceBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.encoder = patch('photo_organizer.performance_benchmark.resolve_video_encoder', return_value='cpu')
        self.encoder.start()
        self.addCleanup(self.encoder.stop)

    def test_recommend_only_successful_meaningful_speedup(self):
        cases = (BenchmarkCase('video_serial', 10, True), BenchmarkCase('video_parallel', 8, True),
                 BenchmarkCase('mixed_serial', 12, True), BenchmarkCase('mixed_parallel', 11.5, True))
        self.assertEqual(recommend(cases), (2, False))
        self.assertEqual(recommend((cases[0], BenchmarkCase('video_parallel', 4, False, 'failure'))), (1, False))

    def test_same_work_and_private_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            source.mkdir(); target.mkdir()
            video = source / 'sample.mp4'; video.write_bytes(b'video')
            photo = source / 'sample.jpg'; photo.write_bytes(b'photo')
            existing = target / 'existing.mp4'; existing.write_bytes(b'keep')
            calls = []
            def encode(src, dst, *args, **kwargs):
                calls.append(('video', src, dst, kwargs))
                dst.write_bytes(b'output')
                return 'SUCCESS'
            def convert_photo(src, dst, settings):
                calls.append(('photo', src, dst, {}))
                dst.write_bytes(b'output')
            with patch('photo_organizer.performance_benchmark.create_mobile_video_output', side_effect=encode), \
                 patch('photo_organizer.performance_benchmark._photo', side_effect=convert_photo):
                report = run_benchmark(AppSettings(), source, target)
            self.assertEqual(len(report.cases), 4)
            self.assertTrue(all(case.success for case in report.cases))
            self.assertEqual(sum(call[0] == 'video' for call in calls), 8)
            self.assertEqual(sum(call[0] == 'photo' for call in calls), 8)
            self.assertTrue(all(call[3]['clip_seconds'] == 10 for call in calls if call[0] == 'video'))
            self.assertEqual(list(target.iterdir()), [existing])
            self.assertEqual(video.read_bytes(), b'video')

    def test_missing_video_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, '동영상'):
                run_benchmark(AppSettings(), Path(directory), Path(directory))

    def test_cancel_cleans_private_targets_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'sample.mp4'; video.write_bytes(b'original')
            control = OperationControl()
            def cancel(src, dst, *args, **kwargs):
                dst.write_bytes(b'partial')
                control.request_stop()
                control.raise_if_interrupted()
            with patch('photo_organizer.performance_benchmark.create_mobile_video_output', side_effect=cancel):
                with self.assertRaises(OperationInterrupted):
                    run_benchmark(AppSettings(), root, root, video_path=video, control=control)
            self.assertEqual(list(root.iterdir()), [video])
            self.assertEqual(video.read_bytes(), b'original')

    def test_no_photo_only_tests_video_and_failed_trial_does_not_recommend_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'sample.mp4'; video.write_bytes(b'original')
            with patch('photo_organizer.performance_benchmark.create_mobile_video_output', side_effect=RuntimeError('encoder failure')):
                report = run_benchmark(AppSettings(), root, root, video_path=video)
            self.assertEqual(len(report.cases), 2)
            self.assertTrue(all(not case.success and 'encoder failure' in case.error for case in report.cases))
            self.assertEqual((report.video_workers, report.mixed_media_workers), (1, False))
            self.assertTrue(any('사진 샘플' in note for note in report.notes))
