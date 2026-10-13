import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.execution_estimate import estimate_execution, EstimateHistory


class VideoEstimateTests(unittest.TestCase):
    def estimate(self, workers=1, history=None):
        rows = [SimpleNamespace(item_id=str(index), source_path=str(index), media_type='video',
                                included=True, mobile_output_enabled=True,
                                metadata_entries=[('Duration', '00:02:00')]) for index in range(2)]
        settings = SimpleNamespace(video_workers=workers, mobile_output_enabled=True)
        return estimate_execution(SimpleNamespace(preview_items=rows), settings, history=history)

    def test_parallel_profile_is_separate_without_assuming_twice_the_speed(self):
        single, parallel = self.estimate(1), self.estimate(2)
        self.assertNotEqual(single.profile, parallel.profile)
        self.assertEqual(single.raw_seconds, parallel.raw_seconds)
        self.assertTrue(any('동영상 2개' in note for note in parallel.notes))

    def test_single_worker_history_does_not_calibrate_parallel_profile(self):
        history = EstimateHistory()
        single = self.estimate(1)
        history.record(single, single.raw_seconds * 2)
        self.assertNotEqual(self.estimate(1, history).total_seconds, self.estimate(2, history).total_seconds)

    def test_invalid_or_missing_video_workers_use_single_profile(self):
        for invalid in (None, True, 0, 3, '2'):
            self.assertEqual(self.estimate(invalid).profile, self.estimate(1).profile)

    def test_history_roundtrip_retains_both_worker_profiles(self):
        history = EstimateHistory()
        for workers in (1, 2):
            estimate = self.estimate(workers)
            history.record(estimate, estimate.raw_seconds * workers)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.json'
            self.assertTrue(history.save(path))
            loaded = EstimateHistory.load(path)
        for workers in (1, 2):
            self.assertTrue(loaded.has_samples(self.estimate(workers).profile))
            self.assertEqual(loaded.factor(self.estimate(workers).profile), workers)

    def test_profile_validation_accepts_only_the_supported_parallel_suffix(self):
        from photo_organizer.execution_estimate import _valid_profile
        baseline = self.estimate(1).profile
        self.assertTrue(_valid_profile(baseline + '|video_workers=2'))
        for suffix in ('video_workers=3', 'video_workers=true', 'video_workers=1', '2', ''):
            self.assertFalse(_valid_profile(baseline + '|' + suffix))


if __name__ == '__main__':
    unittest.main()
