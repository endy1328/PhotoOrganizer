import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import AppSettings, MediaItem, OrganizeRequest
from photo_organizer.job_store import JobState, load_job, save_job
from photo_organizer.resume_models import canonical_plan, ensure_plan


class FileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.request = OrganizeRequest(self.source, self.base / 'target', mobile_output_enabled=False)
        self.engine = OrganizerEngine(self.base)
        self.media = []
        for index, model in enumerate(('A', 'A', 'B')):
            path = self.source / f'{index}.jpg'
            path.write_bytes(b'original')
            self.media.append(MediaItem(path, 'photo', '.jpg', datetime(2024, 1, 1, 12, index), '사진 메타', model, '사진 메타'))
        with patch.object(self.engine.extractor, 'extract', side_effect=self.media):
            self.bundle = self.engine.preview(self.request)

    def job(self):
        return JobState(phase='PREVIEW_READY', preview_bundle=self.bundle,
                        settings=AppSettings(source_path=str(self.source), target_path=str(self.request.target_path), mobile_output_enabled=False))

    def test_file_exclusion_survives_model_off_on_and_resequences(self):
        first = self.bundle.preview_items[0]
        self.engine.set_selected_files(self.bundle, {first.item_id}, False)
        self.assertEqual(self.bundle.selected_models, ['A', 'B'])
        self.assertEqual([row.included for row in self.bundle.preview_items], [False, True, True])
        self.assertTrue(self.bundle.preview_items[1].new_filename.endswith('_0001.jpg'))
        self.engine.set_selected_models(self.bundle, {'B'})
        self.engine.set_selected_models(self.bundle, {'A', 'B'})
        self.assertFalse(self.bundle.preview_items[0].file_selected)
        self.assertFalse(self.bundle.preview_items[0].included)
        self.engine.set_selected_files(self.bundle, {first.item_id}, True)
        self.assertTrue(all(row.included for row in self.bundle.preview_items))

    def test_all_files_of_model_excluded_does_not_clear_model_selection(self):
        ids = {row.item_id for row in self.bundle.preview_items if row.model_name == 'A'}
        self.engine.set_selected_files(self.bundle, ids, False)
        self.assertEqual(self.bundle.selected_models, ['A', 'B'])
        self.engine.set_selected_files(self.bundle, ids, True)
        self.assertTrue(all(row.included for row in self.bundle.preview_items))

    def test_manual_name_survives_exclusion_and_restore(self):
        row = self.bundle.preview_items[0]
        self.engine.edit_preview_filename(self.bundle, row.item_id, 'custom.jpg')
        self.engine.set_selected_files(self.bundle, {row.item_id}, False)
        self.engine.set_selected_models(self.bundle, {'B'})
        self.engine.set_selected_files(self.bundle, {row.item_id}, True)
        self.assertFalse(self.bundle.preview_items[0].included)
        self.engine.set_selected_models(self.bundle, {'A', 'B'})
        self.assertEqual(self.bundle.preview_items[0].new_filename, 'custom.jpg')

    def test_unknown_id_rejected_without_mutation_and_execute_skips_file(self):
        with self.assertRaises(ValueError):
            self.engine.set_selected_files(self.bundle, {'missing'}, False)
        row = self.bundle.preview_items[0]
        self.engine.set_selected_files(self.bundle, {row.item_id}, False)
        self.request.operation_mode = 'move'
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(len(result.execution_results), 2)
        self.assertTrue(Path(row.source_path).exists())
        self.assertFalse(Path(row.target_path).exists())

    def test_roundtrip_and_old_job_defaults_preserve_model_exclusion(self):
        self.engine.set_selected_models(self.bundle, {'B'})
        self.engine.set_selected_files(self.bundle, {self.bundle.preview_items[0].item_id}, False)
        job, path = self.job(), self.base / 'job.json'
        save_job(job, path)
        loaded = load_job(path)
        self.assertFalse(loaded.preview_bundle.preview_items[0].file_selected)
        self.assertEqual(loaded.preview_bundle.selected_models, ['B'])
        # Make a valid pre-feature schema 2 fixture with its original signature.
        for row in self.bundle.preview_items:
            row.file_selected = True
        ensure_plan(job, force=True)
        save_job(job, path)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['preview_bundle'].pop('selected_models')
        for row in data['preview_bundle']['preview_items']:
            row.pop('file_selected')
        path.write_text(json.dumps(data), encoding='utf-8')
        old = load_job(path)
        self.assertTrue(all(row.file_selected for row in old.preview_bundle.preview_items))
        self.engine.set_selected_files(old.preview_bundle, {old.preview_bundle.preview_items[0].item_id}, False)
        self.assertEqual(old.preview_bundle.selected_models, ['B'])
        self.assertFalse(old.preview_bundle.preview_items[1].included)

    def test_old_plan_signature_unchanged_and_new_hidden_selection_frozen(self):
        job = self.job()
        before = canonical_plan(job)
        self.engine.set_selected_models(self.bundle, {'A', 'B'})
        self.assertEqual(canonical_plan(job), before)
        self.engine.set_selected_models(self.bundle, {'B'})
        ensure_plan(job)
        job.execution_started = True
        self.engine.set_selected_files(self.bundle, {self.bundle.preview_items[0].item_id}, False)
        with self.assertRaises(ValueError):
            ensure_plan(job)

    def test_metadata_refresh_updates_inference_and_preserves_selection_names(self):
        video_path = self.source / 'video.mp4'
        video_path.write_bytes(b'video')
        video = MediaItem(video_path, 'video', '.mp4', datetime(2024, 1, 1, 12, 0, 20), '영상 메타')
        media = [*self.media, video]
        with patch.object(self.engine.extractor, 'extract', side_effect=media):
            self.bundle = self.engine.preview(self.request)
        self.assertEqual(next(row for row in self.bundle.preview_items if row.media_type == 'video').model_name, 'A')
        row = self.bundle.preview_items[0]
        self.engine.edit_preview_filename(self.bundle, row.item_id, 'custom.jpg')
        self.engine.set_selected_files(self.bundle, {row.item_id}, False)
        self.engine.set_selected_models(self.bundle, {'A'})
        fresh = {item.source_path: replace(item, model_name='C' if item.source_path == Path(row.source_path) else item.model_name,
                                          warnings=list(item.warnings), metadata={}) for item in media}
        fresh[video_path] = replace(video, model_name=None, model_source='UNKNOWN', metadata={})
        with patch.object(self.engine.extractor, 'extract', side_effect=lambda path: fresh[path]):
            self.engine.refresh_preview_after_metadata(self.bundle, self.request, row.source_path)
        changed = next(item for item in self.bundle.preview_items if item.item_id == row.item_id)
        inferred = next(item for item in self.bundle.preview_items if item.media_type == 'video')
        self.assertEqual(inferred.model_name, 'C')
        self.assertFalse(changed.file_selected)
        self.assertFalse(changed.included)
        self.assertEqual(changed.new_filename, 'custom.jpg')
        self.assertIn('C', self.bundle.selected_models)
        self.assertNotIn('B', self.bundle.selected_models)
        self.assertIn('C', changed.target_directory)

    def test_metadata_refresh_failure_preserves_bundle(self):
        before = list(self.bundle.preview_items)
        with patch.object(self.engine.extractor, 'extract', side_effect=OSError('read failed')):
            with self.assertRaises(ValueError):
                self.engine.refresh_preview_after_metadata(self.bundle, self.request, self.media[0].source_path)
        self.assertEqual(self.bundle.preview_items, before)

    def test_job_rejects_individually_excluded_but_included_row_even_legacy_filter(self):
        job, path = self.job(), self.base / 'job.json'
        save_job(job, path)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['preview_bundle']['selected_models'] = None
        data['preview_bundle']['preview_items'][0]['file_selected'] = False
        # Remove signature to isolate structural selection validation.
        data['plan_signature'] = ''
        data['plan_id'] = ''
        path.write_text(json.dumps(data), encoding='utf-8')
        from photo_organizer.job_store import _bundle
        with self.assertRaisesRegex(ValueError, '개별'):
            _bundle(data['preview_bundle'])

    def test_metadata_refresh_without_media_records_rereads_saved_rows(self):
        self.bundle.media_items = []
        fresh = {item.source_path: replace(item, model_name='C' if item == self.media[0] else item.model_name)
                 for item in self.media}
        with patch.object(self.engine.extractor, 'extract', side_effect=lambda path: fresh[path]):
            self.engine.refresh_preview_after_metadata(self.bundle, self.request, self.media[0].source_path)
        self.assertEqual(self.bundle.preview_items[0].model_name, 'C')
        self.assertEqual(len(self.bundle.media_items), 3)

    def test_owned_metadata_storage_media_excluded_but_unowned_folder_kept(self):
        from photo_organizer.metadata_writer import OWNER, STORAGE_NAME
        owned = self.source / STORAGE_NAME
        owned.mkdir()
        (owned / 'stage.jpg').write_bytes(b'stage')
        nested = owned / 'nested'
        nested.mkdir()
        (nested / 'another.mp4').write_bytes(b'stage')
        self.assertIn(owned / 'stage.jpg', self.engine._scan_media_files(self.source))
        (owned / 'owner.json').write_text(json.dumps(OWNER), encoding='utf-8')
        self.assertEqual(self.engine._scan_media_files(self.source), [item.source_path for item in self.media])


class FileSelectionPanelTests(unittest.TestCase):
    def test_independent_model_state_shown_when_all_rows_individually_excluded(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from photo_organizer.ui.model_selection import ModelSelectionPanel
        from types import SimpleNamespace
        app = QApplication.instance() or QApplication([])
        panel = ModelSelectionPanel()
        try:
            rows = [SimpleNamespace(model_name='A', output_model_name='', media_type='photo', included=False)]
            panel.set_items(rows, ['A'])
            self.assertEqual(panel.selected_models(), {'A'})
            panel.refresh(rows, ['A'])
            self.assertEqual(panel.selected_models(), {'A'})
            self.assertIn('처리 0건', panel.summary_label.text())
        finally:
            panel.close()


if __name__ == '__main__':
    unittest.main()
