import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.models import AppSettings
from photo_organizer.execution_estimate import estimate_execution, remaining_estimate, EstimateHistory


def row(key, kind='photo', duration=None, included=True, output=True):
    return SimpleNamespace(item_id=key, source_path=key, media_type=kind, included=included,
                           mobile_output_enabled=output,
                           metadata_entries=[] if duration is None else [('Duration', duration)])


def bundle(*items):
    return SimpleNamespace(preview_items=list(items), media_items=[])


class ExecutionEstimateTests(unittest.TestCase):
    def estimate(self, rows, settings=None, **kwargs):
        return estimate_execution(rows, settings or AppSettings(), **kwargs)

    def test_selected_items_and_no_filesystem_reads(self):
        with patch.object(Path, 'stat', side_effect=AssertionError('unexpected filesystem read')):
            result = self.estimate(bundle(row('one'), row('excluded', included=False), row('video', 'video', '00:02:00')),
                                   source_fingerprints={'one': {'size': 1000000}, 'video': {'size': 50000000}})
        self.assertEqual((result.photo_count, result.video_count, result.item_count), (1, 1, 2))
        self.assertEqual({item.item_id for item in result.item_estimates}, {'one', 'video'})
        self.assertEqual(result.basis, '초기 추정')
        self.assertLess(result.lower_seconds, result.total_seconds)
        self.assertGreater(result.upper_seconds, result.total_seconds)

    def test_partial_legacy_preview_fixture_and_malformed_optional_metadata_are_safe(self):
        legacy = SimpleNamespace(preview_items=[SimpleNamespace(source_path='legacy.jpg', media_type='photo', metadata_entries=None)])
        self.assertEqual(self.estimate(legacy).item_count, 1)
        self.assertEqual(self.estimate(None).item_count, 0)

    def test_encoder_speed_workers_and_disabled_output_affect_work(self):
        video = bundle(row('video', 'video', '00:10:00'))
        cpu = self.estimate(video, AppSettings(video_encoder='cpu'))
        gpu = self.estimate(video, AppSettings(video_encoder='gpu'))
        fast = self.estimate(video, AppSettings(video_encoder='cpu', conversion_speed='fast'))
        quality = self.estimate(video, AppSettings(video_encoder='cpu', conversion_speed='quality'))
        copy_only = self.estimate(video, AppSettings(mobile_output_enabled=False))
        self.assertGreater(cpu.total_seconds, gpu.total_seconds)
        self.assertGreater(quality.total_seconds, fast.total_seconds)
        self.assertGreater(cpu.total_seconds, copy_only.total_seconds)
        photos = bundle(*(row(str(index)) for index in range(8)))
        self.assertGreater(self.estimate(photos, AppSettings(photo_workers=1)).total_seconds,
                           self.estimate(photos, AppSettings(photo_workers=4)).total_seconds)

    def test_raw_duration_and_saved_display_duration_are_supported(self):
        raw = bundle(row('video', 'video'))
        raw.media_items = [SimpleNamespace(source_path=Path('video'), metadata={'media_info': {'duration_seconds': '120'}})]
        self.assertAlmostEqual(self.estimate(raw).total_seconds,
                               self.estimate(bundle(row('video', 'video', '00:02:00'))).total_seconds)

    def test_history_profiles_separate_quality_resolution_and_photo_output_settings(self):
        rows = bundle(row('photo'), row('video', 'video', '00:02:00'))
        baseline = self.estimate(rows)
        for changes in ({'mobile_output_video_quality': 'very_high'}, {'mobile_output_video_max_width': 1920},
                        {'mobile_output_max_width': 1200}, {'mobile_output_jpeg_quality': 95}):
            self.assertNotEqual(baseline.profile, self.estimate(rows, AppSettings(**changes)).profile)

    def test_known_source_pixels_and_output_width_adjust_video_work(self):
        def measured(width, height, max_width):
            data = bundle(row('video', 'video', '00:02:00'))
            data.media_items = [SimpleNamespace(source_path=Path('video'), metadata={'media_info': {
                'duration_seconds': '120', 'width': width, 'height': height}})]
            return self.estimate(data, AppSettings(mobile_output_video_max_width=max_width),
                                 source_fingerprints={'video': {'size': 10000000}})
        hd = measured(1920, 1080, 1920)
        uhd = measured(3840, 2160, 0)
        reduced = measured(3840, 2160, 1280)
        self.assertGreater(uhd.total_seconds, hd.total_seconds)
        self.assertGreater(uhd.total_seconds, reduced.total_seconds)
        self.assertEqual(hd.missing_data_count, 0)

    def test_missing_duration_and_size_produce_finite_wide_initial_range(self):
        result = self.estimate(bundle(row('video', 'video')))
        self.assertGreater(result.missing_data_count, 0)
        self.assertTrue(math.isfinite(result.upper_seconds))
        self.assertGreaterEqual(result.upper_seconds / result.lower_seconds, 4)
        empty = self.estimate(bundle())
        self.assertEqual((empty.total_seconds, empty.lower_seconds, empty.upper_seconds), (0, 0, 0))

    def test_ledger_done_stages_are_excluded_and_explicit_item_filter_is_used(self):
        ledger = {'one': {'main': {'state': 'DONE'}, 'output': {'state': 'DONE'}, 'source_remove': {'state': 'NOT_REQUIRED'}}}
        result = self.estimate(bundle(row('one'), row('two')), ledger=ledger, item_ids={'one'})
        self.assertEqual(result.total_seconds, 0)
        self.assertEqual(result.item_count, 0)

    def test_remaining_uses_work_weights_and_completed_ids(self):
        estimate = self.estimate(bundle(row('photo'), row('video', 'video', '00:10:00')))
        photo_done = remaining_estimate(estimate, 1, {'photo'})
        video_done = remaining_estimate(estimate, 120, {'video'})
        self.assertGreater(photo_done.total_seconds, video_done.total_seconds)
        paused = remaining_estimate(estimate, 1, {'photo'}, paused=True)
        self.assertTrue(paused.paused)
        self.assertEqual(paused.total_seconds, photo_done.total_seconds)
        complete = remaining_estimate(estimate, 300, {'photo', 'video'})
        self.assertEqual((complete.total_seconds, complete.lower_seconds, complete.upper_seconds), (0, 0, 0))

    def test_first_long_video_initial_eta_decreases_and_overrun_is_explicit(self):
        estimate = self.estimate(bundle(row('video', 'video', '00:10:00')))
        start = remaining_estimate(estimate, 0)
        halfway = remaining_estimate(estimate, estimate.total_seconds / 2)
        self.assertEqual(start.total_seconds, estimate.total_seconds)
        self.assertAlmostEqual(halfway.total_seconds, estimate.total_seconds / 2)
        self.assertAlmostEqual(halfway.upper_seconds, estimate.upper_seconds - estimate.total_seconds / 2)
        overrun = remaining_estimate(estimate, estimate.upper_seconds + 1)
        self.assertEqual((overrun.total_seconds, overrun.lower_seconds, overrun.upper_seconds), (0, 0, 0))
        self.assertEqual(overrun.basis, '초기 예상 초과')
        self.assertEqual(overrun.remaining_count, 1)

    def test_history_calibrates_without_compounding_and_roundtrips(self):
        initial = self.estimate(bundle(row('video', 'video', '00:10:00')))
        history = EstimateHistory()
        self.assertFalse(history.record(initial, 100, completed=False))
        self.assertFalse(history.record(initial, float('nan')))
        self.assertTrue(history.record(initial, initial.total_seconds * 2))
        calibrated = self.estimate(bundle(row('video', 'video', '00:10:00')), history=history)
        self.assertEqual(calibrated.basis, '처리 이력 보정')
        self.assertAlmostEqual(calibrated.total_seconds, initial.total_seconds * 2)
        history.record(calibrated, initial.total_seconds * 2)
        self.assertAlmostEqual(self.estimate(bundle(row('video', 'video', '00:10:00')), history=history).total_seconds,
                               initial.total_seconds * 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            self.assertTrue(history.save(path))
            loaded = EstimateHistory.load(path)
            self.assertAlmostEqual(loaded.factor(initial.profile), 2)

    def test_history_rejects_future_corrupt_oversized_data_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            for text in ('{invalid', json.dumps({'version': 3, 'profiles': {}}), ' ' * 65537,
                         json.dumps({'version': 2, 'profiles': {'cpu|balanced|1|1|balanced|1280|3000|75': {'factor': '2', 'samples': 1}}})):
                path.write_text(text, encoding='utf-8')
                self.assertEqual(EstimateHistory.load(path).factor('unknown'), 1)
            path.write_text('original', encoding='utf-8')
            with patch('photo_organizer.execution_estimate.os.replace', side_effect=OSError('failure')):
                self.assertFalse(EstimateHistory().save(path))
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')


if __name__ == '__main__':
    unittest.main()
