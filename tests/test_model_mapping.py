import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class MappingValidationTests(unittest.TestCase):
    def test_valid_unicode_alias_and_multiple_sources_to_same_alias(self):
        from photo_organizer.model_mapping import validate_model_mapping_rows
        self.assertEqual(validate_model_mapping_rows([("SM-F956N", "내 폴드6"), ("Galaxy Z Fold6", "내 폴드6")]),
                         {"SM-F956N": "내_폴드6", "Galaxy Z Fold6": "내_폴드6"})

    def test_invalid_names_and_duplicate_originals_are_rejected(self):
        from photo_organizer.model_mapping import validate_model_mapping_rows
        for value in ("", "../Action4", "A/B", "CON", "NUL.txt", "Action4.", "a\nB", "A?B", "x" * 256):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_model_mapping_rows([("DJI_OsmoAction4", value)])
        with self.assertRaises(ValueError):
            validate_model_mapping_rows([("Galaxy Z Fold6", "A"), ("galaxy_z_fold6", "B")])

    def test_matching_is_normalized_but_aliases_are_not_chained(self):
        from photo_organizer.model_mapping import resolve_output_model_name
        mappings = {"Galaxy Z Fold6": "Fold6", "Fold6": "Another"}
        self.assertEqual(resolve_output_model_name("Galaxy_Z_Fold6", mappings), "Fold6")
        self.assertEqual(resolve_output_model_name("SM-F926N", mappings), "SM-F926N")
        self.assertEqual(resolve_output_model_name("UNKNOWN", {"UNKNOWN": "Unidentified"}), "Unidentified")

    def test_empty_dict_rows_are_invalid_but_blank_editor_rows_are_ignored(self):
        from photo_organizer.model_mapping import validate_model_mappings, validate_model_mapping_rows
        with self.assertRaises(ValueError):
            validate_model_mappings({"": ""})
        self.assertEqual(validate_model_mapping_rows([("", "")]), {})

    def test_noncanonical_original_is_preserved_without_mapping(self):
        from photo_organizer.model_mapping import resolve_output_model_name
        self.assertEqual(resolve_output_model_name("--", {}), "--")
        self.assertEqual(resolve_output_model_name("_", {"CAM_A": "Action4"}), "_")


class MappingEngineTests(unittest.TestCase):
    def setUp(self):
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import MediaItem, OrganizeRequest
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix="mapping_test_")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.engine = OrganizerEngine(self.base)
        self.request = OrganizeRequest(self.source, self.base / "target", mobile_output_enabled=True)
        self.media = []
        for index, model in enumerate(("CAM_A", "CAM_B", "UNKNOWN")):
            source = self.source / f"{index}.jpg"
            source.write_bytes(b"original")
            self.media.append(MediaItem(source, "photo", ".jpg", datetime(2024, 1, 1, 12, index),
                                        "사진 메타", model, "사진 메타"))

    def preview(self, mappings, scope="filename_and_folders"):
        self.request.model_name_mappings = mappings
        self.request.model_mapping_scope = scope
        with patch.object(self.engine, "_scan_media_files", return_value=[item.source_path for item in self.media]), \
             patch.object(self.engine.extractor, "extract", side_effect=self.media):
            return self.engine.preview(self.request)

    def test_default_maps_names_and_both_folders_without_changing_original(self):
        bundle = self.preview({"CAM_A": "Action4"})
        item = bundle.preview_items[0]
        self.assertEqual(item.model_name, "CAM_A")
        self.assertEqual(item.output_model_name, "Action4")
        self.assertEqual(item.folder_model_name, "Action4")
        self.assertEqual(Path(item.target_directory).name, "20240101_Action4")
        self.assertIn("_Action4_0001.jpg", item.new_filename)
        self.assertEqual(Path(item.mobile_output_path).parent.name, "output_20240101_Action4")
        self.assertEqual(self.media[0].model_name, "CAM_A")
        entries = dict(item.metadata_entries)
        self.assertEqual(entries["추출 모델명"], "CAM_A")
        self.assertEqual(entries["파일명 적용 모델명"], "Action4")

    def test_filename_only_keeps_original_folder_and_output_folder(self):
        item = self.preview({"CAM_A": "Action4"}, "filename_only").preview_items[0]
        self.assertEqual(Path(item.target_directory).name, "20240101_CAM_A")
        self.assertEqual(Path(item.mobile_output_path).parent.name, "output_20240101_CAM_A")
        self.assertIn("_Action4_0001.jpg", item.new_filename)
        self.assertEqual(item.folder_model_name, "CAM_A")

    def test_many_models_to_one_alias_share_date_sequences_and_select_by_original(self):
        bundle = self.preview({"CAM_A": "Same", "CAM_B": "Same"})
        first, second = bundle.preview_items[:2]
        self.assertEqual(first.target_directory, second.target_directory)
        self.assertTrue(first.new_filename.endswith("_Same_0001.jpg"))
        self.assertTrue(second.new_filename.endswith("_Same_0002.jpg"))
        self.engine.set_selected_models(bundle, {"CAM_B"})
        self.assertFalse(bundle.preview_items[0].included)
        self.assertTrue(bundle.preview_items[1].new_filename.endswith("_Same_0001.jpg"))

    def test_unicode_alias_is_preserved_in_paths(self):
        item = self.preview({"CAM_A": "내 카메라"}).preview_items[0]
        self.assertEqual(Path(item.target_directory).name, "20240101_내_카메라")
        self.assertIn("_내_카메라_0001.jpg", item.new_filename)

    def test_manual_filename_survives_reselection_in_mapped_folder(self):
        bundle = self.preview({"CAM_A": "Action4"})
        item = bundle.preview_items[0]
        folder = item.target_directory
        self.engine.edit_preview_filename(bundle, item.item_id, "custom.jpg")
        self.engine.set_selected_models(bundle, {"CAM_B"})
        self.engine.set_selected_models(bundle, {"CAM_A"})
        self.assertEqual(bundle.preview_items[0].new_filename, "custom.jpg")
        self.assertEqual(bundle.preview_items[0].target_directory, folder)

    def test_execute_writes_mapped_target_and_mobile_path(self):
        bundle = self.preview({"CAM_A": "Action4"})
        self.engine.set_selected_models(bundle, {"CAM_A"})
        def generate(source_path, target_path, media_type, request):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"mobile")
            return "SUCCESS"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate):
            result = self.engine.execute(self.request, preview_bundle=bundle)
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertEqual(Path(result.execution_results[0].target_path).read_bytes(), b"original")
        self.assertEqual(Path(result.execution_results[0].mobile_output_path).read_bytes(), b"mobile")
        self.assertTrue(all(item.source_path.exists() for item in self.media))

    def test_alias_does_not_become_video_inference_identity(self):
        from photo_organizer.models import MediaItem
        video = MediaItem(self.source / "video.mp4", "video", ".mp4", self.media[0].captured_at)
        self.media = [self.media[0], video]
        video.source_path.write_bytes(b"video")
        bundle = self.preview({"CAM_A": "Action4"})
        self.assertTrue(all(item.model_name == "CAM_A" for item in bundle.preview_items))
        self.assertTrue(all(item.output_model_name == "Action4" for item in bundle.preview_items))
        self.assertIn("추론", bundle.preview_items[1].model_source)

    def test_unknown_alias_keeps_original_unknown(self):
        bundle = self.preview({"UNKNOWN": "Unidentified"})
        self.assertEqual(bundle.preview_items[2].model_name, "UNKNOWN")
        self.assertEqual(bundle.preview_items[2].output_model_name, "Unidentified")

    def test_changed_mapping_cannot_execute_old_preview(self):
        bundle = self.preview({"CAM_A": "Action4"})
        self.request.model_name_mappings = {"CAM_A": "Other"}
        with self.assertRaises(ValueError):
            self.engine.execute(self.request, preview_bundle=bundle)
        self.assertFalse(self.request.target_path.exists())

    def test_changed_scope_cannot_execute_old_preview(self):
        bundle = self.preview({"CAM_A": "Action4"})
        self.request.model_mapping_scope = "filename_only"
        with self.assertRaises(ValueError):
            self.engine.execute(self.request, preview_bundle=bundle)
        self.assertFalse(self.request.target_path.exists())

    def test_manual_filename_can_be_restored_after_mapping_change(self):
        old = self.preview({"CAM_A": "Old"})
        self.engine.edit_preview_filename(old, old.preview_items[0].item_id, "custom.jpg")
        new = self.preview({"CAM_A": "New"})
        count = self.engine.restore_manual_filenames(new, {old.preview_items[0].source_path: "custom.jpg"})
        self.assertEqual(count, 1)
        self.assertEqual(new.preview_items[0].new_filename, "custom.jpg")
        self.assertTrue(new.preview_items[0].filename_edited)
        self.assertEqual(Path(new.preview_items[0].target_directory).name, "20240101_New")
        self.assertEqual(Path(new.preview_items[0].mobile_output_path).parent.name, "output_20240101_New")

    def test_restored_manual_collision_is_visible_without_changing_names(self):
        new = self.preview({"CAM_A": "Same", "CAM_B": "Same"})
        auto = new.preview_items[1]
        self.engine.restore_manual_filenames(new, {new.preview_items[0].source_path: auto.new_filename})
        self.assertEqual(new.preview_items[0].new_filename, auto.new_filename)
        self.assertEqual([i.write_mode for i in new.preview_items[:2]], ["CONFLICT", "CONFLICT"])

    def test_restore_invalid_filename_is_atomic(self):
        new = self.preview({"CAM_A": "Same", "CAM_B": "Same"})
        before = [i.new_filename for i in new.preview_items]
        with self.assertRaises(ValueError):
            self.engine.restore_manual_filenames(new, {new.preview_items[0].source_path: "custom.jpg",
                                                       new.preview_items[1].source_path: "../invalid.jpg"})
        self.assertEqual([i.new_filename for i in new.preview_items], before)


if __name__ == "__main__":
    unittest.main()
