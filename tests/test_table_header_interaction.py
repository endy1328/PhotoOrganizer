import json
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import test_execution_controller as fixture
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView


class TableHeaderInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ExecutionControllerTests.setUpClass()

    def setUp(self):
        self.fixture = fixture.ExecutionControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window = self.fixture.window

    def tables(self):
        w = self.window
        return (w.preview_table, w.results_table, w.error_table, w.delete_table,
                w.selection_metadata_table, w.execution_progress_dock.active_table,
                w.execution_progress_dock.history_table)

    def test_all_display_headers_allow_manual_resize_and_reorder(self):
        for table in self.tables():
            header = table.horizontalHeader()
            self.assertTrue(header.sectionsMovable())
            for index in range(table.columnCount()):
                self.assertEqual(header.sectionResizeMode(index), QHeaderView.Interactive)

    def test_actual_mouse_drag_resizes_and_moves_logical_column(self):
        table = self.window.execution_progress_dock.active_table
        table.setParent(None)
        self.addCleanup(table.close)
        table.resize(650, 240)
        table.show()
        fixture.ExecutionControllerTests.app.processEvents()
        header = table.horizontalHeader()
        viewport = header.viewport()
        width = header.sectionSize(0)
        y = viewport.height() // 2
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(width - 1, y))
        QTest.mouseMove(viewport, QPoint(width + 49, y), 30)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(width + 49, y))
        self.assertGreater(header.sectionSize(0), width + 20)
        start = QPoint(header.sectionViewportPosition(0) + 40, y)
        target = QPoint(header.sectionViewportPosition(2) + header.sectionSize(2) - 12, y)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(viewport, start + QPoint(20, 0), 30)
        QTest.mouseMove(viewport, target, 30)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, target)
        self.assertNotEqual(header.visualIndex(0), 0)
        self.assertEqual(table.columnCount(), 3)

    def test_auxiliary_column_preferences_roundtrip_without_job_change(self):
        w = self.window
        with tempfile.TemporaryDirectory(dir=Path.cwd() / '.tmp_test') as directory:
            prefs = w._view_preferences
            prefs.path = Path(directory) / 'view.json'
            signature = w._request_signature(w._request_from_inputs(preview_only=True))
            dirty = w._job_dirty
            for table in self.tables()[4:]:
                table.horizontalHeader().moveSection(0, 1)
                table.setColumnWidth(0, 240)
            self.assertTrue(prefs.save())
            data = json.loads(prefs.path.read_text(encoding='utf-8'))
            self.assertIn('selection_metadata_table', data['tables'])
            self.assertIn('execution_active_table', data['tables'])
            self.assertIn('execution_history_table', data['tables'])
            for table in self.tables()[4:]:
                table.horizontalHeader().moveSection(1, 0)
                table.setColumnWidth(0, 100)
            prefs.restore()
            for table in self.tables()[4:]:
                self.assertEqual(table.horizontalHeader().visualIndex(0), 1)
                self.assertEqual(table.columnWidth(0), 240)
            self.assertEqual(w._job_dirty, dirty)
            self.assertEqual(w._request_signature(w._request_from_inputs(preview_only=True)), signature)
