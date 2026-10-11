import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import MediaItem, OrganizeRequest


class PreviewEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix="preview_edit_test_")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.target = self.base / "target"
        self.source.mkdir()
        self.target.mkdir()
        self.file = self.source / "20240501_125303.jpg"
        self.file.write_bytes(b"original")
        self.engine = OrganizerEngine(self.base)
        self.request = OrganizeRequest(source_path=self.source, target_path=self.target, mobile_output_enabled=False)
        self.bundle = self.engine.preview(self.request)
        self.item = self.bundle.preview_items[0]

    def test_edit_updates_destination_and_actual_copy(self):
        folder = self.item.target_directory
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "旅行_SM-F926N.jpg")
        self.assertEqual(self.item.target_directory, folder)
        self.assertEqual(Path(self.item.target_path).name, "旅行_SM-F926N.jpg")
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertEqual(Path(self.item.target_path).read_bytes(), b"original")
        self.assertTrue(self.file.exists())

    def test_invalid_names_are_rejected_without_changing_preview(self):
        original = self.item.new_filename
        for name in ("", "../x.jpg", "bad\\x.jpg", "CON.jpg", "CON .jpg", "COM¹.jpg", "NUL.any.jpg", "bad?.jpg", "x.jpg ", "x.png", "a" * 256 + ".jpg"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.engine.edit_preview_filename(self.bundle, self.item.item_id, name)
            self.assertEqual(self.item.new_filename, original)

    def test_existing_file_and_preview_duplicate_are_rejected(self):
        parent = Path(self.item.target_directory)
        parent.mkdir(parents=True)
        (parent / "taken.jpg").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.engine.edit_preview_filename(self.bundle, self.item.item_id, "taken.jpg")
        import copy
        other = copy.deepcopy(self.item)
        other.item_id = "other"
        other.new_filename = "another.jpg"
        other.target_path = str(parent / "another.jpg")
        self.bundle.preview_items.append(other)
        with self.assertRaises(ValueError):
            self.engine.edit_preview_filename(self.bundle, self.item.item_id, "ANOTHER.jpg")
        self.assertEqual((parent / "taken.jpg").read_bytes(), b"keep")

    def test_file_created_after_edit_is_not_overwritten(self):
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        target = Path(self.item.target_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing")
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "ERROR")
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertTrue(self.file.exists())

    def test_move_uses_edited_filename_and_preserves_existing_collision(self):
        self.request.operation_mode = "move"
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertEqual(Path(self.item.target_path).read_bytes(), b"original")
        self.assertFalse(self.file.exists())

    def test_partial_copy_failure_keeps_source_and_removes_own_partial_output(self):
        from unittest.mock import patch
        self.request.operation_mode = "move"
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        with patch("photo_organizer.engine.shutil.copyfileobj", side_effect=OSError("write failed")):
            result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "ERROR")
        self.assertTrue(self.file.exists())
        self.assertFalse(Path(self.item.target_path).exists())

    def test_known_video_is_a_model_candidate_only_in_same_folder(self):
        first = MediaItem(self.source / "video.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, 9))
        known = MediaItem(self.source / "known.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12), model_name="CAM", model_source="영상 메타")
        elsewhere = MediaItem(self.base / "other" / "known.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, 9), model_name="OTHER", model_source="영상 메타")
        self.engine._infer_video_models([first, known, elsewhere], 10)
        self.assertEqual(first.model_name, "CAM")
        self.assertEqual(first.model_source, "영상 모델명 영상 추론")

    def test_edit_updates_mobile_name_and_checks_collision(self):
        self.item.mobile_output_enabled = True
        self.item.mobile_output_path = str(self.engine._build_mobile_output_path(Path(self.item.target_directory), self.item.new_filename))
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        mobile = Path(self.item.mobile_output_path)
        self.assertEqual(mobile.name, "custom.jpg")
        mobile.parent.mkdir(parents=True)
        (mobile.parent / "taken.jpg").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.engine.edit_preview_filename(self.bundle, self.item.item_id, "taken.jpg")

    def test_mobile_file_created_during_generation_is_not_overwritten(self):
        from unittest.mock import patch
        self.item.mobile_output_enabled = True
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        mobile = Path(self.item.mobile_output_path)
        def generate(source_path, target_path, media_type, request):
            mobile.parent.mkdir(parents=True, exist_ok=True)
            mobile.write_bytes(b"existing mobile")
            target_path.write_bytes(b"generated mobile")
            return "SUCCESS"
        self.request.operation_mode = "move"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate):
            result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "ERROR")
        self.assertEqual(mobile.read_bytes(), b"existing mobile")
        self.assertTrue(self.file.exists())

    def test_manual_move_publishes_mobile_before_removing_source(self):
        from unittest.mock import patch
        self.item.mobile_output_enabled = True
        self.request.operation_mode = "move"
        self.engine.edit_preview_filename(self.bundle, self.item.item_id, "custom.jpg")
        def generate(source_path, target_path, media_type, request):
            self.assertTrue(self.file.exists())
            target_path.write_bytes(b"mobile")
            return "SUCCESS"
        with patch.object(self.engine, "_create_mobile_output", side_effect=generate):
            result = self.engine.execute(self.request, preview_bundle=self.bundle)
        self.assertEqual(result.execution_results[0].status, "SUCCESS")
        self.assertEqual(Path(self.item.mobile_output_path).read_bytes(), b"mobile")
        self.assertAlmostEqual(Path(self.item.mobile_output_path).stat().st_mtime,
                               datetime.fromisoformat(self.item.captured_at).timestamp(), delta=0.001)
        self.assertFalse(self.file.exists())

    def test_video_lookup_and_final_model_source_are_independent(self):
        item = MediaItem(self.file, "video", ".mp4", model_name="CAM", model_source="영상 모델명 사진 추론")
        item.metadata["video_model_lookup"] = {"status": "not_found", "model": None, "tools": {"ffprobe": {"status": "success", "detail": ""}, "mediainfo": {"status": "error", "detail": "failed"}}}
        rows = dict(self.engine._build_metadata_entries(item))
        self.assertEqual(rows["영상 모델 조회"], "지원 태그에서 모델명 미확인")
        self.assertEqual(rows["모델명 출처"], "영상 모델명 사진 추론")
        self.assertIn("실패", rows["mediainfo 조회"])

    def test_video_inference_does_not_chain_through_newly_inferred_video(self):
        first = MediaItem(self.source / "first.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, 4))
        second = MediaItem(self.source / "second.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, 8))
        anchor = MediaItem(self.source / "known.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12), model_name="CAM", model_source="영상 메타")
        self.engine._infer_video_models([anchor, first, second], 5)
        self.assertEqual(first.model_name, "CAM")
        self.assertEqual(second.model_name, "UNKNOWN")

    def test_sequences_continue_across_models_and_unknown_for_same_day(self):
        models = ("CAM", "UNKNOWN", "OTHER", "UNKNOWN")
        items = [MediaItem(self.source / f"{index}.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, index), model_name=model) for index, model in enumerate(models)]
        items.append(MediaItem(self.source / "next_day.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 2, 12), model_name="UNKNOWN"))
        rows, errors, _ = self.engine._build_preview(items, self.target, self.request)
        self.assertFalse(errors)
        self.assertEqual([Path(row.new_filename).stem.rsplit("_", 1)[1] for row in rows], ["0001", "0002", "0003", "0004", "0001"])
        self.assertEqual(Path(rows[1].target_directory).name, "20240101_UNKNOWN")

    def test_missing_date_file_is_skipped_without_breaking_date_sequence(self):
        first = MediaItem(self.source / "first.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12), model_name="CAM")
        invalid = MediaItem(self.source / "invalid.mp4", "video", ".mp4")
        second = MediaItem(self.source / "second.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 13), model_name="UNKNOWN")
        rows, errors, _ = self.engine._build_preview([second, invalid, first], self.target, self.request)
        self.assertEqual([Path(row.new_filename).stem.rsplit("_", 1)[1] for row in rows], ["0001", "0002"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(Path(errors[0].source_path).name, "invalid.mp4")

    def test_unknown_video_uses_photos_outside_configured_window(self):
        video = MediaItem(self.source / "video.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        before = MediaItem(self.source / "before.jpg", "photo", ".jpg", captured_at=datetime(2024, 1, 1, 10), model_name="CAM", model_source="사진 메타")
        after = MediaItem(self.source / "after.jpg", "photo", ".jpg", captured_at=datetime(2024, 1, 1, 14), model_name="CAM", model_source="사진 메타")
        self.engine._infer_video_models([video, before, after], 5)
        self.assertEqual(video.model_name, "CAM")
        self.assertIn("시간 제한 없음", video.model_source)
        self.assertEqual(video.metadata["model_inference"]["mode"], "unbounded_photos")

    def test_outside_window_conflicting_surrounding_photos_remain_unknown(self):
        video = MediaItem(self.source / "video.mp4", "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        before = MediaItem(self.source / "before.jpg", "photo", ".jpg", captured_at=datetime(2024, 1, 1, 10), model_name="CAMA", model_source="사진 메타")
        after = MediaItem(self.source / "after.jpg", "photo", ".jpg", captured_at=datetime(2024, 1, 1, 14), model_name="CAMB", model_source="사진 메타")
        self.engine._infer_video_models([video, before, after], 5)
        self.assertEqual(video.model_name, "UNKNOWN")
        self.assertIn("서로 다름", video.metadata["model_inference"]["detail"])


if __name__ == "__main__":
    unittest.main()
