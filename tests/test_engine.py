import unittest
from datetime import datetime
from pathlib import Path
import sys
import shutil
import copy
from unittest.mock import patch

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from PIL import PngImagePlugin
except Exception:
    PngImagePlugin = None

try:
    import piexif
except Exception:
    piexif = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import MediaItem, OrganizeRequest


class EngineTests(unittest.TestCase):
    def _case_dir(self, name: str) -> Path:
        base = Path(__file__).resolve().parents[1] / ".tmp_test" / name
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _media_item(self, path: Path, metadata_snapshot: dict[str, object]) -> MediaItem:
        return MediaItem(
            source_path=path,
            media_type="photo",
            extension=path.suffix,
            captured_at=datetime(2024, 1, 1, 12, 0, 0),
            datetime_source="사진 메타",
            model_name="RX100M3",
            model_source="사진 메타",
            metadata={"source_metadata": metadata_snapshot},
        )

    def test_target_filename_uses_seq(self) -> None:
        base = self._case_dir("seq_case")
        engine = OrganizerEngine(base)
        target_dir = base / "target"
        target_dir.mkdir()
        (target_dir / "20240101_120000_RX100M3_0001.JPG").write_text("x", encoding="utf-8")
        item = self._media_item(base / "source" / "IMG_20240101_120000.jpg", {"camera": "A"})
        item.source_path.parent.mkdir(parents=True, exist_ok=True)
        item.source_path.write_text("abcdefghij", encoding="utf-8")
        filename, write_mode = engine._build_target_filename(item, target_dir, 1)  # noqa: SLF001
        self.assertEqual(filename, "20240101_120000_RX100M3_0001.jpg")
        self.assertEqual(write_mode, "CONFLICT")

    def test_target_filename_uses_next_global_seq_for_same_date_directory(self) -> None:
        base = self._case_dir("global_seq_case")
        engine = OrganizerEngine(base)
        target_dir = base / "target"
        target_dir.mkdir()
        (target_dir / "20240101_090000_OLDCAM_0001.JPG").write_text("x", encoding="utf-8")
        item = self._media_item(base / "source" / "IMG_20240101_120000.jpg", {"camera": "A"})
        item.model_name = "NEWCAM"
        item.source_path.parent.mkdir(parents=True, exist_ok=True)
        item.source_path.write_text("abcdefghij", encoding="utf-8")

        filename, write_mode = engine._build_target_filename(item, target_dir, 1)  # noqa: SLF001

        self.assertEqual(filename, "20240101_120000_NEWCAM_0001.jpg")
        self.assertEqual(write_mode, "NEW")

    def test_build_mobile_output_path_uses_model_directory_name(self) -> None:
        base = self._case_dir("mobile_path_case")
        engine = OrganizerEngine(base)
        target_dir = base / "2024년" / "2024년 01월" / "20240101" / "20240101_RX100M3"
        mobile_path = engine._build_mobile_output_path(target_dir, "20240101_120000_RX100M3_0001.jpg")  # noqa: SLF001
        self.assertEqual(
            mobile_path,
            target_dir / "output_20240101_RX100M3" / "20240101_120000_RX100M3_0001.jpg",
        )

    def test_build_mobile_output_path_converts_heic_to_jpg(self) -> None:
        base = self._case_dir("mobile_heic_path_case")
        engine = OrganizerEngine(base)
        target_dir = base / "2024년" / "2024년 01월" / "20240101" / "20240101_RX100M3"
        mobile_path = engine._build_mobile_output_path(target_dir, "20240101_120000_RX100M3_0001.HEIC")  # noqa: SLF001
        self.assertEqual(
            mobile_path,
            target_dir / "output_20240101_RX100M3" / "20240101_120000_RX100M3_0001.JPG",
        )

    def test_build_mobile_output_path_converts_lowercase_heic_to_lowercase_jpg(self) -> None:
        base = self._case_dir("mobile_heic_lower_path_case")
        engine = OrganizerEngine(base)
        target_dir = base / "2024년" / "2024년 01월" / "20240101" / "20240101_RX100M3"
        mobile_path = engine._build_mobile_output_path(target_dir, "20240101_120000_RX100M3_0001.heic")  # noqa: SLF001
        self.assertEqual(
            mobile_path,
            target_dir / "output_20240101_RX100M3" / "20240101_120000_RX100M3_0001.jpg",
        )

    def test_target_filename_overwrites_when_metadata_matches(self) -> None:
        base = self._case_dir("overwrite_case")
        engine = OrganizerEngine(base)
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        source_file.write_text("abcdefghij", encoding="utf-8")

        source_item = self._media_item(source_file, {"camera": "A", "lens": "B"})
        target_dir = engine._build_target_directory(target, source_item.captured_at, source_item.model_name or "UNKNOWN")  # noqa: SLF001
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "20240101_120000_RX100M3_0001.JPG"
        target_file.write_text("1234567890", encoding="utf-8")
        target_item = self._media_item(target_file, {"camera": "A", "lens": "B"})
        engine.extractor.extract = lambda path: source_item if path == source_file else target_item  # type: ignore[method-assign]

        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=True)
        bundle = engine.preview(request)

        self.assertEqual(len(bundle.preview_items), 1)
        preview_item = bundle.preview_items[0]
        self.assertEqual(preview_item.target_path, str(target_dir / "20240101_120000_RX100M3_0001.jpg"))
        self.assertEqual(preview_item.write_mode, "OVERWRITE")
        self.assertEqual(preview_item.mobile_output_path, str(target_dir / "output_20240101_RX100M3" / "20240101_120000_RX100M3_0001.jpg"))

    def test_target_filename_uses_seq_when_metadata_differs(self) -> None:
        base = self._case_dir("seq_metadata_case")
        engine = OrganizerEngine(base)
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        source_file.write_text("abcdefghij", encoding="utf-8")

        source_item = self._media_item(source_file, {"camera": "A", "lens": "B"})
        target_dir = engine._build_target_directory(target, source_item.captured_at, source_item.model_name or "UNKNOWN")  # noqa: SLF001
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "20240101_120000_RX100M3_0001.JPG"
        target_file.write_text("1234567890", encoding="utf-8")
        target_item = self._media_item(target_file, {"camera": "A", "lens": "C"})
        engine.extractor.extract = lambda path: source_item if path == source_file else target_item  # type: ignore[method-assign]

        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=True)
        bundle = engine.preview(request)

        self.assertEqual(len(bundle.preview_items), 1)
        preview_item = bundle.preview_items[0]
        self.assertEqual(preview_item.target_path, str(target_dir / "20240101_120000_RX100M3_0001.jpg"))
        self.assertEqual(preview_item.write_mode, "CONFLICT")

    def test_target_directory_format(self) -> None:
        base = self._case_dir("dir_case")
        engine = OrganizerEngine(base)
        directory = engine._build_target_directory(base, datetime(2016, 10, 8, 1, 1, 34), "RX100M3")  # noqa: SLF001
        self.assertEqual(directory, base / "2016년" / "2016년 10월" / "20161008" / "20161008_RX100M3")

    def test_preview_uses_device_name_override(self) -> None:
        base = self._case_dir("device_override_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240115_183000.jpg"
        source_file.write_text("x", encoding="utf-8")
        engine = OrganizerEngine(base)
        existing_dir = engine._build_target_directory(target, datetime(2024, 1, 15, 18, 30, 0), "alpha_7c")  # noqa: SLF001
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "20240115_090000_OLDCAM_0001.JPG").write_text("y", encoding="utf-8")
        engine.extractor.extract = lambda path: MediaItem(  # type: ignore[method-assign]
            source_path=path,
            media_type="photo",
            extension=".jpg",
            captured_at=datetime(2024, 1, 15, 18, 30, 0),
            datetime_source="사진 메타",
            model_name="CAMA",
            model_source="사진 메타",
        )

        request = OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override="alpha 7c",
            operation_mode="copy",
            preview_only=True,
        )
        bundle = engine.preview(request)

        self.assertEqual(len(bundle.preview_items), 1)
        preview_item = bundle.preview_items[0]
        self.assertEqual(preview_item.model_name, "alpha_7c")
        self.assertEqual(preview_item.model_source, "사용자 입력")
        self.assertIn("20240115_183000_alpha_7c_0001.jpg", preview_item.target_path)

    def test_preview_includes_metadata_entries_for_detail_panel(self) -> None:
        base = self._case_dir("metadata_entries_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240115_183000.jpg"
        source_file.write_text("x" * 2048, encoding="utf-8")
        engine = OrganizerEngine(base)
        engine.extractor.extract = lambda path: MediaItem(  # type: ignore[method-assign]
            source_path=path,
            media_type="photo",
            extension=".jpg",
            captured_at=datetime(2024, 1, 15, 18, 30, 0),
            datetime_source="사진 메타",
            model_name="alpha_7c",
            model_source="사용자 입력",
            metadata={
                "media_info": {"width": 4032, "height": 3024},
                "display_metadata": {
                    "photo_make": "SONY",
                    "photo_model": "ILCE-7C",
                    "photo_datetime_original": "2024:01:15 18:30:00",
                },
                "source_metadata": {"exifread": {"Image Model": "ILCE-7C"}},
            },
        )

        bundle = engine.preview(
            OrganizeRequest(
                source_path=source,
                target_path=target,
                device_name_override="alpha_7c",
                operation_mode="copy",
                preview_only=True,
            )
        )

        preview_item = bundle.preview_items[0]
        metadata_map = dict(preview_item.metadata_entries)
        self.assertEqual(metadata_map["미디어 종류"], "사진")
        self.assertEqual(metadata_map["확장자"], ".jpg")
        self.assertEqual(metadata_map["원본 크기"], "4032 x 3024")
        self.assertEqual(metadata_map["일시 출처"], "사진 메타")
        self.assertEqual(metadata_map["모델명 출처"], "사용자 입력")
        self.assertEqual(metadata_map["EXIF Make"], "SONY")
        self.assertEqual(metadata_map["EXIF Model"], "ILCE-7C")

    def test_preview_assigns_compact_seq_per_date_with_multiple_times(self) -> None:
        base = self._case_dir("compact_seq_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_files = [
            source / "img_2024032710522454.jpg",
            source / "img_2024032711080155.jpg",
            source / "img_20240327170722454.jpg",
            source / "img_20240327170722510.jpg",
            source / "img_20240328204118167.jpg",
            source / "img_20240328204118294.jpg",
        ]
        for file_path in source_files:
            file_path.write_text(file_path.name, encoding="utf-8")

        engine = OrganizerEngine(base)
        request = OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override="kidsnote",
            operation_mode="copy",
            preview_only=True,
        )
        bundle = engine.preview(request)

        target_paths = [Path(item.target_path) for item in bundle.preview_items]
        march27 = sorted(path.name for path in target_paths if path.parent.parent.name == "20240327")
        march28 = sorted(path.name for path in target_paths if path.parent.parent.name == "20240328")

        self.assertEqual(
            march27,
            [
                "20240327_105224_kidsnote_0001.jpg",
                "20240327_110801_kidsnote_0002.jpg",
                "20240327_170722_kidsnote_0003.jpg",
                "20240327_170722_kidsnote_0004.jpg",
            ],
        )
        self.assertEqual(
            march28,
            [
                "20240328_204118_kidsnote_0001.jpg",
                "20240328_204118_kidsnote_0002.jpg",
            ],
        )

    def test_preview_assigns_seq_in_datetime_ascending_order(self) -> None:
        base = self._case_dir("datetime_order_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_files = [
            source / "img_20240327170722510.jpg",
            source / "img_2024032710522454.jpg",
            source / "img_2024032711080155.jpg",
            source / "img_20240327170722454.jpg",
        ]
        for file_path in source_files:
            file_path.write_text(file_path.name, encoding="utf-8")

        engine = OrganizerEngine(base)
        request = OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override="kidsnote",
            operation_mode="copy",
            preview_only=True,
        )
        bundle = engine.preview(request)

        per_source = {Path(item.source_path).name: Path(item.target_path).name for item in bundle.preview_items}
        self.assertEqual(per_source["img_2024032710522454.jpg"], "20240327_105224_kidsnote_0001.jpg")
        self.assertEqual(per_source["img_2024032711080155.jpg"], "20240327_110801_kidsnote_0002.jpg")
        self.assertEqual(per_source["img_20240327170722454.jpg"], "20240327_170722_kidsnote_0003.jpg")
        self.assertEqual(per_source["img_20240327170722510.jpg"], "20240327_170722_kidsnote_0004.jpg")

    def test_preview_adds_mobile_output_for_photos_and_videos(self) -> None:
        base = self._case_dir("mobile_preview_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        photo = source / "img_20240327170722454.jpg"
        video = source / "video_high_20240327175839245.mp4"
        photo.write_text("photo", encoding="utf-8")
        video.write_text("video", encoding="utf-8")

        engine = OrganizerEngine(base)
        request = OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override="kidsnote",
            operation_mode="copy",
            preview_only=True,
        )
        bundle = engine.preview(request)

        by_source = {Path(item.source_path).name: item for item in bundle.preview_items}
        self.assertTrue(by_source["img_20240327170722454.jpg"].mobile_output_enabled)
        self.assertIn("output_20240327_kidsnote", by_source["img_20240327170722454.jpg"].mobile_output_path)
        self.assertTrue(by_source["video_high_20240327175839245.mp4"].mobile_output_enabled)
        self.assertIn("output_20240327_kidsnote", by_source["video_high_20240327175839245.mp4"].mobile_output_path)
        self.assertTrue(by_source["video_high_20240327175839245.mp4"].mobile_output_path.endswith(".mp4"))

    def test_preview_groups_same_canonical_model_for_photo_and_video(self) -> None:
        base = self._case_dir("canonical_model_group_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        photo_path = source / "photo.jpg"
        video_path = source / "video.mp4"
        photo_path.write_text("photo", encoding="utf-8")
        video_path.write_text("video", encoding="utf-8")

        engine = OrganizerEngine(base)

        def fake_extract(path: Path) -> MediaItem:
            if path == photo_path:
                return MediaItem(
                    source_path=path,
                    media_type="photo",
                    extension=".jpg",
                    captured_at=datetime(2024, 5, 1, 11, 0, 0),
                    datetime_source="사진 메타",
                    model_name="Galaxy_Z_Fold6",
                    model_source="사진 메타",
                )
            return MediaItem(
                source_path=path,
                media_type="video",
                extension=".mp4",
                captured_at=datetime(2024, 5, 1, 11, 0, 5),
                datetime_source="영상 메타",
                model_name="GalaxyZFold6",
                model_source="영상 메타",
            )

        engine.extractor.extract = fake_extract  # type: ignore[method-assign]
        bundle = engine.preview(
            OrganizeRequest(
                source_path=source,
                target_path=target,
                operation_mode="copy",
                preview_only=True,
                mobile_output_enabled=False,
            )
        )

        by_source = {Path(item.source_path).name: item for item in bundle.preview_items}
        photo_item = by_source["photo.jpg"]
        video_item = by_source["video.mp4"]
        self.assertEqual(photo_item.model_name, "Galaxy_Z_Fold6")
        self.assertEqual(video_item.model_name, "Galaxy_Z_Fold6")
        self.assertIn("20240501_Galaxy_Z_Fold6", photo_item.target_path)
        self.assertIn("20240501_Galaxy_Z_Fold6", video_item.target_path)
        self.assertTrue(photo_item.target_path.endswith("20240501_110000_Galaxy_Z_Fold6_0001.jpg"))
        self.assertTrue(video_item.target_path.endswith("20240501_110005_Galaxy_Z_Fold6_0002.mp4"))

    def test_preview_keeps_compact_seq_and_marks_conflict_instead_of_skipping(self) -> None:
        base = self._case_dir("compact_conflict_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_files = [
            source / "img_2024032710522454.jpg",
            source / "img_2024032711080155.jpg",
            source / "img_20240327170722454.jpg",
            source / "img_20240327170722510.jpg",
        ]
        for file_path in source_files:
            file_path.write_text(file_path.name, encoding="utf-8")

        existing_dir = target / "2024년" / "2024년 03월" / "20240327" / "20240327_kidsnote"
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "20240327_170722_kidsnote_0003.JPG").write_text("occupied", encoding="utf-8")

        engine = OrganizerEngine(base)
        request = OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override="kidsnote",
            operation_mode="copy",
            preview_only=True,
        )
        bundle = engine.preview(request)

        by_name = {Path(item.target_path).name: item.write_mode for item in bundle.preview_items}
        self.assertEqual(by_name["20240327_105224_kidsnote_0001.jpg"], "NEW")
        self.assertEqual(by_name["20240327_110801_kidsnote_0002.jpg"], "NEW")
        self.assertEqual(by_name["20240327_170722_kidsnote_0003.jpg"], "CONFLICT")
        self.assertEqual(by_name["20240327_170722_kidsnote_0004.jpg"], "NEW")

    def test_scan_media_files_excludes_target_tree(self) -> None:
        base = self._case_dir("scan_case")
        source = base / "source"
        target = source / "target"
        source.mkdir()
        target.mkdir()
        (source / "IMG_20240115_183000.jpg").write_text("x", encoding="utf-8")
        (target / "20240115_183000_RX100M3_0001.JPG").write_text("y", encoding="utf-8")
        engine = OrganizerEngine(base)
        scanned = engine._scan_media_files(source, target)  # noqa: SLF001
        self.assertEqual(scanned, [source / "IMG_20240115_183000.jpg"])

    def test_preview_reports_progress(self) -> None:
        base = self._case_dir("progress_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        (source / "IMG_20240115_183000.jpg").write_text("x", encoding="utf-8")
        engine = OrganizerEngine(base)
        events: list[tuple[str, int, int]] = []
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=True)

        engine.preview(request, progress_callback=lambda message, current, total: events.append((message, current, total)))

        self.assertTrue(events)
        self.assertEqual(events[0], ("파일 스캔 중", 0, 0))
        self.assertEqual(events[-1], ("미리보기 완료", 1, 1))

    def test_execute_carries_write_mode_for_overwrite(self) -> None:
        base = self._case_dir("execute_overwrite_case")
        engine = OrganizerEngine(base)
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        source_file.write_text("abcdefghij", encoding="utf-8")

        source_item = self._media_item(source_file, {"camera": "A", "lens": "B"})
        target_dir = engine._build_target_directory(target, source_item.captured_at, source_item.model_name or "UNKNOWN")  # noqa: SLF001
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "20240101_120000_RX100M3_0001.JPG"
        target_file.write_text("1234567890", encoding="utf-8")
        target_item = self._media_item(target_file, {"camera": "A", "lens": "B"})
        engine.extractor.extract = lambda path: source_item if path == source_file else target_item  # type: ignore[method-assign]

        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False, mobile_output_enabled=False)
        bundle = engine.execute(request)

        self.assertEqual(len(bundle.execution_results), 1)
        result = bundle.execution_results[0]
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.write_mode, "OVERWRITE")
        self.assertEqual(result.target_path, str(target_dir / "20240101_120000_RX100M3_0001.jpg"))
        self.assertEqual(target_file.read_text(encoding="utf-8"), "abcdefghij")

    def test_execute_can_use_existing_preview_bundle_without_rebuilding_targets(self) -> None:
        base = self._case_dir("execute_cached_preview_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240115_183000.jpg"
        source_file.write_text("payload", encoding="utf-8")
        engine = OrganizerEngine(base)
        preview_media_item = MediaItem(
            source_path=source_file,
            media_type="photo",
            extension=".jpg",
            captured_at=datetime(2024, 1, 15, 18, 30, 0),
            datetime_source="파일명 fallback",
            model_name="kidsnote",
            model_source="사용자 입력",
            metadata={"source_metadata": {"camera": "A"}},
        )
        engine.extractor.extract = lambda path: copy.deepcopy(preview_media_item)  # type: ignore[method-assign]
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False, mobile_output_enabled=False)

        preview_bundle = engine.preview(request)
        self.assertEqual(
            preview_bundle.preview_items[0].target_path,
            str(target / "2024년" / "2024년 01월" / "20240115" / "20240115_kidsnote" / "20240115_183000_kidsnote_0001.jpg"),
        )

        existing_target = Path(preview_bundle.preview_items[0].target_path)
        existing_target.parent.mkdir(parents=True, exist_ok=True)
        existing_target.write_text("other", encoding="utf-8")
        changed_media_item = copy.deepcopy(preview_media_item)
        changed_media_item.metadata = {"source_metadata": {"camera": "B"}}
        engine.extractor.extract = lambda path: copy.deepcopy(changed_media_item)  # type: ignore[method-assign]

        bundle = engine.execute(request, preview_bundle=preview_bundle)

        self.assertEqual(bundle.execution_results[0].target_path, preview_bundle.preview_items[0].target_path)
        self.assertTrue(Path(bundle.execution_results[0].target_path).exists())

    @unittest.skipIf(Image is None, "Pillow 미설치 환경")
    def test_execute_creates_mobile_output_for_photo(self) -> None:
        base = self._case_dir("mobile_execute_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        Image.new("RGB", (4000, 2000), color=(20, 40, 60)).save(source_file, format="JPEG", quality=95)

        engine = OrganizerEngine(base)
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
        bundle = engine.execute(request)

        self.assertEqual(len(bundle.execution_results), 1)
        result = bundle.execution_results[0]
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.mobile_output_status, "SUCCESS")
        self.assertTrue(Path(result.mobile_output_path).exists())
        output_stat = Path(result.mobile_output_path).stat()
        expected_time = datetime(2024, 1, 1, 12).timestamp()
        self.assertAlmostEqual(output_stat.st_mtime, expected_time, delta=0.001)
        if sys.platform == "win32":
            self.assertAlmostEqual(output_stat.st_birthtime, expected_time, delta=0.001)
        with Image.open(result.mobile_output_path) as output_image:
            self.assertEqual(output_image.width, 3000)
            self.assertEqual(output_image.height, 1500)

    def test_build_mobile_output_path_converts_video_to_mp4(self) -> None:
        base = self._case_dir("mobile_video_path_case")
        engine = OrganizerEngine(base)
        target_dir = base / "2024년" / "2024년 01월" / "20240101" / "20240101_RX100M3"
        mobile_path = engine._build_mobile_output_path(target_dir, "20240101_120000_RX100M3_0001.MOV")  # noqa: SLF001
        self.assertEqual(
            mobile_path,
            target_dir / "output_20240101_RX100M3" / "20240101_120000_RX100M3_0001.mp4",
        )

    def test_execute_creates_mobile_output_for_video(self) -> None:
        base = self._case_dir("mobile_video_execute_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "video_high_20240327175839245.mp4"
        source_file.write_bytes(b"video")

        engine = OrganizerEngine(base)
        expected_bytes = b"compressed-video"

        def fake_create(source_path: Path, target_path: Path, max_width: int, quality: str, only_if_smaller: bool, **options) -> str:
            self.assertEqual(source_path, source_file)
            self.assertEqual(max_width, 1280)
            self.assertEqual(quality, "balanced")
            self.assertTrue(only_if_smaller)
            self.assertEqual(options.get("encoder"), "auto")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(expected_bytes)
            return "SUCCESS"

        with patch("photo_organizer.engine.create_mobile_video_output", side_effect=fake_create):
            bundle = engine.execute(
                OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
            )

        self.assertEqual(len(bundle.execution_results), 1)
        result = bundle.execution_results[0]
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.mobile_output_status, "SUCCESS")
        self.assertTrue(Path(result.mobile_output_path).exists())
        self.assertEqual(Path(result.mobile_output_path).suffix, ".mp4")
        self.assertEqual(Path(result.mobile_output_path).read_bytes(), expected_bytes)
        output_stat = Path(result.mobile_output_path).stat()
        expected_time = datetime(2024, 3, 27, 17, 58, 39).timestamp()
        self.assertAlmostEqual(output_stat.st_mtime, expected_time, delta=0.001)
        if sys.platform == "win32":
            self.assertAlmostEqual(output_stat.st_birthtime, expected_time, delta=0.001)

    def test_execute_marks_video_mobile_output_skipped(self) -> None:
        base = self._case_dir("mobile_video_skip_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "video_high_20240327175839245.mp4"
        source_file.write_bytes(b"video")

        engine = OrganizerEngine(base)
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
        preview = engine.preview(request)
        existing = Path(preview.preview_items[0].mobile_output_path)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"existing output")
        before = existing.stat()

        with patch("photo_organizer.engine.create_mobile_video_output", return_value="SKIPPED"):
            bundle = engine.execute(
                request, preview_bundle=preview
            )

        self.assertEqual(bundle.execution_results[0].mobile_output_status, "SKIPPED")
        self.assertEqual(existing.read_bytes(), b"existing output")
        self.assertEqual(existing.stat().st_mtime_ns, before.st_mtime_ns)
        if sys.platform == "win32":
            self.assertEqual(existing.stat().st_birthtime, before.st_birthtime)

    def test_target_filename_preserves_uppercase_extension(self) -> None:
        base = self._case_dir("uppercase_ext_case")
        engine = OrganizerEngine(base)
        item = self._media_item(base / "source" / "IMG_20240101_120000.JPG", {"camera": "A"})
        filename, write_mode = engine._build_target_filename(item, base / "target", 1)  # noqa: SLF001
        self.assertEqual(filename, "20240101_120000_RX100M3_0001.JPG")
        self.assertEqual(write_mode, "NEW")

    def test_target_filename_preserves_mixed_case_extension(self) -> None:
        base = self._case_dir("mixed_ext_case")
        engine = OrganizerEngine(base)
        item = self._media_item(base / "source" / "IMG_20240101_120000.JpG", {"camera": "A"})
        filename, write_mode = engine._build_target_filename(item, base / "target", 1)  # noqa: SLF001
        self.assertEqual(filename, "20240101_120000_RX100M3_0001.JpG")
        self.assertEqual(write_mode, "NEW")

    @unittest.skipIf(Image is None, "Pillow 미설치 환경")
    def test_execute_mobile_output_keeps_smaller_original_size(self) -> None:
        base = self._case_dir("mobile_small_photo_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        Image.new("RGB", (1200, 800), color=(20, 40, 60)).save(source_file, format="JPEG", quality=95)

        engine = OrganizerEngine(base)
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
        bundle = engine.execute(request)

        with Image.open(bundle.execution_results[0].mobile_output_path) as output_image:
            self.assertEqual(output_image.width, 1200)
            self.assertEqual(output_image.height, 800)

    @unittest.skipIf(Image is None or piexif is None, "Pillow/piexif 미설치 환경")
    def test_execute_mobile_output_preserves_jpeg_exif(self) -> None:
        base = self._case_dir("mobile_exif_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.jpg"
        exif_dict = {
            "0th": {
                piexif.ImageIFD.Make: b"NIKON",
                piexif.ImageIFD.Model: b"D700",
                piexif.ImageIFD.DateTime: b"2024:01:01 12:00:00",
            },
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2024:01:01 12:00:00",
                piexif.ExifIFD.DateTimeDigitized: b"2024:01:01 12:00:00",
            },
        }
        Image.new("RGB", (4200, 2100), color=(20, 40, 60)).save(source_file, format="JPEG", quality=95, exif=piexif.dump(exif_dict))

        engine = OrganizerEngine(base)
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
        bundle = engine.execute(request)

        source_item = engine.extractor.extract(source_file)
        mobile_item = engine.extractor.extract(Path(bundle.execution_results[0].mobile_output_path))
        self.assertEqual(
            mobile_item.metadata.get("source_metadata", {}).get("exifread", {}).get("Image Make"),
            source_item.metadata.get("source_metadata", {}).get("exifread", {}).get("Image Make"),
        )
        self.assertEqual(
            mobile_item.metadata.get("source_metadata", {}).get("exifread", {}).get("Image Model"),
            source_item.metadata.get("source_metadata", {}).get("exifread", {}).get("Image Model"),
        )
        self.assertEqual(mobile_item.datetime_source, "사진 메타")
        self.assertEqual(mobile_item.model_name, "D700")
        self.assertEqual(mobile_item.captured_at, source_item.captured_at)
        self.assertAlmostEqual(Path(bundle.execution_results[0].mobile_output_path).stat().st_mtime,
                               source_item.captured_at.timestamp(), delta=0.001)

    @unittest.skipIf(Image is None or PngImagePlugin is None, "Pillow 미설치 환경")
    def test_execute_mobile_output_preserves_png_text_metadata(self) -> None:
        base = self._case_dir("mobile_png_meta_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        source_file = source / "IMG_20240101_120000.png"
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("Description", "sample")
        Image.new("RGBA", (1200, 800), color=(20, 40, 60, 255)).save(source_file, format="PNG", pnginfo=pnginfo)

        engine = OrganizerEngine(base)
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)
        bundle = engine.execute(request)

        with Image.open(bundle.execution_results[0].mobile_output_path) as output_image:
            self.assertEqual(output_image.info.get("Description"), "sample")

    def test_execute_stops_when_mobile_output_fails(self) -> None:
        base = self._case_dir("mobile_fail_stop_case")
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()
        first = source / "IMG_20240101_120000.jpg"
        second = source / "IMG_20240101_120100.jpg"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")

        engine = OrganizerEngine(base)
        engine._create_mobile_output = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mobile fail"))  # type: ignore[method-assign]
        request = OrganizeRequest(source_path=source, target_path=target, operation_mode="copy", preview_only=False)

        bundle = engine.execute(request)

        self.assertEqual(len(bundle.execution_results), 1)
        self.assertEqual(bundle.execution_results[0].status, "ERROR")
        self.assertEqual(bundle.execution_results[0].mobile_output_status, "ERROR")


if __name__ == "__main__":
    unittest.main()
