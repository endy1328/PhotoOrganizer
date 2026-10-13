from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import unittest

import test_preview_file_detail as fixtures
from photo_organizer.models import PreviewBundle, ExecutionResult


class OutputColumnTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PreviewFileDetailTests.setUpClass.__func__)
    close_window = fixtures.PreviewFileDetailTests.close_window
    click = fixtures.PreviewFileDetailTests.click
    def setUp(self):
        fixtures.PreviewFileDetailTests.setUp(self)
        self.output = self.base / 'output_CAM' / 'mobile.jpg'
        self.output.parent.mkdir()
        self.output.write_bytes(self.source.read_bytes())
        self.row.mobile_output_enabled = True
        self.row.mobile_output_path = str(self.output)
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)

    def test_output_appended_readonly_click_switches_all_panels(self):
        from PySide6.QtCore import Qt
        table = self.window.preview_table
        self.assertEqual(table.columnCount(), 10)
        self.assertEqual(table.horizontalHeaderItem(8).text(), 'output')
        self.assertEqual(table.item(0, 8).text(), str(self.output))
        self.assertFalse(table.item(0, 8).flags() & Qt.ItemIsEditable)
        self.click(8)
        self.assertEqual(self.window._current_preview_source_path, self.output)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), self.output.name)
        self.assertIn('상세 기준: 모바일 출력 파일', self.window.selection_detail.toPlainText())

    def test_output_missing_then_created_refreshes_without_source_fallback(self):
        content = self.output.read_bytes()
        self.output.unlink()
        self.click(0)
        self.click(8)
        self.assertIsNone(self.window._current_preview_source_path)
        self.assertIn('출력 파일이 아직 없습니다', self.window.selection_detail.toPlainText())
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '메타정보 없음')
        self.output.write_bytes(content)
        self.click(8)
        self.assertEqual(self.window._current_preview_source_path, self.output)

    def test_disabled_output_keeps_output_selection_without_using_target(self):
        self.row.mobile_output_enabled = False
        self.row.mobile_output_path = ''
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)
        self.click(8)
        self.assertEqual(self.window.preview_table.item(0, 8).text(), '-')
        self.assertIsNone(self.window._current_preview_source_path)
        self.assertIn('출력 파일', self.window.selection_detail.toPlainText())

    def test_moved_column_uses_logical_output_path_for_video_thumbnail(self):
        video = self.output.with_suffix('.mp4')
        video.write_bytes(b'video')
        self.row.mobile_output_path = str(video)
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)
        header = self.window.preview_table.horizontalHeader()
        header.moveSection(header.visualIndex(8), 0)
        with patch('photo_organizer.ui.main_window.extract_video_thumbnail_bytes', return_value=None) as thumbnail:
            self.click(8)
        self.assertTrue(thumbnail.called)
        self.assertTrue(all(call.args[0] == video for call in thumbnail.call_args_list))

    def test_results_existing_output_is_renamed_and_does_not_fallback_if_disabled(self):
        result = ExecutionResult(str(self.source), str(self.target), 'SUCCESS', 'copy', 'NEW')
        self.window._fill_results_table([result])
        self.window.results_table.selectRow(0)
        self.assertEqual(self.window.results_table.horizontalHeaderItem(6).text(), 'output')
        cell = self.window.results_table.item(0, 6)
        self.window._handle_results_item_clicked(cell)
        self.assertEqual(self.window._results_detail_target(0), (None, '모바일 출력 파일'))
        self.assertIn('출력 파일', self.window.selection_detail.toPlainText())

    def test_busy_output_read_uses_output_path(self):
        self.window._set_busy(True)
        with patch.object(self.window, '_start_busy_detail_read'):
            self.click(8)
        request = self.window._busy_read_pending
        self.assertEqual(request[1], self.output)
        self.window._set_busy(False)

    def test_mouse_click_after_column_drag_selects_output_file(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.show()
        self.app.processEvents()
        table = self.window.preview_table
        header = table.horizontalHeader()
        header.moveSection(header.visualIndex(8), 0)
        table.scrollToItem(table.item(0, 8))
        self.app.processEvents()
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualItemRect(table.item(0, 8)).center())
        self.assertEqual(self.window._current_preview_source_path, self.output)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), self.output.name)

    def test_refilled_preview_uses_latest_output_path(self):
        new_output = self.output.with_name('renamed.jpg')
        self.output.rename(new_output)
        self.row.mobile_output_path = str(new_output)
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)
        self.click(8)
        self.assertEqual(self.window._current_preview_source_path, new_output)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), new_output.name)


if __name__ == '__main__':
    unittest.main()
