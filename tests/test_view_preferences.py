import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter, QTableWidget, QToolButton, QWidget


class ViewPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='viewprefs_')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'view_preferences.json'
        self.window = QMainWindow()
        self.addCleanup(self.window.close)
        self.window.preview_table = QTableWidget(0, 8)
        self.window.preview_table.setHorizontalHeaderLabels(['원본', '대상', '처리', '새 파일명', '일시', '모델', '안내', '영상 조회'])
        self.window.results_table = QTableWidget(0, 8)
        self.window.error_table = QTableWidget(0, 2)
        self.window.delete_table = QTableWidget(0, 3)
        self.window.workspace_splitter = QSplitter(Qt.Horizontal)
        self.window.workspace_splitter.addWidget(QWidget())
        self.window.workspace_splitter.addWidget(QWidget())
        self.window.details_toggle = QToolButton()
        self.window.details_toggle.setCheckable(True)
        self.window.details_toggle.setChecked(True)
        self.window.setCentralWidget(self.window.workspace_splitter)

    def controller(self):
        from photo_organizer.ui.view_preferences import ViewPreferences
        return ViewPreferences(self.window, self.path)

    def test_default_column_order_keeps_logical_filename_index(self):
        prefs = self.controller()
        prefs.restore()
        self.assertEqual(self.window.preview_table.horizontalHeader().logicalIndex(0), 3)
        self.assertFalse(self.window.preview_table.isColumnHidden(3))
        self.assertGreaterEqual(self.window.preview_table.columnWidth(3), 340)

    def test_roundtrip_columns_width_order_and_panel_visibility(self):
        prefs = self.controller()
        prefs.restore()
        table = self.window.preview_table
        table.setColumnWidth(3, 355)
        table.setColumnWidth(0, 345)
        table.setColumnHidden(0, True)
        table.horizontalHeader().moveSection(table.horizontalHeader().visualIndex(6), 1)
        self.window.details_toggle.setChecked(False)
        prefs.save()
        table.setColumnWidth(3, 100)
        table.setColumnHidden(0, False)
        table.setColumnWidth(0, 100)
        self.window.details_toggle.setChecked(True)
        self.controller().restore()
        self.assertEqual(table.columnWidth(3), 355)
        self.assertTrue(table.isColumnHidden(0))
        self.assertEqual(table.horizontalHeader().logicalIndex(1), 6)
        self.assertFalse(self.window.details_toggle.isChecked())
        table.setColumnHidden(0, False)
        self.assertEqual(table.columnWidth(0), 345)

    def test_corrupt_or_outside_screen_geometry_does_not_escape_available_area(self):
        self.path.write_text(json.dumps({'geometry': [50000, 50000, 8000, 8000]}))
        prefs = self.controller()
        prefs.restore()
        screen = self.window.screen().availableGeometry()
        self.assertLessEqual(self.window.width(), screen.width())
        self.assertLessEqual(self.window.height(), screen.height())
        self.assertTrue(screen.contains(self.window.geometry()))
        self.path.write_text('{invalid')
        self.controller().restore()

    def test_filename_cannot_be_hidden_and_last_column_is_accessible(self):
        prefs = self.controller()
        prefs.restore()
        menu = prefs.column_menu(self.window.preview_table)
        action = next(a for a in menu.actions() if a.data() == 3)
        self.assertFalse(action.isEnabled())
        actions = [a for a in menu.actions() if isinstance(a.data(), int) and a.data() != 3]
        for action in actions:
            action.setChecked(False)
        self.assertFalse(self.window.preview_table.isColumnHidden(3))
        self.assertEqual(sum(not self.window.preview_table.isColumnHidden(i) for i in range(8)), 1)

    def test_deeply_nested_json_is_ignored_without_preventing_startup(self):
        self.path.write_text('[' * 3000 + '0' + ']' * 3000, encoding='utf-8')
        self.controller().restore()
        self.assertFalse(self.window.preview_table.isColumnHidden(3))
