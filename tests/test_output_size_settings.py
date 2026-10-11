import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from photo_organizer.config import ConfigManager
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import MainWindow, SettingsDialog


class OutputSizeSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_and_toml_roundtrip(self):
        settings = AppSettings()
        self.assertFalse(settings.mobile_output_limit_enabled)
        self.assertEqual(settings.mobile_output_limit_mb, 500)
        from photo_organizer.models import OrganizeRequest
        request = OrganizeRequest(Path("source"), Path("target"))
        self.assertFalse(request.mobile_output_limit_enabled)
        self.assertEqual(request.mobile_output_limit_mb, 500)
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            settings.mobile_output_limit_enabled = True
            settings.mobile_output_limit_mb = 1234
            manager.save(settings)
            loaded = manager.load()
            self.assertTrue(loaded.mobile_output_limit_enabled)
            self.assertEqual(loaded.mobile_output_limit_mb, 1234)

    def test_invalid_toml_values_default_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            for enabled, size in [('"false"', '"500"'), ('1', 'true'), ('true', '0'), ('false', '1000001')]:
                with self.subTest(enabled=enabled, size=size):
                    manager.config_path.write_text('[app]\nsource_path="keep"\nmobile_output_limit_enabled=' + enabled + '\nmobile_output_limit_mb=' + size, encoding="utf-8")
                    loaded = manager.load()
                    self.assertEqual(loaded.source_path, "keep")
                    self.assertEqual(loaded.mobile_output_limit_enabled, enabled == 'true')
                    self.assertEqual(loaded.mobile_output_limit_mb, 500)

    def test_legacy_json_sanitizes_and_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            manager.legacy_config_path.write_text(json.dumps({"source_path": "keep", "mobile_output_limit_enabled": "true", "mobile_output_limit_mb": False}), encoding="utf-8")
            loaded = manager.load()
            self.assertEqual(loaded.source_path, "keep")
            self.assertFalse(loaded.mobile_output_limit_enabled)
            self.assertEqual(loaded.mobile_output_limit_mb, 500)
            self.assertTrue(manager.config_path.exists())

    def test_save_normalizes_invalid_values_without_mutating_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.mobile_output_limit_enabled = "false"
            settings.mobile_output_limit_mb = -1
            manager = ConfigManager(Path(directory))
            manager.save(settings)
            loaded = manager.load()
            self.assertFalse(loaded.mobile_output_limit_enabled)
            self.assertEqual(loaded.mobile_output_limit_mb, 500)
            self.assertEqual(settings.mobile_output_limit_enabled, "false")
            self.assertEqual(settings.mobile_output_limit_mb, -1)

    def test_ui_toggle_roundtrip_and_restore(self):
        settings = AppSettings()
        settings.mobile_output_limit_enabled = True
        settings.mobile_output_limit_mb = 720
        dialog = SettingsDialog(None, settings)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.mobile_output_limit_checkbox.isChecked())
        self.assertTrue(dialog.mobile_output_limit_spin.isEnabled())
        self.assertEqual(dialog.mobile_output_limit_spin.minimum(), 1)
        self.assertEqual(dialog.mobile_output_limit_spin.maximum(), 1000000)
        self.assertIn("1,000,000", dialog.mobile_output_limit_spin.toolTip())
        dialog.mobile_output_limit_spin.setValue(900)
        self.assertEqual(dialog.to_settings(settings).mobile_output_limit_mb, 900)
        dialog.mobile_output_limit_checkbox.setChecked(False)
        self.assertFalse(dialog.mobile_output_limit_spin.isEnabled())
        self.assertFalse(dialog.to_settings(settings).mobile_output_limit_enabled)
        dialog._restore_defaults()
        restored = dialog.to_settings(settings)
        self.assertFalse(restored.mobile_output_limit_enabled)
        self.assertEqual(restored.mobile_output_limit_mb, 500)
        dialog.mobile_output_limit_checkbox.setChecked(True)
        dialog.enabled_checkbox.setChecked(False)
        self.assertFalse(dialog.mobile_output_limit_checkbox.isEnabled())
        self.assertFalse(dialog.mobile_output_limit_spin.isEnabled())
        dialog.enabled_checkbox.setChecked(True)
        self.assertTrue(dialog.mobile_output_limit_spin.isEnabled())

    def test_main_window_preserves_request_and_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings(target_path=directory)
            settings.mobile_output_limit_enabled = True
            settings.mobile_output_limit_mb = 720
            config = Mock()
            config.load.return_value = settings
            window = MainWindow(Mock(base_dir=Path(directory)), config)
            self.addCleanup(window.close)
            current = window._current_settings()
            self.assertTrue(current.mobile_output_limit_enabled)
            self.assertEqual(current.mobile_output_limit_mb, 720)
            self.assertIn("720 MB", window.mobile_output_summary.text())
            request = window._request_from_inputs(preview_only=False)
            self.assertTrue(request.mobile_output_limit_enabled)
            self.assertEqual(request.mobile_output_limit_mb, 720)
            original = window._request_signature(request)
            request.mobile_output_limit_mb = 721
            self.assertNotEqual(original, window._request_signature(request))
            request.mobile_output_limit_mb = 720
            request.mobile_output_limit_enabled = False
            self.assertNotEqual(original, window._request_signature(request))

    def test_size_excluded_result_has_reason_in_table_and_detail(self):
        from photo_organizer.models import ExecutionResult, ExecutionBundle
        with tempfile.TemporaryDirectory() as directory:
            config = Mock()
            config.load.return_value = AppSettings()
            window = MainWindow(Mock(base_dir=Path(directory)), config)
            self.addCleanup(window.close)
            result = ExecutionResult("source.jpg", "target.jpg", "SUCCESS", "copy", mobile_output_path="output_/photo.jpg", mobile_output_status="SIZE_EXCLUDED", mobile_output_message="결과 600 MB / 기준 500 MB 이상")
            window.last_execution_bundle = ExecutionBundle(execution_results=[result])
            window.engine.describe_media_path.return_value = []
            window._fill_results_table([result])
            self.assertEqual(window.results_table.item(0, 5).text(), "출력 용량 제한 제외")
            self.assertIn("600 MB", window.results_table.item(0, 7).text())
            window.results_table.selectRow(0)
            window._update_selection_detail("results")
            self.assertIn("600 MB", window.selection_detail.toPlainText())

if __name__ == "__main__":
    unittest.main()
