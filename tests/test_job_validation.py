import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from photo_organizer.models import AppSettings, DeleteReviewItem, ExecutionBundle, ExecutionResult, MediaItem, OrganizeRequest


class JobValidationTests(unittest.TestCase):
    def setUp(self):
        from photo_organizer.engine import OrganizerEngine
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='job_validation_')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        source = self.base / 'source'
        source.mkdir()
        self.original = source / 'original.jpg'
        self.original.write_bytes(b'original')
        engine = OrganizerEngine(self.base)
        request = OrganizeRequest(source, self.base / 'target')
        media = MediaItem(self.original, 'photo', '.jpg', datetime(2024, 1, 1, 12), 'metadata', 'CAM', 'metadata')
        with patch.object(engine, '_scan_media_files', return_value=[self.original]), patch.object(engine.extractor, 'extract', return_value=media):
            preview = engine.preview(request)
        from photo_organizer.job_validation import capture_file_states
        self.job = SimpleNamespace(settings=AppSettings(source_path=str(source), target_path=str(request.target_path)),
                                   phase='PREVIEW_READY', preview_bundle=preview, execution_bundle=None,
                                   source_fingerprints=capture_file_states([self.original]), result_fingerprints={})
        self.item = preview.preview_items[0]

    def test_preview_baseline_and_lexical_validation(self):
        from photo_organizer.job_validation import validate_job_paths, validate_preview_files
        validate_job_paths(self.job)
        self.assertEqual(validate_preview_files(self.job), [])
        self.original.write_bytes(b'changed original')
        self.assertTrue(validate_preview_files(self.job))

    def test_missing_baseline_or_source_blocks(self):
        from photo_organizer.job_validation import validate_preview_files
        self.job.source_fingerprints = {}
        self.assertTrue(validate_preview_files(self.job))
        self.original.unlink()
        self.assertTrue(validate_preview_files(self.job))

    def test_existing_target_blocks_even_overwrite(self):
        from photo_organizer.job_validation import validate_preview_files
        target = Path(self.item.target_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'previous')
        self.item.write_mode = 'OVERWRITE'
        self.assertTrue(validate_preview_files(self.job))

    def test_existing_mobile_output_blocks(self):
        from photo_organizer.job_validation import validate_preview_files
        mobile = Path(self.item.mobile_output_path)
        mobile.parent.mkdir(parents=True)
        mobile.write_bytes(b'previous')
        self.assertTrue(validate_preview_files(self.job))

    def test_path_escape_bad_folder_filename_and_duplicate_id_rejected(self):
        from photo_organizer.job_validation import validate_job_paths
        from dataclasses import replace
        for change in ({'source_path': str(self.base / 'elsewhere.jpg')}, {'target_directory': str(self.base / 'target')},
                       {'new_filename': '../bad.jpg'}, {'mobile_output_path': str(self.base / 'bad.jpg')}):
            with self.subTest(change=change):
                self.job.preview_bundle.preview_items = [replace(self.item, **change)]
                with self.assertRaises(ValueError):
                    validate_job_paths(self.job)
        self.job.preview_bundle.preview_items = [self.item, replace(self.item)]
        with self.assertRaises(ValueError):
            validate_job_paths(self.job)

    def test_draft_allows_blank_paths(self):
        from photo_organizer.job_validation import validate_job_paths
        validate_job_paths(SimpleNamespace(settings=AppSettings(), phase='DRAFT', preview_bundle=None, execution_bundle=None))

    def test_delete_requires_success_copy_and_both_unchanged_fingerprints(self):
        from photo_organizer.job_validation import capture_file_states, validate_delete_candidate
        target = Path(self.item.target_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'original')
        self.job.execution_bundle = ExecutionBundle(preview_items=[self.item], execution_results=[ExecutionResult(str(self.original), str(target), 'SUCCESS', 'copy')])
        self.job.result_fingerprints = capture_file_states([target])
        review = DeleteReviewItem(self.item.item_id, str(self.original), 'copy', selected=False)
        self.assertEqual(validate_delete_candidate(self.job, review), [])
        self.job.execution_bundle.execution_results[0].action = 'move'
        self.assertTrue(validate_delete_candidate(self.job, review))
        self.job.execution_bundle.execution_results[0].action = 'copy'
        target.write_bytes(b'changed')
        self.assertTrue(validate_delete_candidate(self.job, review))

    def test_delete_mismatched_id_rejected(self):
        from photo_organizer.job_validation import validate_delete_candidate
        self.assertTrue(validate_delete_candidate(self.job, DeleteReviewItem('other', str(self.original), 'copy')))

    def test_linked_parent_rejected_without_reading_target(self):
        from photo_organizer.job_validation import validate_preview_files
        with patch('photo_organizer.job_validation._has_link_component', return_value=True):
            self.assertTrue(validate_preview_files(self.job))

    def test_loaded_path_validation_has_no_filesystem_reads(self):
        from photo_organizer.job_validation import validate_job_paths
        with patch.object(Path, 'stat', side_effect=AssertionError('stat during lexical validation')), \
             patch.object(Path, 'lstat', side_effect=AssertionError('lstat during lexical validation')):
            validate_job_paths(self.job)

    def test_unselected_source_changes_do_not_block_selected_execution(self):
        from photo_organizer.job_validation import validate_preview_files
        self.item.included = False
        self.original.unlink()
        self.assertEqual(validate_preview_files(self.job), [])

    def test_mapping_and_media_timestamp_tampering_rejected(self):
        from photo_organizer.job_validation import validate_job_paths
        self.job.settings.model_name_mappings = {'CAM': 'Other'}
        with self.assertRaises(ValueError):
            validate_job_paths(self.job)
        self.job.settings.model_name_mappings = {}
        self.job.preview_bundle.media_items[0].captured_at = datetime(2024, 2, 1)
        with self.assertRaises(ValueError):
            validate_job_paths(self.job)

    def test_optional_fingerprint_error_key_does_not_invalidate_file(self):
        from photo_organizer.job_validation import validate_preview_files
        self.job.source_fingerprints[str(self.original)]['error'] = ''
        self.assertEqual(validate_preview_files(self.job), [])

    def test_symbolic_link_source_or_ancestor_rejected(self):
        from photo_organizer.job_validation import validate_preview_files
        self.original.unlink()
        real = self.base / 'real.jpg'
        real.write_bytes(b'original')
        try:
            self.original.symlink_to(real)
        except OSError:
            self.skipTest('Windows symbolic link privilege unavailable')
        self.assertTrue(validate_preview_files(self.job))


if __name__ == '__main__':
    unittest.main()
