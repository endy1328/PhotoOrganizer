import os
from pathlib import Path
from datetime import datetime
import tempfile
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog, QTableWidgetItem, QLineEdit
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import MainWindow, SettingsDialog
from photo_organizer.ui.model_selection import ModelSelectionPanel


class ModelMappingUiTests(unittest.TestCase):
    def setUp(self):
        for method in ("_confirm_job_transition", "_restore_recent_job", "_autosave_job"):
            fixture=patch(f"photo_organizer.ui.main_window.MainWindow.{method}",new=(lambda self: True) if method == "_confirm_job_transition" else (lambda self: None),create=True)
            fixture.start()
            self.addCleanup(fixture.stop)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        dialog = SettingsDialog(None, AppSettings())
        self.addCleanup(dialog.close)
        self.assertTrue(hasattr(dialog, "mapping_table"))
        return dialog

    def test_mapping_table_add_edit_delete_scope_and_restore_defaults(self):
        dialog = self.dialog()
        dialog._add_model_mapping_row()
        dialog.mapping_table.setItem(0, 0, QTableWidgetItem("SM-F926N"))
        dialog.mapping_table.setItem(0, 1, QTableWidgetItem("아빠 폰"))
        scope = dialog.model_mapping_scope_combo
        scope.setCurrentIndex(scope.findData("filename_only"))
        settings = dialog.to_settings(AppSettings())
        self.assertEqual(settings.model_name_mappings, {"SM-F926N": "아빠_폰"})
        self.assertEqual(settings.model_mapping_scope, "filename_only")
        dialog.mapping_table.selectRow(0)
        dialog._delete_model_mapping_rows()
        self.assertEqual(dialog.mapping_table.rowCount(), 0)
        dialog._add_model_mapping_row()
        dialog._restore_defaults()
        self.assertEqual(dialog.mapping_table.rowCount(), 0)
        self.assertEqual(scope.currentData(), "filename_and_folders")
        self.assertTrue(dialog.settings_scroll.widgetResizable())

    def test_invalid_mapping_prevents_ok_and_duplicate_originals_are_rejected(self):
        dialog = self.dialog()
        for source, alias in (("SM-F926N", "Family"), ("sm_f926n", "Other")):
            row = dialog.mapping_table.rowCount()
            dialog._add_model_mapping_row()
            dialog.mapping_table.setItem(row, 0, QTableWidgetItem(source))
            dialog.mapping_table.setItem(row, 1, QTableWidgetItem(alias))
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        dialog.mapping_table.removeRow(1)
        dialog.mapping_table.item(0, 1).setText("bad/name")
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_settings_and_request_preserve_mapping_and_signature_is_order_independent(self):
        settings = AppSettings()
        self.assertTrue(hasattr(settings, "model_name_mappings"))
        settings.model_name_mappings = {"B": "두번째", "A": "첫번째"}
        settings.model_mapping_scope = "filename_only"
        config = Mock()
        config.load.return_value = settings
        window = MainWindow(Mock(), config)
        self.addCleanup(window.close)
        current = window._current_settings()
        request = window._request_from_inputs(True)
        self.assertEqual(current.model_name_mappings, settings.model_name_mappings)
        self.assertIsNot(current.model_name_mappings, settings.model_name_mappings)
        self.assertEqual(request.model_name_mappings, settings.model_name_mappings)
        self.assertEqual(request.model_mapping_scope, "filename_only")
        signature = window._request_signature(request)
        request.model_name_mappings = {"A": "첫번째", "B": "두번째"}
        self.assertEqual(window._request_signature(request), signature)
        request.model_mapping_scope = "filename_and_folders"
        self.assertNotEqual(window._request_signature(request), signature)
        request.model_mapping_scope = "filename_only"
        request.model_name_mappings["A"] = "수정"
        self.assertNotEqual(window._request_signature(request), signature)

    def test_ok_validates_value_still_being_edited(self):
        dialog = self.dialog()
        dialog.mapping_table.setRowCount(1)
        dialog.mapping_table.setItem(0, 0, QTableWidgetItem("CAM_A"))
        dialog.mapping_table.setItem(0, 1, QTableWidgetItem("Family"))
        dialog.show()
        self.app.processEvents()
        dialog.mapping_table.editItem(dialog.mapping_table.item(0, 1))
        self.app.processEvents()
        editor = dialog.mapping_table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setText("bad/name")
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_panel_shows_alias_without_merging_original_selection_keys(self):
        panel = ModelSelectionPanel()
        self.addCleanup(panel.close)
        items = [SimpleNamespace(model_name=name, output_model_name="가족", media_type="photo", included=True) for name in ("CAM_A", "CAM_B")]
        panel.set_items(items)
        self.assertIn("CAM_A → 가족", panel.checkboxes["CAM_A"].text())
        self.assertIn("CAM_B → 가족", panel.checkboxes["CAM_B"].text())
        panel.checkboxes["CAM_A"].setChecked(False)
        self.assertEqual(panel.selected_models(), {"CAM_B"})

    def test_mapping_change_requires_new_preview_for_selection_and_manual_names(self):
        settings = AppSettings()
        self.assertTrue(hasattr(settings, "model_name_mappings"))
        config = Mock()
        config.load.return_value = settings
        engine = Mock()
        window = MainWindow(engine, config)
        self.addCleanup(window.close)
        window.source_edit.setText("source")
        window.target_edit.setText("target")
        previous = window._request_from_inputs(True)
        item = SimpleNamespace(model_name="CAM_A", output_model_name="CAM_A", media_type="photo", included=True, filename_edited=False)
        preview = SimpleNamespace(preview_items=[item], selection_applied=True)
        window.last_preview_bundle = preview
        window.last_preview_signature = window._request_signature(previous)
        window.model_selection_panel.set_items([item])
        window.settings.model_name_mappings = {"CAM_A": "가족"}
        window._build_request = Mock(return_value=window._request_from_inputs(False))
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            window.model_selection_panel.checkboxes["CAM_A"].setChecked(False)
            self.assertTrue(window.model_selection_panel.checkboxes["CAM_A"].isChecked())
            window._handle_execute()
            self.assertEqual(warning.call_count, 2)
        window._build_request.assert_not_called()
        engine.set_selected_models.assert_not_called()
        engine.execute.assert_not_called()
        preview.selection_applied = False
        item.filename_edited = True
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            window._handle_execute()
            warning.assert_called_once()
        engine.execute.assert_not_called()
        item.filename_edited = False
        window._build_request.reset_mock()
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            window._handle_execute()
            warning.assert_called_once()
        window._build_request.assert_not_called()
        engine.execute.assert_not_called()
        preview.model_name_mappings = {}
        preview.model_mapping_scope = "filename_and_folders"
        window.settings.model_name_mappings = {}
        window.settings.model_mapping_scope = "filename_only"
        with patch("photo_organizer.ui.main_window.QMessageBox.warning") as warning:
            window._handle_execute()
            warning.assert_called_once()
        window._build_request.assert_not_called()

    def test_mapping_only_repreview_preserves_manual_filename_in_new_folder(self):
        from photo_organizer.engine import OrganizerEngine
        from photo_organizer.models import MediaItem
        base = Path(__file__).resolve().parents[1] / ".tmp_test"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.jpg"
            photo.write_bytes(b"original")
            engine = OrganizerEngine(root)
            engine.extractor.extract = Mock(side_effect=lambda path: MediaItem(path, "photo", ".jpg", datetime(2024, 1, 1, 12), "사진 메타", "CAM_A", "사진 메타"))
            config = Mock()
            config.load.return_value = AppSettings(source_path=str(source), target_path=str(root / "target"), mobile_output_enabled=False)
            window = MainWindow(engine, config)
            try:
                window._handle_preview()
                old = window.last_preview_bundle.preview_items[0]
                engine.edit_preview_filename(window.last_preview_bundle, old.item_id, "내사진.jpg")
                window.settings.model_name_mappings = {"CAM_A": "가족"}
                window._handle_preview()
                item = window.last_preview_bundle.preview_items[0]
                self.assertEqual(item.new_filename, "내사진.jpg")
                self.assertTrue(item.filename_edited)
                self.assertEqual(Path(item.target_path).parent.name, "20240101_가족")
                self.assertIn("수동 파일명", window.status_label.text())
                self.assertTrue(photo.exists())
                window.settings.model_name_mappings = {"CAM_A": "가족2"}
                planned = engine.preview(window._request_from_inputs(True)).preview_items[0]
                collision = Path(planned.target_directory) / "내사진.jpg"
                collision.parent.mkdir(parents=True)
                collision.write_bytes(b"keep")
                window._handle_preview()
                item = window.last_preview_bundle.preview_items[0]
                self.assertEqual(item.new_filename, "내사진.jpg")
                self.assertEqual(item.write_mode, "CONFLICT")
                self.assertEqual(window.preview_table.item(0, 2).text(), "충돌")
                window._handle_execute()
                self.assertEqual(window.last_execution_bundle.execution_results[0].status, "ERROR")
                self.assertEqual(collision.read_bytes(), b"keep")
                self.assertTrue(photo.exists())
            finally:
                window.close()

