import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from dataclasses import replace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem
from photo_organizer.ui.main_window import MainWindow


class PreviewFileDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source.jpg'
        self.target = self.base / 'target.jpg'
        image = QImage(20, 10, QImage.Format_RGB32)
        image.fill(0xff112233)
        image.save(str(self.source))
        image.save(str(self.target))
        engine = OrganizerEngine(self.base)
        engine.describe_media_path = Mock(side_effect=lambda p: [('파일명', Path(p).name)])
        config = Mock()
        config.load.return_value = AppSettings(restore_last_job=False)
        self.window = MainWindow(engine, config)
        self.addCleanup(self.close_window)
        self.row = PreviewItem('one', 'photo', str(self.source), str(self.base), str(self.target),
                               self.target.name, 'NEW', '2024-01-01T12:00:00', 'EXIF', 'CAM', 'EXIF', [],
                               metadata_entries=[('파일명', self.source.name)])
        self.window.last_preview_bundle = PreviewBundle(preview_items=[self.row])
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)

    def close_window(self):
        self.window._job_dirty = False
        self.window.close()

    def click(self, column, row=0):
        self.window.preview_table.setCurrentCell(row, column)
        self.window.preview_table.itemClicked.emit(self.window.preview_table.item(row, column))

    def test_same_row_source_target_filename_clicks_switch_both_panels(self):
        for column, path, kind in ((0, self.source, '원본 파일'), (1, self.target, '대상 파일'),
                                   (3, self.target, '대상 파일'), (0, self.source, '원본 파일')):
            with self.subTest(column=column):
                self.click(column)
                self.assertEqual(self.window._current_preview_source_path, path)
                self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), path.name)
                self.assertIn('상세 기준: ' + kind, self.window.selection_detail.toPlainText())

    def test_missing_target_shows_absence_and_clears_old_source_metadata(self):
        self.target.unlink()
        self.click(0)
        self.click(1)
        self.assertIsNone(self.window._current_preview_source_path)
        self.assertIn('대상 파일이 아직 없습니다', self.window.selection_detail.toPlainText())
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '메타정보 없음')
        self.assertIn(str(self.target), self.window.preview_image_info.text())

    def test_removed_source_does_not_show_saved_metadata(self):
        self.source.unlink()
        self.click(0)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '메타정보 없음')
        self.assertIn('원본 파일을 찾을 수 없습니다', self.window.selection_detail.toPlainText())

    def test_filename_uses_latest_edited_target_path(self):
        edited = self.base / 'edited.jpg'
        self.target.rename(edited)
        self.row.target_path = str(edited)
        self.row.new_filename = edited.name
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)
        self.click(3)
        self.assertEqual(self.window._current_preview_source_path, edited)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), edited.name)

    def test_video_target_click_requests_target_thumbnail(self):
        target_video = self.base / 'target.mp4'
        target_video.write_bytes(b'video')
        self.row.target_path = str(target_video)
        self.row.new_filename = target_video.name
        self.window._fill_preview_table([self.row])
        self.window.preview_table.selectRow(0)
        with patch('photo_organizer.ui.main_window.extract_video_thumbnail_bytes', return_value=None) as thumbnail:
            self.click(1)
        self.assertTrue(thumbnail.called)
        self.assertTrue(all(call.args[0] == target_video for call in thumbnail.call_args_list))
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), target_video.name)

    def test_target_deleted_after_metadata_cached_does_not_show_stale_metadata(self):
        self.click(1)
        self.target.unlink()
        self.click(3)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '메타정보 없음')

    def test_metadata_refreshes_after_target_replaced(self):
        self.window.engine.describe_media_path.side_effect = lambda p: [('크기', str(Path(p).stat().st_size))]
        self.click(1)
        self.target.write_bytes(b'replaced')
        self.click(3)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '8')

    def test_changed_source_refreshes_metadata_instead_of_using_preview_snapshot(self):
        self.window.engine.describe_media_path.side_effect = lambda p: [('크기', str(Path(p).stat().st_size))]
        self.source.write_bytes(b'replaced')
        self.click(0)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '8')

    def test_target_created_after_first_click_is_read_on_next_click(self):
        self.target.unlink()
        self.click(1)
        self.target.write_bytes(b'created')
        self.click(3)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), self.target.name)

    def test_clicking_second_row_uses_its_own_target(self):
        other = self.base / 'second.jpg'
        other.write_bytes(self.source.read_bytes())
        second = replace(self.row, item_id='two', target_path=str(other), new_filename=other.name)
        self.window.last_preview_bundle = PreviewBundle(preview_items=[self.row, second])
        self.window._fill_preview_table([self.row, second])
        self.click(1)
        self.click(3, row=1)
        self.assertEqual(self.window._current_preview_source_path, other)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), other.name)

    def test_new_job_resets_detail_to_source(self):
        self.click(1)
        self.window._job_dirty = False
        self.window._new_job()
        self.assertEqual(self.window._preview_detail_column, 0)

    def test_recreated_source_does_not_use_metadata_from_missing_saved_baseline(self):
        from photo_organizer.job_store import JobState
        self.window._job_state = JobState(preview_bundle=self.window.last_preview_bundle,
            source_fingerprints={str(self.source): {'exists': False, 'is_file': False, 'size': None, 'mtime_ns': None}})
        self.window._preview_metadata_bundle = None
        self.source.write_bytes(b'replaced')
        self.window.engine.describe_media_path.side_effect = lambda p: [('크기', str(Path(p).stat().st_size))]
        self.window._fill_preview_table([self.row])
        self.click(0)
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '8')


if __name__ == '__main__':
    unittest.main()
