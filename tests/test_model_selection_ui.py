import importlib.util
import os
from pathlib import Path
from datetime import datetime
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication
from photo_organizer.models import AppSettings, OrganizeRequest, ExecutionBundle
from photo_organizer.ui.main_window import MainWindow


class ModelSelectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Job persistence is covered by test_job_ui; these fixtures use partial media objects.
        for method in ("_confirm_job_transition", "_restore_recent_job", "_autosave_job", "_write_recent_job"):
            fixture = patch(f"photo_organizer.ui.main_window.MainWindow.{method}", new=(lambda self: True) if method == "_confirm_job_transition" else (lambda self: None))
            fixture.start()
            self.addCleanup(fixture.stop)
        self.config = Mock()
        self.config.load.return_value = AppSettings(mobile_output_enabled=False)
        self.engine = Mock()
        self.window = MainWindow(self.engine, self.config)
        self.addCleanup(self.window.close)
        self.window.source_edit.setText("source")
        self.window.target_edit.setText("target")
        self.request = OrganizeRequest(Path("source"), Path("target"), mobile_output_enabled=False)
        self.window._build_request = Mock(return_value=self.request)
        self.engine.preview.side_effect = self.bundle
        self.engine.set_selected_models.side_effect = self.select

    @staticmethod
    def bundle(*args, **kwargs):
        items = []
        for index, (model, kind) in enumerate((("CAM_A", "photo"), ("CAM_A", "video"), ("CAM_B", "photo"), ("UNKNOWN", "video"))):
            items.append(SimpleNamespace(item_id=str(index), media_type=kind, source_path=f"source/{index}.jpg", target_directory="target/date/model", target_path=f"target/{index}.jpg", new_filename=f"{index}.jpg", write_mode="NEW", captured_at="2024-01-01", datetime_source="메타", model_name=model, model_source="메타", warnings=[], metadata_entries=[], filename_edited=False, included=True, mobile_output_enabled=False, mobile_output_path=""))
        return SimpleNamespace(preview_items=items, error_items=[], log_events=[], selection_applied=False)

    @staticmethod
    def select(bundle, selected):
        for item in bundle.preview_items:
            item.included = item.model_name in selected
        bundle.selection_applied = True

    def preview(self):
        self.window._handle_preview()
        self.assertTrue(hasattr(self.window, "model_selection_panel"))
        return self.window.model_selection_panel

    def test_panel_lists_model_counts_and_wraps(self):
        self.assertIsNotNone(importlib.util.find_spec("photo_organizer.ui.model_selection"))
        panel = self.preview()
        self.assertEqual(panel.title_label.text(), "처리할 모델")
        self.assertEqual(set(panel.checkboxes), {"CAM_A", "CAM_B", "UNKNOWN"})
        self.assertTrue(all(box.isChecked() for box in panel.checkboxes.values()))
        self.assertIn("사진 1", panel.checkboxes["CAM_A"].text())
        self.assertIn("영상 1", panel.checkboxes["CAM_A"].text())
        self.assertGreater(panel.flow_layout.heightForWidth(180), panel.flow_layout.heightForWidth(1400))
        self.assertIs(self.window.tabs.widget(0), self.window.preview_tab)

    def test_excluded_rows_are_grey_noneditable_and_new_preview_resets_all(self):
        panel = self.preview()
        panel.checkboxes["CAM_B"].setChecked(False)
        self.engine.set_selected_models.assert_called_once()
        cell = self.window.preview_table.item(2, 3)
        self.assertEqual(self.window.preview_table.item(2, 2).text(), "제외")
        self.assertEqual(cell.background().color().name(), "#f1f1f1")
        self.assertFalse(cell.flags() & Qt.ItemIsEditable)
        self.assertIn("처리 3", panel.summary_label.text())
        self.assertIn("제외 1", panel.summary_label.text())
        self.assertEqual(self.window.preview_table.item(3, 0).background().color().name(), "#fff0f0")
        panel = self.preview()
        self.assertTrue(panel.checkboxes["CAM_B"].isChecked())
        self.assertTrue(all(item.included for item in self.window.last_preview_bundle.preview_items))

    def test_none_selected_blocks_execute_and_busy_execution_locks_controls(self):
        panel = self.preview()
        for checkbox in panel.checkboxes.values():
            checkbox.setChecked(False)
        with patch("photo_organizer.ui.main_window.QMessageBox.information") as notice:
            self.window._handle_execute()
            notice.assert_called_once()
        self.engine.execute.assert_not_called()
        self.window._set_busy(True)
        self.assertFalse(panel.isEnabled())
        self.window.last_execution_bundle = SimpleNamespace()
        self.window._set_busy(False)
        self.assertFalse(panel.isEnabled())

    def test_stale_input_change_cannot_select_or_rescan_with_previous_exclusions(self):
        panel = self.preview()
        panel.checkboxes["CAM_B"].setChecked(False)
        self.window.target_edit.setText("different-target")
        self.window._build_request.return_value = OrganizeRequest(Path("source"), Path("different-target"), mobile_output_enabled=False)
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            panel.checkboxes["UNKNOWN"].setChecked(False)
            self.assertTrue(panel.checkboxes["UNKNOWN"].isChecked())
            self.window._handle_execute()
            self.assertEqual(warning.call_count, 2)
        self.engine.execute.assert_not_called()
        self.assertEqual(self.engine.set_selected_models.call_count, 1)
        self.assertEqual(self.window._build_request.call_count, 1)

    def test_execute_passes_selected_cached_bundle_and_locks_panel(self):
        panel = self.preview()
        panel.checkboxes["CAM_B"].setChecked(False)
        preview = self.window.last_preview_bundle
        self.engine.execute.return_value = ExecutionBundle(preview_items=preview.preview_items)
        self.window._handle_execute()
        self.assertIs(self.engine.execute.call_args.kwargs["preview_bundle"], preview)
        self.assertEqual([item.model_name for item in preview.preview_items if item.included], ["CAM_A", "CAM_A", "UNKNOWN"])
        self.assertFalse(panel.isEnabled())

    def test_execute_without_previous_preview_keeps_direct_execution(self):
        self.engine.execute.return_value = ExecutionBundle(preview_items=self.bundle().preview_items)
        self.window._handle_execute()
        self.assertIs(self.engine.execute.call_args.kwargs["preview_bundle"], self.window.last_preview_bundle)
        self.assertTrue(all(item.included for item in self.window.last_preview_bundle.preview_items))
        self.assertFalse(self.window.model_selection_panel.isEnabled())

    def test_failed_selection_restores_checkboxes_and_reports_failure(self):
        panel = self.preview()
        self.engine.set_selected_models.side_effect = ValueError("collision")
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            panel.checkboxes["CAM_B"].setChecked(False)
            warning.assert_called_once()
        self.assertTrue(panel.checkboxes["CAM_B"].isChecked())
        self.assertIn("선택 실패", self.window.status_label.text())

    def test_flow_geometry_actually_wraps_model_checkboxes(self):
        panel = self.preview()
        panel.resize(260, 240)
        panel.show()
        self.app.processEvents()
        panel.flow_layout.setGeometry(QRect(0, 0, 260, 240))
        rows = {box.geometry().y() for box in panel.checkboxes.values()}
        self.assertGreater(len(rows), 1)
        panel.flow_layout.setGeometry(QRect(0, 0, 1400, 240))
        self.assertEqual(len({box.geometry().y() for box in panel.checkboxes.values()}), 1)

    def test_real_engine_executes_only_selected_model_without_metadata_rescan(self):
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import MediaItem
        base = Path(__file__).resolve().parents[1] / ".tmp_test"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            first, second = source / "first.jpg", source / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            engine = OrganizerEngine(root)
            engine.extractor.extract = Mock(side_effect=lambda path: MediaItem(path, "photo", ".jpg", datetime(2024, 1, 1, 12), "사진 메타", "CAM_A" if path == first else "CAM_B", "사진 메타"))
            config = Mock()
            config.load.return_value = AppSettings(source_path=str(source), target_path=str(target), mobile_output_enabled=False)
            window = MainWindow(engine, config)
            try:
                window._handle_preview()
                window.model_selection_panel.checkboxes["CAM_B"].setChecked(False)
                self.assertEqual(engine.extractor.extract.call_count, 2)
                window._handle_execute()
                self.assertEqual(engine.extractor.extract.call_count, 2)
                self.assertEqual(len(window.last_execution_bundle.execution_results), 1)
                output = Path(window.last_execution_bundle.execution_results[0].target_path)
                self.assertEqual(output.read_bytes(), b"first")
                self.assertEqual(len(list(target.rglob("*.jpg"))), 1)
                self.assertTrue(first.exists())
                self.assertTrue(second.exists())
                self.assertFalse(window.model_selection_panel.isEnabled())
            finally:
                window.close()

