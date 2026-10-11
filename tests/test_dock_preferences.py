import json
import base64
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QTableWidget, QToolButton, QWidget
from photo_organizer.ui.view_preferences import ViewPreferences


class DockPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='dockprefs_')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'view.json'
        self.window = QMainWindow()
        self.addCleanup(self.window.close)
        self.window.setCentralWidget(QWidget())
        for name in ('preview_table', 'results_table', 'error_table', 'delete_table'):
            setattr(self.window, name, QTableWidget(0, 8))
        self.window.details_toggle = QToolButton()
        self.window.details_toggle.setCheckable(True)
        self.window.details_toggle.setChecked(True)
        self.window._dock_user_visibility = {'image': True, 'detail': True}
        self.window._custom_dock_layout = False
        for key in ('image', 'detail'):
            dock = QDockWidget(key, self.window)
            dock.setObjectName('photo_' + key + '_dock')
            dock.setWidget(QWidget())
            self.window.addDockWidget(Qt.RightDockWidgetArea, dock)
            setattr(self.window, key + '_dock', dock)
        self.prefs = ViewPreferences(self.window, self.path)

    def test_roundtrip_native_layout_and_independent_visibility(self):
        self.window.addDockWidget(Qt.LeftDockWidgetArea, self.window.image_dock)
        self.window._custom_dock_layout = True
        self.window._dock_user_visibility['detail'] = False
        self.window.detail_dock.hide()
        self.assertTrue(self.prefs.save())
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertIsInstance(saved['dock_state'], str)
        self.window.addDockWidget(Qt.RightDockWidgetArea, self.window.image_dock)
        self.window._custom_dock_layout = False
        self.window._dock_user_visibility['detail'] = True
        self.prefs.restore()
        self.assertEqual(self.window.dockWidgetArea(self.window.image_dock), Qt.LeftDockWidgetArea)
        self.assertTrue(self.window._custom_dock_layout)
        self.assertEqual(self.window._dock_user_visibility, {'image': True, 'detail': False})
        self.assertTrue(self.window.detail_dock.isHidden())

    def test_malformed_state_is_ignored_and_legacy_visibility_migrates(self):
        for state in ('%%%not base64', 'A' * 100000, 123, 'eA=='):
            self.path.write_text(json.dumps({'dock_state': state, 'details_visible': False}), encoding='utf-8')
            with patch.object(self.window, 'restoreState', wraps=self.window.restoreState) as restore:
                self.prefs.restore()
                restore.assert_not_called()
            if len(str(state)) < 65536:
                self.assertEqual(self.window._dock_user_visibility, {'image': False, 'detail': False})

    def test_floating_dock_is_restored_inside_available_screen(self):
        self.window.image_dock.setFloating(True)
        self.window.image_dock.setGeometry(50000, 50000, 9000, 9000)
        self.window._custom_dock_layout = True
        self.prefs.save()
        self.prefs.restore()
        available = self.window.screen().availableGeometry()
        self.assertTrue(self.window.image_dock.isFloating())
        self.assertTrue(available.contains(self.window.image_dock.geometry()))

    def test_none_path_is_safe_for_native_dock_fixture(self):
        prefs = ViewPreferences(self.window, None)
        prefs.restore()
        self.assertTrue(prefs.save())
        self.assertFalse(self.path.exists())

    def test_failed_native_restore_uses_fallback_under_arrangement_guard(self):
        self.prefs.save()
        self.window._arranging_docks = False
        observed = []
        def restore(state, version):
            observed.append((self.window._arranging_docks, version))
            return len(observed) > 1
        with patch.object(self.window, 'restoreState', side_effect=restore):
            self.prefs.restore()
        self.assertEqual(observed, [(True, 1), (True, 1)])
        self.assertFalse(self.window._arranging_docks)
        self.assertFalse(self.window._custom_dock_layout)

    def test_truncated_native_state_keeps_default_areas_and_other_panel_visibility(self):
        truncated = b'\x00\x00\x00\xff\x00\x00\x00\x01\xfd'
        self.path.write_text(json.dumps({'dock_state': base64.b64encode(truncated).decode('ascii'),
                                       'dock_visibility': {'image': False, 'detail': True}}), encoding='utf-8')
        with patch.object(self.window, 'restoreState', wraps=self.window.restoreState) as restore:
            self.prefs.restore()
            self.assertEqual(restore.call_count, 2)
        self.assertEqual(self.window.dockWidgetArea(self.window.image_dock), Qt.RightDockWidgetArea)
        self.assertEqual(self.window.dockWidgetArea(self.window.detail_dock), Qt.RightDockWidgetArea)
        self.assertFalse(self.window._custom_dock_layout)
        self.assertEqual(self.window._dock_user_visibility, {'image': False, 'detail': True})
        self.assertTrue(self.window.image_dock.isHidden())
        self.assertFalse(self.window.detail_dock.isHidden())

    def test_native_dock_widths_roundtrip(self):
        self.window.resize(700, 500)
        self.window.addDockWidget(Qt.LeftDockWidgetArea, self.window.image_dock)
        self.window.show()
        self.app.processEvents()
        self.window.resizeDocks([self.window.image_dock, self.window.detail_dock], [180, 220], Qt.Horizontal)
        self.app.processEvents()
        original = [self.window.image_dock.width(), self.window.detail_dock.width()]
        self.prefs.save()
        self.window.resizeDocks([self.window.image_dock, self.window.detail_dock], [90, 90], Qt.Horizontal)
        self.app.processEvents()
        self.prefs.restore()
        self.app.processEvents()
        actual = [self.window.image_dock.width(), self.window.detail_dock.width()]
        for expected, observed in zip(original, actual):
            self.assertLessEqual(abs(expected - observed), 5)


if __name__ == '__main__':
    unittest.main()
