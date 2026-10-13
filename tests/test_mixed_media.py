import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_parallel_videos as video_tests
from photo_organizer.models import AppSettings
from photo_organizer.resume_models import processing_settings
from photo_organizer.execution_estimate import estimate_execution, EstimateHistory, _valid_profile
from photo_organizer.config import ConfigManager
from photo_organizer.job_store import save_job, load_job
from photo_organizer.execution_journal import ExecutionJournal


class MixedMediaTests(unittest.TestCase):
    setUp = video_tests.ParallelVideoTests.setUp
    convert = staticmethod(video_tests.ParallelVideoTests.convert)
    def add_photos(self):
        import copy
        for i in range(2):
            item = copy.deepcopy(self.items[i])
            item.item_id = f'photo{i}'
            item.media_type = 'photo'
            for attr in ('source_path', 'target_path', 'new_filename', 'mobile_output_path'):
                setattr(item, attr, getattr(item, attr).replace('.mp4', '.jpg'))
            Path(item.source_path).write_bytes(b'photo')
            self.items.append(item)
            self.sources.append(Path(item.source_path))
        from photo_organizer.job_validation import capture_file_states
        self.job.source_fingerprints = capture_file_states(self.sources)

    def test_mixed_launches_four_actual_workers_with_separate_limits(self):
        self.add_photos()
        self.job.settings.mixed_media_workers = True
        both = threading.Barrier(4)
        observed = []
        control = __import__('photo_organizer.operation_control', fromlist=['OperationControl']).OperationControl()
        def convert(source, target, media_type, request):
            both.wait(10)
            observed.append(tuple(a.stage for a in control.activity_snapshot()))
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial', control=control)
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS'] * 4)
        self.assertTrue(any(len(snapshot) == 4 for snapshot in observed))
        self.assertEqual([r.source_path for r in result.execution_results], list(map(str, self.sources)))

    def test_defaults_signature_and_history_preserve_old_projection(self):
        self.assertFalse(AppSettings().mixed_media_workers)
        self.assertNotIn('mixed_media_workers', processing_settings(self.job.settings))
        original = estimate_execution(self.job.preview_bundle, self.job.settings)
        self.job.settings.mixed_media_workers = True
        mixed = estimate_execution(self.job.preview_bundle, self.job.settings)
        self.assertEqual(mixed.profile, original.profile + '|mixed_media_workers=true')
        self.assertTrue(_valid_profile(mixed.profile))
        self.assertFalse(_valid_profile(original.profile + '|mixed_media_workers=false'))
        history = EstimateHistory()
        self.assertTrue(history.record(mixed, mixed.total_seconds))
        path = self.base / 'history.json'
        self.assertTrue(history.save(path))
        self.assertTrue(EstimateHistory.load(path).has_samples(mixed.profile))

    def test_mixed_preference_config_and_job_roundtrip_strict_bool(self):
        self.job.settings.mixed_media_workers = True
        config = ConfigManager(self.base)
        config.save(self.job.settings)
        self.assertTrue(config.load().mixed_media_workers)
        path = self.base / 'saved.pojob.json'
        save_job(self.job, path)
        self.assertTrue(load_job(path).settings.mixed_media_workers)
        self.job.settings.mixed_media_workers = 1
        with self.assertRaises(ValueError):
            save_job(self.job, path)

    def add_third_photo(self):
        import copy
        item = copy.deepcopy(self.items[-1])
        item.item_id = 'photo2'
        item.source_path = str(Path(item.source_path).with_name('20240101_120002_CAM.jpg'))
        item.captured_at = '2024-01-01T12:00:02'
        item.new_filename = '20240101_120002_CAM_0003.jpg'
        item.target_path = str(Path(item.target_path).with_name(item.new_filename))
        item.mobile_output_path = str(Path(item.mobile_output_path).with_name(item.new_filename))
        Path(item.source_path).write_bytes(b'third photo')
        self.items.append(item)
        self.sources.append(Path(item.source_path))
        from photo_organizer.job_validation import capture_file_states
        self.job.source_fingerprints = capture_file_states(self.sources)

    def test_photo_slots_refill_before_long_videos_finish(self):
        self.add_photos()
        self.add_third_photo()
        self.job.settings.mixed_media_workers = True
        third_started = threading.Event()
        initial = threading.Barrier(4)
        def convert(source, target, media_type, request):
            if source.name == self.items[-1].new_filename:
                third_started.set()
            else:
                initial.wait(10)
                if media_type == 'video':
                    self.assertTrue(third_started.wait(10), 'photo slot was not refilled while videos ran')
            return self.convert(source, target, media_type, request)
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial')
        self.assertTrue(third_started.is_set())
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS'] * 5)

    def test_mixed_stop_drains_canceled_items_and_preserves_unscheduled_tail(self):
        from photo_organizer.operation_control import OperationControl
        self.add_photos()
        self.add_third_photo()
        self.job.settings.mixed_media_workers = True
        control = OperationControl()
        initial = threading.Barrier(4)
        def convert(source, target, media_type, request):
            initial.wait(10)
            control.request_stop()
            control.raise_if_interrupted()
        with patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            result = self.engine.resume(self.job, 'initial', control=control)
        self.assertEqual(result.execution_results, [])
        self.assertEqual(control.result_summary().completed_keys, frozenset())
        self.assertEqual(self.job.ledger[self.items[-1].item_id]['main']['state'], 'PENDING')
        self.assertTrue(all(p.exists() for p in self.sources))
        with patch.object(self.engine, '_create_mobile_output', side_effect=self.convert):
            result = self.engine.resume(self.job, 'continue')
        self.assertEqual([r.status for r in result.execution_results], ['SUCCESS'] * 5)
        self.assertEqual([r.source_path for r in result.execution_results], list(map(str, self.sources)))

    def test_output_failure_stops_refill_and_drains_running_items(self):
        self.add_photos()
        self.add_third_photo()
        self.job.settings.mixed_media_workers = True
        initial = threading.Barrier(4)
        failed = threading.Event()
        original = ExecutionJournal.update
        def update(journal, job, item_id, stage, record):
            result = original(journal, job, item_id, stage, record)
            if stage == 'output' and record['state'] == 'FAILED':
                failed.set()
            return result
        def convert(source, target, media_type, request):
            initial.wait(10)
            if source.name == self.items[0].new_filename:
                raise RuntimeError('controlled output failure')
            self.assertTrue(failed.wait(10))
            return self.convert(source, target, media_type, request)
        with patch.object(ExecutionJournal, 'update', update), patch.object(self.engine, '_create_mobile_output', side_effect=convert):
            self.engine.resume(self.job, 'initial')
        self.assertEqual(self.job.ledger[self.items[-1].item_id]['main']['state'], 'PENDING')
        self.assertFalse(Path(self.items[-1].target_path).exists())
        self.assertTrue(all(p.exists() for p in self.sources))
        self.assertTrue(all(self.job.ledger[item.item_id]['output']['state'] == 'DONE' for item in self.items[1:4]))

    def test_history_mixed_suffix_rejects_duplicates_and_invalid_order(self):
        base = estimate_execution(self.job.preview_bundle, self.job.settings).profile
        for suffix in ('|mixed_media_workers=1', '|mixed_media_workers=true|mixed_media_workers=true',
                       '|mixed_media_workers=true|video_workers=2'):
            self.assertFalse(_valid_profile(base + suffix))
        self.job.settings.video_workers = 1
        self.job.settings.mixed_media_workers = True
        profile = estimate_execution(self.job.preview_bundle, self.job.settings).profile
        self.assertTrue(_valid_profile(profile))

    def test_old_job_without_mixed_field_keeps_signature_and_tamper_is_rejected(self):
        import json
        path = self.base / 'old.pojob.json'
        save_job(self.job, path)
        data = json.loads(path.read_text(encoding='utf-8'))
        original_signature = data['plan_signature']
        del data['settings']['mixed_media_workers']
        path.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_job(path)
        self.assertFalse(loaded.settings.mixed_media_workers)
        self.assertEqual(loaded.plan_signature, original_signature)
        data['settings']['mixed_media_workers'] = True
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(path)

    def test_invalid_config_mixed_value_normalizes_to_safe_default(self):
        manager = ConfigManager(self.base)
        manager.save(self.job.settings)
        manager.config_path.write_text('[app]\nmixed_media_workers = 1\nvideo_workers = 2\n', encoding='utf-8')
        settings = manager.load()
        self.assertFalse(settings.mixed_media_workers)
        self.assertEqual(settings.video_workers, 2)


if __name__ == '__main__':
    unittest.main()
