import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import os

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.config import ConfigManager
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import AppSettings, ExecutionBundle, ExecutionResult, PreviewBundle, PreviewItem
from photo_organizer.video_thumbnail import extract_video_thumbnail_bytes

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
except Exception:
    QApplication = None


class VideoThumbnailTests(unittest.TestCase):
    def test_extract_video_thumbnail_bytes_returns_stdout(self) -> None:
        sample = b"png-bytes"

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            command = args[0]
            self.assertEqual(command[0], "ffmpeg")
            self.assertIn("-i", command)
            self.assertIn("sample.mp4", command)
            self.assertIn("image2pipe", command)
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=sample, stderr=b"")

        with patch("photo_organizer.video_thumbnail.subprocess.run", side_effect=fake_run):
            result = extract_video_thumbnail_bytes(Path("sample.mp4"), max_width=480, seek_seconds=1)

        self.assertEqual(result, sample)

    def test_extract_video_thumbnail_bytes_returns_none_on_failure(self) -> None:
        with patch("photo_organizer.video_thumbnail.subprocess.run", side_effect=FileNotFoundError):
            result = extract_video_thumbnail_bytes(Path("sample.mp4"))

        self.assertIsNone(result)


@unittest.skipIf(QApplication is None, "PySide6 미설치 환경")
class VideoThumbnailUiTests(unittest.TestCase):
    def setUp(self) -> None:
        for method in ("_confirm_job_transition", "_restore_recent_job", "_autosave_job"):
            fixture = patch(f"photo_organizer.ui.main_window.MainWindow.{method}", new=(lambda self: True) if method == "_confirm_job_transition" else (lambda self: None), create=True)
            fixture.start()
            self.addCleanup(fixture.stop)

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _case_dir(self, name: str) -> Path:
        base = Path(__file__).resolve().parents[1] / ".tmp_test" / name
        base.mkdir(parents=True, exist_ok=True)
        return base

    def test_window_title_shows_version_and_release_date(self) -> None:
        from photo_organizer.ui.main_window import MainWindow
        from photo_organizer import __version__, __release_date__
        base = self._case_dir("version_title")
        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        self.assertEqual(window.windowTitle(), f"PhotoOrganizer {__version__} ({__release_date__})")
        self.assertEqual(__version__, "1.0.1.15")
        self.assertEqual(__release_date__, "2026-10-11")
        import tomllib
        project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], __version__)
        window.close()

    def test_settings_dialog_saves_inference_minutes(self) -> None:
        from photo_organizer.ui.main_window import SettingsDialog
        current = AppSettings(video_model_window_minutes=10)
        dialog = SettingsDialog(None, current)
        self.assertEqual(dialog.video_model_window_spin.value(), 10)
        dialog.video_model_window_spin.setValue(20)
        self.assertEqual(dialog.to_settings(current).video_model_window_minutes, 20)

    def test_only_new_filename_is_editable_and_updates_bundle(self) -> None:
        from PySide6.QtCore import Qt
        base = self._case_dir("manual_filename_ui")
        source = base / "source" / "sample.mp4"
        with patch("photo_organizer.ui.main_window.extract_video_thumbnail_bytes", return_value=None):
            window = self._window_with_preview_item(source)
            self.assertTrue(window.preview_table.item(0, 3).flags() & Qt.ItemIsEditable)
            self.assertFalse(window.preview_table.item(0, 0).flags() & Qt.ItemIsEditable)
            window.preview_table.item(0, 3).setText("custom.mp4")
            item = window.last_preview_bundle.preview_items[0]
            self.assertEqual(item.new_filename, "custom.mp4")
            self.assertEqual(Path(item.target_path).name, "custom.mp4")
            self.assertTrue(item.filename_edited)
            self.assertEqual(window.preview_table.item(0, 1).text(), item.target_path)
            window.close()

    def test_unknown_preview_row_has_light_red_background(self) -> None:
        from PySide6.QtCore import Qt
        base = self._case_dir("unknown_row_color_ui")
        with patch("photo_organizer.ui.main_window.extract_video_thumbnail_bytes", return_value=None):
            window = self._window_with_preview_item(base / "source" / "sample.mp4")
            item = window.last_preview_bundle.preview_items[0]
            item.model_name = "UNKNOWN"
            item.model_source = "UNKNOWN"
            window._fill_preview_table([item])
            for column in range(window.preview_table.columnCount()):
                self.assertEqual(window.preview_table.item(0, column).background().color().name(), "#fff0f0")
            item.model_name = "CAM"
            window._fill_preview_table([item])
            for column in range(window.preview_table.columnCount()):
                self.assertEqual(window.preview_table.item(0, column).background().style(), Qt.NoBrush)
            window.close()

    def test_execute_uses_edited_cached_preview(self) -> None:
        from photo_organizer.ui.main_window import MainWindow
        import tempfile
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        base = self._case_dir("edited_cached_execute_ui")
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        source = base / "source"
        source.mkdir(exist_ok=True)
        original = source / "20240501_125303.jpg"
        original.write_bytes(b"original")
        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.settings.mobile_output_enabled = False
        window.source_edit.setText(str(source))
        window.target_edit.setText(str(base / "target"))
        window._handle_preview()
        window.show()
        self.app.processEvents()
        window.preview_table.editItem(window.preview_table.item(0, 3))
        editor = window.preview_table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setText("custom.jpg")
        edited_path = Path(window.last_preview_bundle.preview_items[0].target_directory) / "custom.jpg"
        with patch.object(window.engine, "preview", side_effect=AssertionError("must keep edited preview")):
            QTest.mouseClick(window.execute_button, Qt.LeftButton)
        self.assertTrue(edited_path.exists())
        self.assertEqual(edited_path.read_bytes(), b"original")
        window.close()

    def test_settings_change_does_not_silently_discard_filename_edits(self) -> None:
        from photo_organizer.ui.main_window import MainWindow
        import tempfile
        base = self._case_dir("edited_settings_changed_ui")
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        source = base / "source"
        source.mkdir(exist_ok=True)
        (source / "20240501_125303.jpg").write_bytes(b"original")
        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.settings.mobile_output_enabled = False
        window.source_edit.setText(str(source))
        window.target_edit.setText(str(base / "target"))
        window._handle_preview()
        window.preview_table.item(0, 3).setText("custom.jpg")
        window.settings.video_model_window_minutes = 10
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning, patch.object(window.engine, "execute") as execute:
            window._handle_execute()
        warning.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(window.last_preview_bundle.preview_items[0].new_filename, "custom.jpg")
        window.close()

    def _window_with_preview_item(self, source_path: Path):
        from photo_organizer.ui.main_window import MainWindow

        base = source_path.parents[1]
        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        preview_item = PreviewItem(
            item_id=str(source_path),
            media_type="video",
            source_path=str(source_path),
            target_directory=str(base / "target"),
            target_path=str(base / "target" / source_path.name),
            new_filename=source_path.name,
            write_mode="NEW",
            captured_at="2024-01-01 12:00:00",
            datetime_source="영상 메타",
            model_name="CAM",
            model_source="영상 메타",
            warnings=[],
        )
        window.last_preview_bundle = PreviewBundle(preview_items=[preview_item])
        window._fill_preview_table([preview_item])
        window.preview_table.selectRow(0)
        return window

    def test_video_thumbnail_is_displayed_in_preview_panel(self) -> None:
        base = self._case_dir("video_thumb_ui_success")
        source = base / "source"
        source.mkdir(exist_ok=True)
        video = source / "sample.mp4"
        video.write_bytes(b"video")
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        window = self._window_with_preview_item(video)

        with patch("photo_organizer.ui.main_window.extract_video_thumbnail_bytes", return_value=png_bytes):
            window._update_selection_detail("preview")

        self.assertIsNotNone(window.preview_image_view.pixmap())
        self.assertEqual(window.preview_image_view.text(), "")
        self.assertIn("영상 썸네일", window.preview_image_info.text())

    def test_video_thumbnail_failure_keeps_placeholder(self) -> None:
        base = self._case_dir("video_thumb_ui_fail")
        source = base / "source"
        source.mkdir(exist_ok=True)
        video = source / "sample.mp4"
        video.write_bytes(b"video")
        window = self._window_with_preview_item(video)

        with patch("photo_organizer.ui.main_window.extract_video_thumbnail_bytes", return_value=None):
            window._update_selection_detail("preview")

        self.assertIn("영상 썸네일을 추출하지 못했습니다", window.preview_image_view.text())
        self.assertEqual(window.preview_image_info.text(), str(video))

    def test_preview_selection_populates_metadata_table(self) -> None:
        base = self._case_dir("preview_metadata_ui")
        source = base / "source"
        source.mkdir(exist_ok=True)
        image = source / "sample.jpg"
        image.write_bytes(b"image")
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        preview_item = PreviewItem(
            item_id=str(image),
            media_type="photo",
            source_path=str(image),
            target_directory=str(base / "target"),
            target_path=str(base / "target" / image.name),
            new_filename=image.name,
            write_mode="NEW",
            captured_at="2024-01-01 12:00:00",
            datetime_source="파일명 fallback",
            model_name="kidsnote",
            model_source="사용자 입력",
            warnings=[],
            metadata_entries=[
                ("미디어 종류", "사진"),
                ("확장자", ".jpg"),
                ("원본 크기", "4032 x 3024"),
            ],
        )
        window.last_preview_bundle = PreviewBundle(preview_items=[preview_item])
        window._fill_preview_table([preview_item])
        window.preview_table.selectRow(0)
        window._update_selection_detail("preview")

        self.assertEqual(window.selection_metadata_table.rowCount(), 3)
        self.assertEqual(window.selection_metadata_table.item(0, 0).text(), "미디어 종류")
        self.assertEqual(window.selection_metadata_table.item(0, 1).text(), "사진")
        self.assertEqual(window.selection_metadata_table.item(2, 1).text(), "4032 x 3024")

    def test_device_name_hint_shows_override_state_from_saved_settings(self) -> None:
        base = self._case_dir("device_name_hint_ui")
        ConfigManager(base).save(
            AppSettings(
                source_path="",
                target_path="",
                device_name_override="kidsnote",
                operation_mode="copy",
            )
        )
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))

        self.assertIn("override 활성화", window.device_name_hint.text())
        self.assertIn("kidsnote", window.device_name_hint.text())

    def test_device_name_hint_updates_when_override_is_cleared(self) -> None:
        base = self._case_dir("device_name_hint_clear_ui")
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.device_name_edit.setText("kidsnote")
        self.assertIn("override 활성화", window.device_name_hint.text())

        window.device_name_edit.clear()

        self.assertIn("자동 추출", window.device_name_hint.text())

    def test_mobile_output_summary_includes_video_profile(self) -> None:
        base = self._case_dir("mobile_output_summary_ui")
        ConfigManager(base).save(
            AppSettings(
                source_path="",
                target_path="",
                device_name_override="",
                operation_mode="copy",
                mobile_output_video_max_width=1920,
                mobile_output_video_quality="small",
            )
        )
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))

        self.assertIn("사진 3000px 품질 75", window.mobile_output_summary.text())
        self.assertIn("동영상 MP4 1920px 최대 용량 절약", window.mobile_output_summary.text())
        self.assertIn("CRF 28 / 오디오 96 kbps", window.mobile_output_summary.text())

    def test_results_selection_uses_source_metadata_by_default(self) -> None:
        base = self._case_dir("results_metadata_source")
        source = base / "source"
        target = base / "target"
        source.mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        source_file = source / "sample.jpg"
        target_file = target / "sample.jpg"
        source_file.write_bytes(b"source")
        target_file.write_bytes(b"target")
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.engine.describe_media_path = lambda path: [("기준", path.name)]  # type: ignore[method-assign]
        result_item = ExecutionResult(
            source_path=str(source_file),
            target_path=str(target_file),
            status="SUCCESS",
            action="copy",
            write_mode="NEW",
            message="NEW",
        )
        window.last_execution_bundle = ExecutionBundle(
            preview_items=[],
            execution_results=[result_item],
        )
        window._fill_results_table([result_item])
        window.results_table.selectRow(0)
        window._update_selection_detail("results")

        self.assertIn("상세 기준: 원본 파일", window.selection_detail.toPlainText())
        self.assertEqual(window.selection_metadata_table.item(0, 1).text(), "sample.jpg")

    def test_results_target_click_switches_detail_to_target_file(self) -> None:
        base = self._case_dir("results_metadata_target")
        source = base / "source"
        target = base / "target"
        source.mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        source_file = source / "sample_source.jpg"
        target_file = target / "sample_target.jpg"
        source_file.write_bytes(b"source")
        target_file.write_bytes(b"target")
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.engine.describe_media_path = lambda path: [("기준", path.name)]  # type: ignore[method-assign]
        result_item = ExecutionResult(
            source_path=str(source_file),
            target_path=str(target_file),
            status="SUCCESS",
            action="copy",
            write_mode="NEW",
            message="NEW",
        )
        window.last_execution_bundle = ExecutionBundle(
            preview_items=[],
            execution_results=[result_item],
        )
        window._fill_results_table([result_item])
        window.results_table.selectRow(0)
        target_cell = window.results_table.item(0, 4)
        assert target_cell is not None
        window._handle_results_item_clicked(target_cell)

        self.assertIn("상세 기준: 대상 파일", window.selection_detail.toPlainText())
        self.assertEqual(window.selection_metadata_table.item(0, 1).text(), "sample_target.jpg")

    def test_results_mobile_output_path_click_switches_detail_to_mobile_output_file(self) -> None:
        base = self._case_dir("results_metadata_mobile_output")
        source = base / "source"
        target = base / "target"
        output = target / "output"
        source.mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        output.mkdir(exist_ok=True)
        source_file = source / "sample_source.jpg"
        target_file = target / "sample_target.jpg"
        mobile_output_file = output / "sample_output.jpg"
        source_file.write_bytes(b"source")
        target_file.write_bytes(b"target")
        mobile_output_file.write_bytes(b"mobile")
        from photo_organizer.ui.main_window import MainWindow

        window = MainWindow(OrganizerEngine(base), ConfigManager(base))
        window.engine.describe_media_path = lambda path: [("기준", path.name)]  # type: ignore[method-assign]
        result_item = ExecutionResult(
            source_path=str(source_file),
            target_path=str(target_file),
            status="SUCCESS",
            action="copy",
            write_mode="NEW",
            message="NEW",
            mobile_output_path=str(mobile_output_file),
            mobile_output_status="SUCCESS",
        )
        window.last_execution_bundle = ExecutionBundle(
            preview_items=[],
            execution_results=[result_item],
        )
        window._fill_results_table([result_item])
        window.results_table.selectRow(0)
        mobile_output_cell = window.results_table.item(0, 6)
        assert mobile_output_cell is not None
        window._handle_results_item_clicked(mobile_output_cell)

        self.assertIn("상세 기준: 모바일 출력 파일", window.selection_detail.toPlainText())
        self.assertEqual(window.selection_metadata_table.item(0, 1).text(), "sample_output.jpg")


if __name__ == "__main__":
    unittest.main()
