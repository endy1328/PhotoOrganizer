import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import MediaItem, OrganizeRequest, PreviewBundle


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="model_selection_", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.request = OrganizeRequest(self.source, self.base / "target", mobile_output_enabled=False)
        self.engine = OrganizerEngine(self.base)
        self.media = []
        for index, (model, day) in enumerate((("B", 1), ("A", 1), ("A", 1), ("UNKNOWN", 1), ("A", 2))):
            path = self.source / f"{index}.jpg"
            path.write_bytes(b"original")
            self.media.append(MediaItem(path, "photo", ".jpg", datetime(2024, 1, day, 12, index),
                                        "사진 메타", model, "사진 메타"))
        with patch.object(self.engine.extractor, "extract", side_effect=self.media):
            self.bundle = self.engine.preview(self.request)

    def test_selection_recomputes_date_sequences_and_reselects(self):
        self.engine.set_selected_models(self.bundle, {"A", "UNKNOWN"})
        self.assertEqual([i.included for i in self.bundle.preview_items], [False, True, True, True, True])
        selected = [i for i in self.bundle.preview_items if i.included]
        self.assertEqual([Path(i.new_filename).stem[-4:] for i in selected], ["0001", "0002", "0003", "0001"])
        self.assertTrue(self.bundle.selection_applied)
        self.engine.set_selected_models(self.bundle, {"A", "B", "UNKNOWN"})
        self.assertTrue(all(i.included for i in self.bundle.preview_items))
        self.assertEqual([Path(i.new_filename).stem[-4:] for i in self.bundle.preview_items],
                         ["0001", "0002", "0003", "0004", "0001"])

    def test_copy_excludes_target_output_and_deletion_candidates(self):
        self.engine.set_selected_models(self.bundle, {"B"})
        excluded = self.bundle.preview_items[1:]
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertEqual(len(result.delete_review_items), 1)
        self.assertEqual(result.delete_review_items[0].item_id, str(self.media[0].source_path))
        self.assertTrue(all(not Path(i.target_path).exists() for i in excluded))
        self.assertTrue(all(m.source_path.exists() for m in self.media))

    def test_move_leaves_excluded_originals(self):
        self.request.operation_mode = "move"
        self.engine.set_selected_models(self.bundle, {"B"})
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(len(result.execution_results), 1)
        self.assertFalse(self.media[0].source_path.exists())
        self.assertTrue(all(m.source_path.exists() for m in self.media[1:]))

    def test_empty_selection_performs_no_file_operations(self):
        self.engine.set_selected_models(self.bundle, set())
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results, [])
        self.assertEqual(result.delete_review_items, [])
        self.assertFalse(self.request.target_path.exists())

    def test_manual_filename_survives_selection_and_reselection(self):
        item = self.bundle.preview_items[1]
        self.engine.edit_preview_filename(self.bundle, item.item_id, "custom.jpg")
        self.engine.set_selected_models(self.bundle, {"B"})
        self.assertEqual(self.bundle.preview_items[1].new_filename, "custom.jpg")
        self.engine.set_selected_models(self.bundle, {"A"})
        self.assertEqual(self.bundle.preview_items[1].new_filename, "custom.jpg")
        self.assertTrue(self.bundle.preview_items[1].filename_edited)
        self.assertTrue(self.bundle.preview_items[2].new_filename.endswith("_0002.jpg"))

    def test_new_duplicate_after_resequence_is_conflict_and_preserves_manual_name(self):
        manual = self.bundle.preview_items[1]
        auto = self.bundle.preview_items[2]
        conflicting_name = auto.new_filename.replace("_0003.jpg", "_0002.jpg")
        self.engine.edit_preview_filename(self.bundle, manual.item_id, conflicting_name)
        self.engine.set_selected_models(self.bundle, {"A"})
        self.assertEqual(self.bundle.preview_items[1].new_filename, conflicting_name)
        self.assertEqual([i.write_mode for i in self.bundle.preview_items[1:3]], ["CONFLICT", "CONFLICT"])
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertTrue(all(i.status == "ERROR" for i in result.execution_results[:2]))
        self.assertFalse(Path(manual.target_path).exists())

    def test_excluded_rows_cannot_be_edited(self):
        self.engine.set_selected_models(self.bundle, {"B"})
        with self.assertRaises(ValueError):
            self.engine.edit_preview_filename(self.bundle, self.bundle.preview_items[1].item_id, "custom.jpg")

    def test_editing_manual_name_clears_resolved_selection_conflicts(self):
        manual, auto = self.bundle.preview_items[1:3]
        self.engine.edit_preview_filename(self.bundle, manual.item_id,
                                          auto.new_filename.replace("_0003.jpg", "_0002.jpg"))
        self.engine.set_selected_models(self.bundle, {"A"})
        self.engine.edit_preview_filename(self.bundle, manual.item_id, "safe.jpg")
        self.assertEqual([i.write_mode for i in self.bundle.preview_items[1:3]], ["NEW", "NEW"])
        self.assertFalse(any("모델 선택 후 출력" in w for i in self.bundle.preview_items for w in i.warnings))

    def test_existing_target_collision_is_rechecked_on_selection(self):
        selected = self.bundle.preview_items[1]
        new_path = Path(selected.target_path.replace("_0002.jpg", "_0001.jpg"))
        new_path.parent.mkdir(parents=True)
        new_path.write_bytes(b"existing unrelated file")
        self.engine.set_selected_models(self.bundle, {"A"})
        self.assertEqual(self.bundle.preview_items[1].write_mode, "CONFLICT")
        self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(new_path.read_bytes(), b"existing unrelated file")

    def test_selection_existing_target_check_never_reextracts_metadata(self):
        self.media[1].metadata["source_metadata"] = {"Model": "A"}
        selected = self.bundle.preview_items[1]
        new_path = Path(selected.target_path.replace("_0002.jpg", "_0001.jpg"))
        new_path.parent.mkdir(parents=True)
        new_path.write_bytes(b"original")
        with patch.object(self.engine.extractor, "extract") as extract:
            self.engine.set_selected_models(self.bundle, {"A"})
        extract.assert_not_called()
        self.assertEqual(self.bundle.preview_items[1].write_mode, "CONFLICT")

    def test_existing_mobile_only_output_is_protected_after_selection(self):
        self.request.mobile_output_enabled = True
        for row in self.bundle.preview_items:
            row.mobile_output_enabled = True
        selected = self.bundle.preview_items[1]
        name = selected.new_filename.replace("_0002.jpg", "_0001.jpg")
        mobile = self.engine._build_mobile_output_path(Path(selected.target_directory), name)
        mobile.parent.mkdir(parents=True)
        mobile.write_bytes(b"existing output")
        self.engine.set_selected_models(self.bundle, {"A"})
        self.assertEqual(self.bundle.preview_items[1].write_mode, "CONFLICT")
        def generate(source_path, target_path, media_type, request):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"new output")
            return "SUCCESS"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate):
            self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(mobile.read_bytes(), b"existing output")

    def test_planned_conflict_does_not_stop_later_mobile_outputs(self):
        self.request.mobile_output_enabled = True
        for row in self.bundle.preview_items:
            row.mobile_output_enabled = True
        manual, auto = self.bundle.preview_items[1:3]
        self.engine.edit_preview_filename(self.bundle, manual.item_id,
                                          auto.new_filename.replace("_0003.jpg", "_0002.jpg"))
        self.engine.set_selected_models(self.bundle, {"A"})
        def generate(source_path, target_path, media_type, request):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"output")
            return "SUCCESS"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate):
            result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual([row.status for row in result.execution_results], ["ERROR", "ERROR", "SUCCESS"])

    def test_excluded_rows_do_not_reserve_names(self):
        first, second = self.bundle.preview_items[1:3]
        self.engine.set_selected_models(self.bundle, {"B"})
        # Re-include only A then directly mark one item excluded to exercise edit validation.
        self.engine.set_selected_models(self.bundle, {"A"})
        first, second = self.bundle.preview_items[1:3]
        first.included = False
        self.engine.edit_preview_filename(self.bundle, second.item_id, first.new_filename)
        self.assertEqual(second.new_filename, first.new_filename)

    def test_video_inference_is_resolved_before_selection(self):
        photo = self.media[0]
        video_path = self.source / "video.mp4"
        video_path.write_bytes(b"video")
        video = MediaItem(video_path, "video", ".mp4", photo.captured_at, "영상 메타")
        with patch.object(self.engine, "_scan_media_files", return_value=[photo.source_path, video_path]), \
             patch.object(self.engine.extractor, "extract", side_effect=[photo, video]):
            bundle = self.engine.preview(self.request)
        self.engine.set_selected_models(bundle, set())
        self.engine.set_selected_models(bundle, {"B"})
        self.assertEqual(bundle.preview_items[1].model_name, "B")
        self.assertIn("추론", bundle.preview_items[1].model_source)

    def test_mobile_paths_resequence_and_only_included_are_generated(self):
        self.request.mobile_output_enabled = True
        for item in self.bundle.preview_items:
            item.mobile_output_enabled = True
        self.engine.set_selected_models(self.bundle, {"B"})
        def generate(source_path, target_path, media_type, request):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"output")
            return "SUCCESS"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate) as create:
            result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertTrue(Path(self.bundle.preview_items[0].mobile_output_path).exists())
        self.assertTrue(all(not Path(i.mobile_output_path).exists() for i in self.bundle.preview_items[1:]
                            if i.mobile_output_path))


if __name__ == "__main__":
    unittest.main()
