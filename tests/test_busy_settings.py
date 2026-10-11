import unittest
from unittest.mock import patch
import test_responsive_ui as fixtures
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import SettingsDialog
from PySide6.QtWidgets import QDialogButtonBox


class BusySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResponsiveUiTests.setUpClass()
        cls.app = fixtures.ResponsiveUiTests.app

    def test_readonly_settings_cannot_apply_or_reset(self):
        settings = AppSettings(photo_workers=4)
        dialog = SettingsDialog(None, settings, read_only=True)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.settings_scroll.isEnabled())
        self.assertTrue(dialog.mapping_table.isEnabled())
        self.assertFalse(dialog.photo_workers_combo.isEnabled())
        self.assertFalse(dialog.save_defaults_checkbox.isEnabled())
        dialog._restore_defaults()
        self.assertEqual(dialog.photo_workers_combo.currentData(), 4)
        with self.assertRaises(ValueError):
            dialog.to_settings(settings)
        box = dialog.findChild(QDialogButtonBox)
        self.assertIsNone(box.button(QDialogButtonBox.Ok))

class BusySettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResponsiveUiTests.setUpClass()
        cls.app = fixtures.ResponsiveUiTests.app

    setUp = fixtures.ResponsiveUiTests.setUp
    cleanup = fixtures.ResponsiveUiTests.cleanup

    def test_started_job_readonly_mapping_remains_browsable(self):
        self.window._job_state.execution_started = True
        dialog = SettingsDialog(self.window, AppSettings(model_name_mappings={'CAM': 'My camera'}), read_only=True)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.mapping_table.isEnabled())
        self.assertEqual(dialog.mapping_table.rowCount(), 1)

    def test_nonmodal_snapshot_remains_readonly_after_operation_finishes(self):
        w = self.window
        w._active_operation_settings = AppSettings(photo_workers=4)
        w._set_busy(True)
        w.config_manager.save.reset_mock()
        w._job_dirty = False
        w._open_settings_dialog()
        dialog = w._busy_settings_dialog
        self.assertFalse(dialog.isModal())
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.photo_workers_combo.currentData(), 4)
        w._active_operation_settings.photo_workers = 1
        w._set_busy(False)
        self.assertEqual(dialog.photo_workers_combo.currentData(), 4)
        self.assertTrue(dialog._read_only)
        dialog._restore_defaults()
        dialog.reject()
        w.config_manager.save.assert_not_called()
        self.assertFalse(w._job_dirty)
