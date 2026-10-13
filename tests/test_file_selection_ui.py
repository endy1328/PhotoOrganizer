from pathlib import Path
from unittest.mock import patch
import unittest
import test_preview_file_detail as fixtures
from PySide6.QtCore import Qt


class FileSelectionUiTests(fixtures.PreviewFileDetailTests):
    def setUp(self):
        super().setUp()
        self.window.last_preview_signature = self.window._request_signature(
            self.window._request_from_inputs(preview_only=True))

    def test_check_column_is_first_visually_and_default_included(self):
        table = self.window.preview_table
        self.assertEqual(table.columnCount(), 10)
        self.assertEqual(table.horizontalHeaderItem(9).text(), '처리')
        self.assertEqual(table.horizontalHeader().visualIndex(9), 0)
        self.assertEqual(table.item(0, 9).checkState(), Qt.Checked)
        self.assertEqual(table.item(0, 8).text(), '-')

    def test_uncheck_excludes_then_reinclude_preserves_row_and_source(self):
        self.window.preview_table.item(0, 9).setCheckState(Qt.Unchecked)
        row = self.window.last_preview_bundle.preview_items[0]
        self.assertFalse(row.included)
        self.assertEqual(self.window.preview_table.item(0, 2).text(), '제외')
        self.assertTrue(self.source.exists())
        self.window.preview_table.item(0, 9).setCheckState(Qt.Checked)
        self.assertTrue(self.window.last_preview_bundle.preview_items[0].included)

    def test_busy_checkbox_is_readonly_and_handler_cannot_change_plan(self):
        self.window._set_busy(True)
        cell = self.window.preview_table.item(0, 9)
        self.assertFalse(cell.flags() & Qt.ItemIsUserCheckable)
        cell.setCheckState(Qt.Unchecked)
        self.assertTrue(self.window.last_preview_bundle.preview_items[0].included)
        self.window._set_busy(False)
        self.assertEqual(self.window.preview_table.item(0, 9).checkState(), Qt.Checked)

    def test_metadata_action_targets_original_even_when_output_selected(self):
        self.click(8)
        self.assertEqual(self.window._original_metadata_selected_item().source_path, str(self.source))
        self.window._set_busy(True)
        self.assertFalse(self.window.metadata_edit_button.isEnabled())
        self.window._set_busy(False)

    def test_old_columns_keep_logical_meaning(self):
        self.click(0)
        self.assertEqual(self.window._current_preview_source_path, self.source)
        self.click(1)
        self.assertEqual(self.window._current_preview_source_path, self.target)

    def test_old_column_order_widths_and_hidden_are_migrated(self):
        import json
        from photo_organizer.ui.view_preferences import ViewPreferences
        path = self.base / 'view.json'
        old = [8, 3, 2, 6, 5, 0, 1, 4, 7]
        path.write_text(json.dumps({'tables': {'preview_table': {'order': old,
            'widths': [220] * 9, 'hidden': [1, 4, 7]}}}), encoding='utf-8')
        controller = ViewPreferences(self.window, path)
        controller.restore()
        header = self.window.preview_table.horizontalHeader()
        self.assertEqual([header.logicalIndex(i) for i in range(10)], [9] + old)
        self.assertEqual(self.window.preview_table.columnWidth(8), 220)
        self.assertTrue(self.window.preview_table.isColumnHidden(1))
        self.assertFalse(self.window.preview_table.isColumnHidden(9))
        header.moveSection(header.visualIndex(9), 9)
        self.assertTrue(controller.save())
        controller.restore()
        self.assertEqual(header.visualIndex(9), 9)
