import unittest
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.fallback import canonical_model_key, infer_video_model_from_photos, parse_filename_fallback, explain_video_model_failure
from photo_organizer.models import MediaItem


class FallbackTests(unittest.TestCase):
    def test_dji_sequence_and_d_marker_are_not_camera_models(self) -> None:
        for filename in ("DJI_20240501113332_0053_D.MP4", "DJI_20240501113354_0054_D.MP4",
                         "dji_20240501113332_0016_d.mp4"):
            with self.subTest(filename=filename):
                captured_at, model, pattern = parse_filename_fallback(filename)
                self.assertIsNotNone(captured_at)
                self.assertIsNone(model)
                self.assertEqual(pattern, "DJI_YYYYMMDDHHMMSS_SEQ_D")
        self.assertEqual(parse_filename_fallback("DJI_20240501113332_0053_D.MP4")[0],
                         datetime(2024, 5, 1, 11, 33, 32))

    def test_dji_exception_does_not_change_organizer_or_other_models(self) -> None:
        self.assertEqual(parse_filename_fallback("20240501_113332_DJI_OsmoAction4_0001.mp4")[1],
                         "DJI_OsmoAction4")
        self.assertEqual(parse_filename_fallback("20240501_113332_SM-F926N_0001.mp4")[1], "SM-F926N")

    def test_unbounded_photos_require_matching_before_and_after_models(self) -> None:
        import photo_organizer.fallback as fallback
        self.assertTrue(hasattr(fallback, "find_video_model_candidate_unbounded_photos"))
        video = MediaItem(Path("folder/video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        before = MediaItem(Path("folder/before.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 10), model_name="CAM-A")
        after = MediaItem(Path("folder/after.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 13), model_name="CAMA")
        self.assertIsNone(infer_video_model_from_photos(video, [before, after])[0])
        self.assertIs(fallback.find_video_model_candidate_unbounded_photos(video, [before, after]), after)
        before.model_name = "CAMB"
        self.assertIsNone(fallback.find_video_model_candidate_unbounded_photos(video, [before, after]))
        self.assertIn("서로 다름", fallback.explain_unbounded_photo_failure(video, [before, after]))

    def test_unbounded_photos_can_use_one_side_but_reject_tied_conflict(self) -> None:
        import photo_organizer.fallback as fallback
        self.assertTrue(hasattr(fallback, "find_video_model_candidate_unbounded_photos"))
        video = MediaItem(Path("folder/video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        first = MediaItem(Path("folder/a.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 10), model_name="CAMA")
        second = MediaItem(Path("folder/b.jpg"), "photo", ".jpg", captured_at=first.captured_at, model_name="CAMB")
        self.assertIs(fallback.find_video_model_candidate_unbounded_photos(video, [first]), first)
        first.captured_at = datetime(2024, 1, 1, 13)
        self.assertIs(fallback.find_video_model_candidate_unbounded_photos(video, [first]), first)
        first.captured_at = second.captured_at
        self.assertIsNone(fallback.find_video_model_candidate_unbounded_photos(video, [first, second]))
        first.captured_at = second.captured_at = video.captured_at
        self.assertIsNone(fallback.find_video_model_candidate_unbounded_photos(video, [first, second]))

    def test_unbounded_photos_ignore_other_folders_videos_and_unknown(self) -> None:
        import photo_organizer.fallback as fallback
        self.assertTrue(hasattr(fallback, "find_video_model_candidate_unbounded_photos"))
        video = MediaItem(Path("folder/video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        items = [
            MediaItem(Path("other/a.jpg"), "photo", ".jpg", captured_at=video.captured_at, model_name="CAMA"),
            MediaItem(Path("folder/a.mp4"), "video", ".mp4", captured_at=video.captured_at, model_name="CAMA"),
            MediaItem(Path("folder/b.jpg"), "photo", ".jpg", captured_at=video.captured_at, model_name="UNKNOWN"),
            MediaItem(Path("folder/c.jpg"), "photo", ".jpg", model_name="CAMA"),
        ]
        self.assertIsNone(fallback.find_video_model_candidate_unbounded_photos(video, items))
        self.assertIn("사진 없음", fallback.explain_unbounded_photo_failure(video, items))
        video.captured_at = None
        self.assertIsNone(fallback.find_video_model_candidate_unbounded_photos(video, items))
        self.assertIn("일시 없음", fallback.explain_unbounded_photo_failure(video, items))

    def test_unbounded_photos_ignore_more_distant_same_side_models(self) -> None:
        import photo_organizer.fallback as fallback
        video = MediaItem(Path("folder/video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        near = MediaItem(Path("folder/near.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 10), model_name="CAMA")
        far = MediaItem(Path("folder/far.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 9), model_name="CAMB")
        self.assertIs(fallback.find_video_model_candidate_unbounded_photos(video, [far, near]), near)

    def test_inference_window_is_configurable_and_inclusive(self) -> None:
        video = MediaItem(Path("video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        photo = MediaItem(Path("photo.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 12, 10), model_name="CAMA")
        self.assertIsNone(infer_video_model_from_photos(video, [photo], window_minutes=9)[0])
        self.assertEqual(infer_video_model_from_photos(video, [photo], window_minutes=10)[0], "CAMA")
        self.assertIn("±9분", explain_video_model_failure(video, [photo], window_minutes=9))

    def test_zero_window_matches_only_identical_time(self) -> None:
        video = MediaItem(Path("video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        photo = MediaItem(Path("photo.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 12, 0, 1), model_name="CAMA")
        self.assertIsNone(infer_video_model_from_photos(video, [photo], window_minutes=0)[0])
        photo.captured_at = video.captured_at
        self.assertEqual(infer_video_model_from_photos(video, [photo], window_minutes=0)[0], "CAMA")

    def test_known_video_can_supply_model_and_candidate_details(self) -> None:
        import photo_organizer.fallback as fallback
        video = MediaItem(Path("video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        candidate = MediaItem(Path("known.mov"), "video", ".mov", captured_at=datetime(2024, 1, 1, 12, 1), model_name="CAMA", model_source="영상 메타")
        self.assertTrue(hasattr(fallback, "infer_video_model_from_media"))
        self.assertEqual(fallback.infer_video_model_from_media(video, [candidate]), ("CAMA", "영상 모델명 영상 추론"))
        self.assertIs(fallback.find_video_model_candidate(video, [candidate]), candidate)

    def test_mixed_media_tie_conflicts_and_unknown_candidates_are_ignored(self) -> None:
        import photo_organizer.fallback as fallback
        video = MediaItem(Path("video.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12))
        photo = MediaItem(Path("photo.jpg"), "photo", ".jpg", captured_at=datetime(2024, 1, 1, 11, 59), model_name="CAMA")
        known_video = MediaItem(Path("known.mp4"), "video", ".mp4", captured_at=datetime(2024, 1, 1, 12, 1), model_name="CAMB")
        unknown = MediaItem(Path("unknown.mp4"), "video", ".mp4", captured_at=video.captured_at, model_name="UNKNOWN")
        self.assertEqual(fallback.infer_video_model_from_media(video, [unknown, photo, known_video]), (None, "UNKNOWN"))
        self.assertIn("사진/영상 후보의 모델명이 서로 다름", explain_video_model_failure(video, [unknown, photo, known_video]))
        known_video.model_name = "CAM-A"
        self.assertEqual(fallback.infer_video_model_from_media(video, [unknown, photo, known_video]), ("CAMA", "영상 모델명 사진 추론"))

    def test_video_unknown_reason_explains_nearest_photo_outside_window(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4", captured_at=datetime(2024, 5, 1, 12, 53, 19))
        photos = [MediaItem(source_path=Path("photo.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 5, 1, 13, 2, 32), model_name="SM-F926N")]
        self.assertIsNone(infer_video_model_from_photos(video, photos)[0])
        reason = explain_video_model_failure(video, photos)
        self.assertIn("±5분", reason)
        self.assertIn("553초", reason)

    def test_video_unknown_reason_distinguishes_model_conflict(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4", captured_at=datetime(2024, 1, 1, 12))
        photos = [MediaItem(source_path=Path(name + ".jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 12), model_name=name) for name in ("CAMA", "CAMB")]
        self.assertIn("서로 다름", explain_video_model_failure(video, photos))

    def test_video_unknown_reason_distinguishes_missing_photos_and_time(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4")
        self.assertIn("일시 없음", explain_video_model_failure(video, []))
        video.captured_at = datetime(2024, 1, 1, 12)
        self.assertIn("사진/영상 없음", explain_video_model_failure(video, []))

    def test_parse_filename_with_model(self) -> None:
        parsed_at, model, source = parse_filename_fallback("20161008_010134_RX100M3.JPG")
        self.assertEqual(parsed_at, datetime(2016, 10, 8, 1, 1, 34))
        self.assertEqual(model, "RX100M3")
        self.assertEqual(source, "YYYYMMDD_HHMMSS_MODEL")

    def test_parse_filename_with_model_and_seq4(self) -> None:
        parsed_at, model, source = parse_filename_fallback("20161008_010134_D700_0001.JPG")
        self.assertEqual(parsed_at, datetime(2016, 10, 8, 1, 1, 34))
        self.assertEqual(model, "D700")
        self.assertEqual(source, "YYYYMMDD_HHMMSS_MODEL")

    def test_parse_filename_keeps_model_suffix_numbers(self) -> None:
        parsed_at, model, source = parse_filename_fallback("20161008_010134_RX100M3_0001.JPG")
        self.assertEqual(parsed_at, datetime(2016, 10, 8, 1, 1, 34))
        self.assertEqual(model, "RX100M3")
        self.assertEqual(source, "YYYYMMDD_HHMMSS_MODEL")

    def test_parse_filename_img_pattern(self) -> None:
        parsed_at, model, source = parse_filename_fallback("IMG_20240115_183000.jpg")
        self.assertEqual(parsed_at, datetime(2024, 1, 15, 18, 30, 0))
        self.assertIsNone(model)
        self.assertEqual(source, "IMG_YYYYMMDD_HHMMSS")

    def test_parse_filename_img_pattern_with_milliseconds(self) -> None:
        parsed_at, model, source = parse_filename_fallback("img_20240327170722454.jpg")
        self.assertEqual(parsed_at, datetime(2024, 3, 27, 17, 7, 22))
        self.assertIsNone(model)
        self.assertEqual(source, "IMG_YYYYMMDD_HHMMSS")

    def test_infer_video_model_uses_closest_photo(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4", captured_at=datetime(2024, 1, 1, 12, 0, 0))
        photos = [
            MediaItem(source_path=Path("a.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 11, 59, 0), model_name="CAMA"),
            MediaItem(source_path=Path("b.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 12, 2, 0), model_name="CAMB"),
        ]
        model, source = infer_video_model_from_photos(video, photos)
        self.assertEqual(model, "CAMA")
        self.assertEqual(source, "영상 모델명 사진 추론")

    def test_infer_video_model_conflict_returns_unknown(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4", captured_at=datetime(2024, 1, 1, 12, 0, 0))
        photos = [
            MediaItem(source_path=Path("a.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 11, 59, 0), model_name="CAMA"),
            MediaItem(source_path=Path("b.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 12, 1, 0), model_name="CAMB"),
        ]
        model, source = infer_video_model_from_photos(video, photos)
        self.assertIsNone(model)
        self.assertEqual(source, "UNKNOWN")

    def test_canonical_model_key_ignores_spacing_and_separators(self) -> None:
        self.assertEqual(canonical_model_key("Galaxy Z Fold6"), "galaxyzfold6")
        self.assertEqual(canonical_model_key("GalaxyZFold6"), "galaxyzfold6")
        self.assertEqual(canonical_model_key("Galaxy_Z_Fold6"), "galaxyzfold6")

    def test_infer_video_model_treats_same_model_key_as_non_conflict(self) -> None:
        video = MediaItem(source_path=Path("video.mp4"), media_type="video", extension=".mp4", captured_at=datetime(2024, 1, 1, 12, 0, 0))
        photos = [
            MediaItem(source_path=Path("a.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 11, 59, 0), model_name="Galaxy_Z_Fold6"),
            MediaItem(source_path=Path("b.jpg"), media_type="photo", extension=".jpg", captured_at=datetime(2024, 1, 1, 11, 59, 0), model_name="GalaxyZFold6"),
        ]
        model, source = infer_video_model_from_photos(video, photos)
        self.assertEqual(model, "Galaxy_Z_Fold6")
        self.assertEqual(source, "영상 모델명 사진 추론")


if __name__ == "__main__":
    unittest.main()
