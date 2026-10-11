import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import MainWindow


class ResponsiveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        config = Mock()
        config.load.return_value = AppSettings(restore_last_job=False, autosave_job_changes=False)
        self.window = MainWindow(Mock(), config)
        self.window.show()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.window._job_dirty = False
        self.window.close()
        self.window._job_dirty = False

    def test_small_window_keeps_list_visible_and_controls_inside(self):
        self.window.resize(1024, 650)
        self.app.processEvents()
        self.assertLessEqual(self.window.height(), 650)
        self.assertGreaterEqual(self.window.preview_table.viewport().height(), 160)
        self.assertFalse(self.window.additional_options_panel.isVisible())
        for button in (self.window.preview_button, self.window.execute_button, self.window.pause_button,
                       self.window.stop_button, self.window.settings_button, self.window.phone_transfer_button):
            self.assertTrue(button.isVisible())
            self.assertTrue(self.window.rect().contains(button.mapTo(self.window, button.rect().bottomRight())))

    def test_workspace_changes_orientation_and_details_can_hide(self):
        self.window.resize(1600, 900)
        self.app.processEvents()
        self.assertEqual(self.window.dockWidgetArea(self.window.image_dock), Qt.RightDockWidgetArea)
        self.window.resize(1204, 1032)
        self.app.processEvents()
        self.assertEqual(self.window.dockWidgetArea(self.window.image_dock), Qt.BottomDockWidgetArea)
        before = self.window.preview_table.viewport().height()
        self.window.details_toggle.click()
        self.app.processEvents()
        self.assertFalse((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.assertGreater(self.window.preview_table.viewport().height(), before)

    def test_menu_busy_and_shared_detail_tabs_preserve_controls(self):
        self.assertEqual(self.window.detail_tabs.count(), 2)
        self.assertIs(self.window.detail_tabs.widget(0), self.window.selection_detail)
        self.assertIs(self.window.detail_tabs.widget(1), self.window.selection_metadata_table)
        self.assertEqual(len(self.window.job_actions), 4)
        self.window._set_busy(True)
        self.assertTrue(all(not action.isEnabled() for action in self.window.job_actions.values()))
        self.assertFalse(self.window.job_save_button.isEnabled())
        self.window._set_busy(False)
        self.assertTrue(all(action.isEnabled() for action in self.window.job_actions.values()))
        old_id = self.window._job_state.job_id
        self.window.job_actions['job_new_button'].trigger()
        self.assertNotEqual(self.window._job_state.job_id, old_id)

    def test_options_and_long_summary_do_not_force_large_minimum(self):
        self.window.additional_options_toggle.click()
        self.assertTrue(self.window.additional_options_panel.isVisible())
        self.window.additional_options_toggle.click()
        summary = '긴 설정값 ' * 100
        self.window.mobile_output_summary.setText(summary)
        self.window.resize(1024, 650)
        self.app.processEvents()
        self.assertEqual(self.window.mobile_output_summary.toolTip(), summary)
        self.assertLess(self.window.mobile_output_summary.height(), 40)
        self.assertLess(self.window.minimumSizeHint().width(), 1025)

    def test_short_window_auto_folds_detail_and_respects_manual_choice(self):
        self.window.resize(800, 550)
        self.app.processEvents()
        self.assertFalse((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.assertGreaterEqual(self.window.preview_table.viewport().height(), 150)
        self.window.resize(1204, 1032)
        self.app.processEvents()
        self.assertTrue((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.window.resize(602, 516)
        self.app.processEvents()
        self.assertGreaterEqual(self.window.preview_table.viewport().height(), 120)
        self.window.details_toggle.click()
        self.assertTrue((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.window.details_toggle.click()
        self.window.resize(1204, 1032)
        self.app.processEvents()
        self.assertFalse((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))

    def test_collapsed_options_show_active_move_and_device_without_long_width(self):
        self.window.mode_combo.setCurrentText('move')
        self.window.device_name_edit.setText('장비' * 250)
        self.assertIn('이동', self.window.additional_options_toggle.text())
        self.assertIn('기기 지정', self.window.additional_options_toggle.text())
        self.assertIn('장비' * 250, self.window.additional_options_toggle.toolTip())
        self.window.resize(1024, 650)
        self.app.processEvents()
        self.assertLess(self.window.minimumSizeHint().width(), 1025)
        self.assertFalse(self.window.additional_options_panel.isVisible())
        self.window.device_name_edit.clear()
        self.window.mode_combo.setCurrentText('copy')
        self.assertEqual(self.window.additional_options_toggle.text(), '추가 옵션')

    def test_real_korean_font_remote_sizes_and_manual_details_override(self):
        font_path = Path('C:/Windows/Fonts/malgun.ttf')
        if font_path.exists():
            self.assertGreaterEqual(QFontDatabase.addApplicationFont(str(font_path)), 0)
        self.window.resize(802, 640)
        self.app.processEvents()
        self.assertFalse((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.window.details_toggle.click()
        self.window.resize(802, 620)
        self.app.processEvents()
        self.assertTrue((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.window.resize(1024, 650)
        self.app.processEvents()
        self.assertTrue((self.window.image_dock.isVisible() or self.window.detail_dock.isVisible()))
        self.window.resize(602, 480)
        self.app.processEvents()
        self.assertGreaterEqual(self.window.preview_table.viewport().height(), 100)
        for button in (self.window.preview_button, self.window.execute_button, self.window.stop_button,
                       self.window.phone_transfer_button, self.window.settings_button):
            self.assertTrue(self.window.rect().contains(button.mapTo(self.window, button.rect().bottomRight())))
