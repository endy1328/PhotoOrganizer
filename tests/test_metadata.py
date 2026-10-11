import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.metadata import MetadataExtractor
from photo_organizer.models import MediaItem


class MetadataTests(unittest.TestCase):
    def test_verified_dji_encoder_is_used_before_filename_sequence(self) -> None:
        response = subprocess.CompletedProcess([], 0,
            b'{"format":{"tags":{"creation_time":"2024-05-01T02:33:33Z","encoder":"DJI OsmoAction4"}},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=response), \
             patch("photo_organizer.metadata.MediaInfo", None):
            item = MetadataExtractor().extract(Path("DJI_20240501113332_0053_D.MP4"))
        self.assertEqual(item.model_name, "DJI_OsmoAction4")
        self.assertEqual(item.model_source, "영상 메타")
        self.assertEqual(item.metadata["video_model_lookup"]["status"], "found")
        self.assertEqual(item.metadata["video_model_lookup"]["model"], "DJI OsmoAction4")
        self.assertEqual(item.datetime_source, "영상 메타")

    def test_explicit_stream_model_precedes_known_format_encoder(self) -> None:
        item = MediaItem(Path("sample.mp4"), "video", ".mp4")
        MetadataExtractor()._apply_ffprobe_metadata(item, {
            "format": {"tags": {"encoder": "DJI OsmoAction4"}},
            "streams": [{"tags": {"model": "OTHER_CAMERA"}}],
        })
        self.assertEqual(item.model_name, "OTHER_CAMERA")

    def test_explicit_mediainfo_track_model_precedes_known_encoder(self) -> None:
        item = MediaItem(Path("sample.mp4"), "video", ".mp4")
        MetadataExtractor()._apply_mediainfo(item, {"tracks": [
            {"track_type": "General", "encoder": "DJI OsmoAction4"},
            {"track_type": "Video", "camera_model": "OTHER_CAMERA"},
        ]})
        self.assertEqual(item.model_name, "OTHER_CAMERA")

    def test_verified_encoder_key_case_and_device_spacing_are_normalized(self) -> None:
        for value in ("DJI OsmoAction4", "dji osmoaction4", " DJI Osmo Action 4 "):
            with self.subTest(encoder=value):
                item = MediaItem(Path("sample.mp4"), "video", ".mp4")
                MetadataExtractor()._apply_ffprobe_metadata(item, {
                    "format": {"tags": {"ENCODER": value}}, "streams": [],
                })
                self.assertEqual(item.model_name, "DJI_OsmoAction4")

    def test_generic_or_unverified_encoders_do_not_supply_camera_model(self) -> None:
        for value in ("DJI", "DJI OsmoAction5", "Lavf61.1", "Samsung", "DJI OsmoAction4 edited", 4):
            with self.subTest(encoder=value):
                item = MediaItem(Path("sample.mp4"), "video", ".mp4")
                MetadataExtractor()._apply_ffprobe_metadata(item, {
                    "format": {"tags": {"encoder": value}}, "streams": [],
                })
                self.assertIsNone(item.model_name)

    def test_dji_without_device_metadata_keeps_model_unresolved(self) -> None:
        response = subprocess.CompletedProcess([], 0, b'{"format":{"tags":{}},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=response), \
             patch("photo_organizer.metadata.MediaInfo", None):
            item = MetadataExtractor().extract(Path("DJI_20240501113332_0053_D.MP4"))
        self.assertEqual(item.captured_at, datetime(2024, 5, 1, 11, 33, 32))
        self.assertIsNone(item.model_name)
        self.assertEqual(item.metadata["video_model_lookup"]["status"], "not_found")

    def test_video_lookup_without_supported_tag_is_information_not_warning(self) -> None:
        result = subprocess.CompletedProcess([], 0, b'{"format":{"tags":{"com.android.version":"14"}},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=result), patch("photo_organizer.metadata.MediaInfo", None):
            item = MetadataExtractor().extract(Path("20240501_125303_FILENAMECAM.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "not_found")
        self.assertIsNone(lookup["model"])
        self.assertEqual(lookup["tools"]["ffprobe"]["status"], "success")
        self.assertEqual(lookup["tools"]["mediainfo"]["status"], "unavailable")
        self.assertEqual(item.model_name, "FILENAMECAM")
        self.assertEqual(item.model_source, "파일명 fallback")
        self.assertEqual(item.warnings, [])

    def test_video_lookup_direct_model_skips_unneeded_secondary_tool(self) -> None:
        result = subprocess.CompletedProcess([], 0, b'{"format":{"tags":{"creation_time":"2024-05-01T12:53:19","model":"Galaxy Z Fold6"}},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=result), patch("photo_organizer.metadata.MediaInfo") as mediainfo:
            item = MetadataExtractor().extract(Path("20240501_125303_FILENAMECAM.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "found")
        self.assertEqual(lookup["model"], "Galaxy Z Fold6")
        self.assertEqual(lookup["tools"]["mediainfo"]["status"], "not_needed")
        mediainfo.parse.assert_not_called()
        self.assertEqual(item.model_name, "Galaxy_Z_Fold6")

    def test_video_lookup_secondary_success_keeps_primary_failure(self) -> None:
        with patch("photo_organizer.metadata.subprocess.run", side_effect=FileNotFoundError("ffprobe unavailable")), patch("photo_organizer.metadata.MediaInfo") as mediainfo:
            mediainfo.parse.return_value.to_data.return_value = {"tracks": [{"model": "SM-F926N"}]}
            item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "found")
        self.assertEqual(lookup["model"], "SM-F926N")
        self.assertEqual(lookup["tools"]["ffprobe"]["status"], "unavailable")
        self.assertEqual(lookup["tools"]["mediainfo"]["status"], "success")
        self.assertIn("ffprobe unavailable", lookup["tools"]["ffprobe"]["detail"])
        self.assertTrue(item.warnings)

    def test_video_lookup_direct_model_remains_found_when_secondary_fails(self) -> None:
        result = subprocess.CompletedProcess([], 0, b'{"format":{"tags":{"model":"SM-F926N"}},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=result), patch("photo_organizer.metadata.MediaInfo") as mediainfo:
            mediainfo.parse.side_effect = RuntimeError("secondary failure")
            item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "found")
        self.assertEqual(lookup["tools"]["ffprobe"]["status"], "success")
        self.assertEqual(lookup["tools"]["mediainfo"]["status"], "error")
        self.assertIn("secondary failure", lookup["tools"]["mediainfo"]["detail"])

    def test_video_lookup_partial_failure_does_not_claim_all_queries_failed(self) -> None:
        result = subprocess.CompletedProcess([], 0, b'{"format":{},"streams":[]}')
        with patch("photo_organizer.metadata.subprocess.run", return_value=result), patch("photo_organizer.metadata.MediaInfo") as mediainfo:
            mediainfo.parse.side_effect = RuntimeError("secondary failure")
            item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "not_found")
        self.assertIsNone(lookup["model"])
        self.assertEqual(lookup["tools"]["mediainfo"]["status"], "error")

    def test_video_lookup_all_queries_failed_preserves_filename_distinction(self) -> None:
        with patch("photo_organizer.metadata.subprocess.run", side_effect=subprocess.TimeoutExpired(["ffprobe"], 60)), patch("photo_organizer.metadata.MediaInfo", None):
            item = MetadataExtractor().extract(Path("20240501_125303_FILENAMECAM.mp4"))
        lookup = item.metadata["video_model_lookup"]
        self.assertEqual(lookup["status"], "failed")
        self.assertIsNone(lookup["model"])
        self.assertEqual(lookup["tools"]["ffprobe"]["status"], "error")
        self.assertEqual(item.model_name, "FILENAMECAM")

    def test_extract_preserves_original_extension_case(self) -> None:
        extractor = MetadataExtractor()

        with patch.object(MetadataExtractor, "_extract_photo_metadata", autospec=True), patch.object(
            MetadataExtractor, "_apply_filename_fallback", autospec=True
        ):
            lower_item = extractor.extract(Path("sample.jpg"))
            upper_item = extractor.extract(Path("sample.JPG"))
            mixed_item = extractor.extract(Path("sample.JpG"))

        self.assertEqual(lower_item.extension, ".jpg")
        self.assertEqual(upper_item.extension, ".JPG")
        self.assertEqual(mixed_item.extension, ".JpG")

    def test_ffprobe_decodes_utf8_bytes(self) -> None:
        extractor = MetadataExtractor()
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            self.assertFalse(kwargs.get("text", False))
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout='{"format":{"tags":{"creation_time":"2024-01-15T18:30:00","model":"RX100M3","comment":"테스트메모"}},"streams":[]}'.encode("utf-8"),
                stderr="",
            )

        with patch("photo_organizer.metadata.subprocess.run", side_effect=fake_run):
            extractor._extract_video_metadata(item)  # noqa: SLF001

        self.assertEqual(item.datetime_source, "영상 메타")
        self.assertEqual(item.model_name, "RX100M3")
        self.assertEqual(item.model_source, "영상 메타")
        self.assertEqual(item.metadata["source_metadata"]["ffprobe"]["comment"], "테스트메모")

    def test_ffprobe_failure_preserves_stderr_and_uses_mediainfo(self) -> None:
        failure = subprocess.CalledProcessError(1, ["ffprobe"], stderr="파일 열기 실패".encode("utf-8"))
        with patch("photo_organizer.metadata.subprocess.run", side_effect=failure), patch(
            "photo_organizer.metadata.MediaInfo"
        ) as mediainfo:
            mediainfo.parse.return_value.to_data.return_value = {
                "tracks": [{"recorded_hardware_model_name": "SM-F926N"}]
            }
            item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
        self.assertEqual(item.model_name, "SM-F926N")
        self.assertTrue(any("종료 코드 1; 파일 열기 실패" in warning for warning in item.warnings))

    def test_missing_ffprobe_output_reports_actionable_warning_and_falls_back(self) -> None:
        for output in (None, b"", b"   "):
            with self.subTest(output=output):
                result = subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")
                with patch("photo_organizer.metadata.subprocess.run", return_value=result), patch(
                    "photo_organizer.metadata.MediaInfo", None
                ):
                    item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
                self.assertEqual(item.datetime_source, "파일명 fallback")
                self.assertTrue(any("출력이 없습니다" in warning for warning in item.warnings))

    def test_invalid_json_shape_is_reported(self) -> None:
        for output in (b"[]", b"null", b"not json"):
            with self.subTest(output=output):
                with patch("photo_organizer.metadata.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output)), patch(
                    "photo_organizer.metadata.MediaInfo", None
                ):
                    item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
                self.assertTrue(any("JSON" in warning for warning in item.warnings))

    def test_video_model_tags_are_case_insensitive(self) -> None:
        for key in ("Model", "COM.APPLE.QUICKTIME.MODEL", "camera_model", "device_model"):
            with self.subTest(key=key):
                item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")
                MetadataExtractor()._apply_ffprobe_metadata(item, {"format": {"tags": {key: "SM-F926N"}}, "streams": []})
                self.assertEqual(item.model_name, "SM-F926N")

    def test_unknown_format_model_does_not_mask_valid_stream_model(self) -> None:
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")
        MetadataExtractor()._apply_ffprobe_metadata(item, {
            "format": {"tags": {"model": "UNKNOWN", "com.apple.quicktime.model": " "}},
            "streams": [{"codec_type": "video", "tags": {"Model": "SM-F926N"}}],
        })
        self.assertEqual(item.model_name, "SM-F926N")

    def test_mediainfo_recorded_hardware_model_is_used(self) -> None:
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")
        MetadataExtractor()._apply_mediainfo(item, {"tracks": [{"track_type": "General", "recorded_hardware_model_name": "SM-F926N"}]})
        self.assertEqual(item.model_name, "SM-F926N")

    def test_platform_information_is_not_used_as_model(self) -> None:
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")
        MetadataExtractor()._apply_ffprobe_metadata(item, {"format": {"tags": {"com.android.version": "14", "encoder": "Samsung"}}, "streams": []})
        self.assertIsNone(item.model_name)

    def test_unknown_model_description_is_not_used(self) -> None:
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")
        MetadataExtractor()._apply_ffprobe_metadata(item, {"format": {"tags": {"model": "unknown camera"}}, "streams": []})
        self.assertIsNone(item.model_name)

    def test_ffprobe_timeout_uses_filename_fallback(self) -> None:
        with patch("photo_organizer.metadata.subprocess.run", side_effect=subprocess.TimeoutExpired(["ffprobe"], 60)), patch(
            "photo_organizer.metadata.MediaInfo", None
        ):
            item = MetadataExtractor().extract(Path("20240501_125303.mp4"))
        self.assertEqual(item.datetime_source, "파일명 fallback")
        self.assertTrue(any("60" in warning for warning in item.warnings))

    def test_ffprobe_converts_utc_creation_time_to_local_time(self) -> None:
        extractor = MetadataExtractor()
        item = MediaItem(source_path=Path("sample.mp4"), media_type="video", extension=".mp4")

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout='{"format":{"tags":{"creation_time":"2024-01-15T09:30:00Z","model":"RX100M3"}},"streams":[]}',
                stderr="",
            )

        with patch("photo_organizer.metadata.subprocess.run", side_effect=fake_run):
            extractor._extract_video_metadata(item)  # noqa: SLF001

        expected = datetime.fromisoformat("2024-01-15T09:30:00+00:00").astimezone().replace(tzinfo=None)
        self.assertEqual(item.captured_at, expected)
        self.assertEqual(item.datetime_source, "영상 메타")


if __name__ == "__main__":
    unittest.main()
