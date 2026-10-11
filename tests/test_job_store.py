import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.job_store import JobState, load_job, save_job
from photo_organizer.models import AppSettings
from photo_organizer.models import PreviewItem, PreviewBundle, MediaItem, ExecutionBundle, ExecutionResult, DeleteReviewItem
from datetime import datetime


class JobStoreTests(unittest.TestCase):
    def preview(self):
        source = str(self.path.parent / '원본.jpg')
        target = str(self.path.parent / '20240101_가족' / '내사진.jpg')
        row = PreviewItem('id1', 'photo', source, str(Path(target).parent), target, '내사진.jpg', 'NEW', '2024-01-01T12:00:00', 'EXIF', 'SM-F926N', 'EXIF', [], metadata_entries=[('모델', 'SM-F926N')], filename_edited=True, output_model_name='가족', folder_model_name='가족')
        class Opaque:
            def __deepcopy__(self, memo):
                raise RuntimeError('raw EXIF object must not be copied')
        media = MediaItem(Path(source), 'photo', '.jpg', captured_at=datetime(2024, 1, 1, 12), model_name='SM-F926N', metadata={'opaque': Opaque()})
        return PreviewBundle(preview_items=[row], media_items=[media])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '한글.pojob.json'
        self.validation = patch('photo_organizer.job_store._validate_paths')
        self.validation.start()
        self.addCleanup(self.validation.stop)

    def test_draft_roundtrip_and_success_revision(self):
        job = JobState(settings=AppSettings(device_name_override='가족'))
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertEqual(loaded.job_id, job.job_id)
        self.assertEqual(loaded.settings.device_name_override, '가족')
        self.assertEqual(job.revision, 1)
        self.assertTrue(loaded.saved_at_utc)

    def test_replace_failure_preserves_file_revision_and_timestamp(self):
        job = JobState()
        save_job(job, self.path)
        before = self.path.read_bytes()
        stamp = job.saved_at_utc
        with patch('photo_organizer.job_store.os.replace', side_effect=OSError('replace')):
            with self.assertRaises(OSError):
                save_job(job, self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(job.revision, 1)
        self.assertEqual(job.saved_at_utc, stamp)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_schema_phase_types_rejected(self):
        save_job(JobState(), self.path)
        base = json.loads(self.path.read_text(encoding='utf-8'))
        for field, value in [('schema_version', 3), ('schema_version', True), ('phase', 'DONE'), ('active_tab', True), ('execution_started', 'false'), ('revision', -1)]:
            with self.subTest(field=field, value=value):
                data = dict(base, **{field: value})
                self.path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_job(self.path)

    def test_missing_required_field_rejected(self):
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        del data['settings']['source_path']
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_size_limit_preserves_existing(self):
        save_job(JobState(), self.path)
        before = self.path.read_bytes()
        with patch('photo_organizer.job_store.MAX_JOB_BYTES', 1):
            with self.assertRaises(ValueError):
                load_job(self.path)
            with self.assertRaises(ValueError):
                save_job(JobState(), self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_preview_roundtrip_unicode_manual_media_and_raw_metadata_omitted(self):
        preview = self.preview()
        job = JobState(phase='PREVIEW_READY', preview_bundle=preview, settings=AppSettings(source_path=str(self.path.parent), target_path=str(self.path.parent / 'target'), model_name_mappings={'SM-F926N': '가족'}))
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertEqual(loaded.preview_bundle.preview_items, preview.preview_items)
        self.assertEqual(loaded.preview_bundle.media_items[0].captured_at, preview.media_items[0].captured_at)
        self.assertEqual(loaded.preview_bundle.media_items[0].metadata, {})
        self.assertEqual(loaded.settings.model_name_mappings, {'SM-F926N': '가족'})

    def test_results_roundtrip_and_delete_selection_cleared(self):
        preview = self.preview()
        row = preview.preview_items[0]
        execution = ExecutionBundle(preview_items=preview.preview_items, execution_results=[ExecutionResult(row.source_path, row.target_path, 'SUCCESS', 'copy', mobile_output_status='SIZE_EXCLUDED')], delete_review_items=[DeleteReviewItem(row.item_id, row.source_path, '복사 완료', True)])
        job = JobState(phase='EXECUTION_FINISHED', preview_bundle=preview, execution_bundle=execution, execution_started=True)
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertEqual(loaded.execution_bundle.execution_results, execution.execution_results)
        self.assertFalse(loaded.execution_bundle.delete_review_items[0].selected)
        self.assertTrue(job.execution_bundle.delete_review_items[0].selected)

    def test_stage_contradictions_cannot_save(self):
        preview = self.preview()
        jobs = [JobState(phase='PREVIEW_READY'), JobState(phase='DRAFT', preview_bundle=preview), JobState(phase='PREVIEW_READY', preview_bundle=preview, execution_started=True), JobState(phase='EXECUTION_FINISHED', preview_bundle=preview, execution_started=True, execution_bundle=ExecutionBundle())]
        for job in jobs:
            with self.subTest(phase=job.phase), self.assertRaises(ValueError):
                save_job(job, self.path)
        self.assertFalse(self.path.exists())

    def test_invalid_settings_types_and_values_rejected(self):
        save_job(JobState(), self.path)
        base = json.loads(self.path.read_text(encoding='utf-8'))
        for name, value in [('operation_mode', 'destroy'), ('mobile_output_enabled', 1), ('mobile_output_jpeg_quality', 101), ('mobile_output_limit_mb', 0), ('mobile_output_video_quality', 'random'), ('model_name_mappings', {'X': '../unsafe'})]:
            data = dict(base, settings=dict(base['settings'], **{name: value}))
            self.path.write_text(json.dumps(data), encoding='utf-8')
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_job(self.path)

    def test_video_original_width_zero_roundtrip(self):
        job = JobState(settings=AppSettings(mobile_output_video_max_width=0))
        save_job(job, self.path)
        self.assertEqual(load_job(self.path).settings.mobile_output_video_max_width, 0)

    def test_real_logical_path_validator_roundtrip_without_creating_media_paths(self):
        self.validation.stop()
        root = self.path.parent
        source = root / 'source' / '20240101_120000_X.jpg'
        target_root = root / 'target'
        directory = target_root / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
        filename = '20240101_120000_X_0001.jpg'
        row = PreviewItem('one', 'photo', str(source), str(directory), str(directory / filename), filename, 'NEW', '2024-01-01T12:00:00', '파일명 fallback', 'X', '파일명 fallback', [])
        media = MediaItem(source, 'photo', '.jpg', datetime(2024, 1, 1, 12), model_name='X')
        job = JobState(phase='PREVIEW_READY', settings=AppSettings(source_path=str(source.parent), target_path=str(target_root)), preview_bundle=PreviewBundle(preview_items=[row], media_items=[media]))
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertEqual(loaded.preview_bundle.preview_items, [row])
        self.assertFalse(source.parent.exists())
        self.assertFalse(target_root.exists())

    def test_old_optional_output_fields_use_defaults(self):
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        del data['settings']['mobile_output_limit_enabled']
        del data['settings']['mobile_output_limit_mb']
        self.path.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_job(self.path)
        self.assertFalse(loaded.settings.mobile_output_limit_enabled)
        self.assertEqual(loaded.settings.mobile_output_limit_mb, 500)

    def test_item_count_limit_and_future_unknown_field_rejected(self):
        preview = self.preview()
        with patch('photo_organizer.job_store.MAX_PREVIEW_ITEMS', 0), self.assertRaises(ValueError):
            save_job(JobState(phase='PREVIEW_READY', preview_bundle=preview), self.path)
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['future_execute_anything'] = True
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_duplicate_keys_and_duplicate_item_ids_rejected(self):
        self.path.write_text('{"format":"a","format":"b"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)
        preview = self.preview()
        preview.preview_items.append(preview.preview_items[0])
        with self.assertRaises(ValueError):
            save_job(JobState(phase='PREVIEW_READY', preview_bundle=preview), self.path)

    def test_fsync_failure_cleans_temp_and_keeps_old_revision(self):
        job = JobState()
        save_job(job, self.path)
        before = self.path.read_bytes()
        with patch('photo_organizer.job_store.os.fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                save_job(job, self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(job.revision, 1)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == '__main__':
    unittest.main()
