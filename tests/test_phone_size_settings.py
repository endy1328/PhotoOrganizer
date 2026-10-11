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


class PhoneSizeSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_and_toml_roundtrip(self):
        settings = AppSettings()
        self.assertFalse(settings.phone_video_limit_enabled)
        self.assertEqual(settings.phone_video_limit_mb, 500)
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            settings.phone_video_limit_enabled = True
            settings.phone_video_limit_mb = 1234
            manager.save(settings)
            loaded = manager.load()
            self.assertTrue(loaded.phone_video_limit_enabled)
            self.assertEqual(loaded.phone_video_limit_mb, 1234)

    def test_invalid_toml_values_default_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            for enabled, size in [('"false"', '"500"'), ('1', 'true'), ('true', '0'), ('false', '1000001')]:
                with self.subTest(enabled=enabled, size=size):
                    manager.config_path.write_text('[app]\nsource_path="keep"\nphone_video_limit_enabled=' + enabled + '\nphone_video_limit_mb=' + size, encoding="utf-8")
                    loaded = manager.load()
                    self.assertEqual(loaded.source_path, "keep")
                    self.assertEqual(loaded.phone_video_limit_enabled, enabled == 'true')
                    self.assertEqual(loaded.phone_video_limit_mb, 500)

    def test_legacy_json_sanitizes_and_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(Path(directory))
            manager.legacy_config_path.write_text(json.dumps({"source_path": "keep", "phone_video_limit_enabled": "true", "phone_video_limit_mb": False}), encoding="utf-8")
            loaded = manager.load()
            self.assertEqual(loaded.source_path, "keep")
            self.assertFalse(loaded.phone_video_limit_enabled)
            self.assertEqual(loaded.phone_video_limit_mb, 500)
            self.assertTrue(manager.config_path.exists())

    def test_save_normalizes_invalid_values_without_mutating_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.phone_video_limit_enabled = "false"
            settings.phone_video_limit_mb = -1
            manager = ConfigManager(Path(directory))
            manager.save(settings)
            loaded = manager.load()
            self.assertFalse(loaded.phone_video_limit_enabled)
            self.assertEqual(loaded.phone_video_limit_mb, 500)
            self.assertEqual(settings.phone_video_limit_enabled, "false")
            self.assertEqual(settings.phone_video_limit_mb, -1)

    def test_ui_toggle_roundtrip_and_restore(self):
        settings = AppSettings()
        settings.phone_video_limit_enabled = True
        settings.phone_video_limit_mb = 720
        dialog = SettingsDialog(None, settings)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.phone_video_limit_checkbox.isChecked())
        self.assertTrue(dialog.phone_video_limit_spin.isEnabled())
        self.assertEqual(dialog.phone_video_limit_spin.minimum(), 1)
        self.assertEqual(dialog.phone_video_limit_spin.maximum(), 1000000)
        self.assertIn("1,000,000", dialog.phone_video_limit_spin.toolTip())
        dialog.phone_video_limit_spin.setValue(900)
        self.assertEqual(dialog.to_settings(settings).phone_video_limit_mb, 900)
        dialog.phone_video_limit_checkbox.setChecked(False)
        self.assertFalse(dialog.phone_video_limit_spin.isEnabled())
        self.assertFalse(dialog.to_settings(settings).phone_video_limit_enabled)
        dialog._restore_defaults()
        restored = dialog.to_settings(settings)
        self.assertFalse(restored.phone_video_limit_enabled)
        self.assertEqual(restored.phone_video_limit_mb, 500)

    def test_main_window_preserves_and_passes_decimal_byte_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings(target_path=directory)
            settings.phone_video_limit_enabled = True
            settings.phone_video_limit_mb = 720
            config = Mock()
            config.load.return_value = settings
            window = MainWindow(Mock(base_dir=Path(directory)), config)
            self.addCleanup(window.close)
            current = window._current_settings()
            self.assertTrue(current.phone_video_limit_enabled)
            self.assertEqual(current.phone_video_limit_mb, 720)
            with patch("photo_organizer.ui.phone_transfer_dialog.PhoneTransferDialog") as dialog:
                window._open_phone_transfer()
                self.assertEqual(dialog.call_args.kwargs["video_limit_bytes"], 720000000)
                window.settings.phone_video_limit_enabled = False
                window._open_phone_transfer()
                self.assertIsNone(dialog.call_args.kwargs["video_limit_bytes"])


if __name__ == "__main__":
    unittest.main()
