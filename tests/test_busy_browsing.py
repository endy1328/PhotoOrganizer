import unittest
import threading
from pathlib import Path
from unittest.mock import patch
import test_responsive_ui as fixtures
import test_preview_file_detail as detail_fixtures
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QAbstractItemView, QCheckBox


class BusyBrowsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResponsiveUiTests.setUpClass()
        cls.app = fixtures.ResponsiveUiTests.app

    setUp = fixtures.ResponsiveUiTests.setUp
    cleanup = fixtures.ResponsiveUiTests.cleanup

    def test_busy_allows_browsing_but_blocks_mutation(self):
        w = self.window
        w.delete_table.setRowCount(1)
        checkbox = QCheckBox()
        w.delete_table.setCellWidget(0, 0, checkbox)
        w._job_dirty = False
        w._set_busy(True)
        for widget in (w.preview_table, w.results_table, w.error_table, w.delete_table,
                       w.selection_detail_panel, w.selection_image_panel, w.tabs.tabBar(), w.settings_button):
            self.assertTrue(widget.isEnabled())
        self.assertFalse(checkbox.isEnabled())
        self.assertEqual(w.preview_table.editTriggers(), QAbstractItemView.NoEditTriggers)
        w.tabs.setCurrentIndex(1)
        self.assertFalse(w._job_dirty)
        self.assertFalse(w.execute_button.isEnabled())
        self.assertFalse(w.model_selection_panel.isEnabled())
        w._set_busy(False)


class BusyDetailReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        detail_fixtures.PreviewFileDetailTests.setUpClass()
        cls.app = detail_fixtures.PreviewFileDetailTests.app

    setUp = detail_fixtures.PreviewFileDetailTests.setUp
    click = detail_fixtures.PreviewFileDetailTests.click

    def close_window(self):
        self.window._set_busy(False)
        if self.window._busy_read_worker is not None:
            self.wait_for(lambda: self.window._busy_read_worker is None)
        self.window._job_dirty = False
        self.window.close()

    def wait_for(self, predicate):
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        timer.start()
        deadline.start(10000)
        if not predicate():
            loop.exec()
        timer.stop()
        deadline.stop()
        self.assertTrue(predicate(), 'read-only worker did not settle within bounded deadline')

    def test_only_one_reader_and_latest_pending_selection_is_applied(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        w = self.window
        first_started, release = threading.Event(), threading.Event()
        calls = []
        middle = self.base / 'middle.jpg'
        middle.write_bytes(self.source.read_bytes())
        final = self.base / 'final.jpg'
        final.write_bytes(self.source.read_bytes())
        def read(request):
            token, path, before, *_rest = request
            calls.append(path)
            if len(calls) == 1:
                first_started.set()
                if not release.wait(10):
                    raise RuntimeError('test failed to release reader')
            image = QImage(str(path))
            return token, path, before, before, [('파일명', path.name)], image, ''
        with patch.object(BusyDetailWorker, 'read', side_effect=read), patch.object(w, '_selected_image_source_path', return_value=str(self.source)) as selected:
            w._set_busy(True)
            w._job_dirty = False
            w._update_selection_detail('preview')
            self.wait_for(first_started.is_set)
            initial_worker = w._busy_read_worker
            selected.return_value = str(middle)
            w._update_selection_detail('preview')
            selected.return_value = str(final)
            w._update_selection_detail('preview')
            self.assertIs(w._busy_read_worker, initial_worker)
            self.assertEqual(w._busy_read_pending[1], final)
            self.assertTrue(w.pause_button.isEnabled() is False)  # No engine operation in this fixture.
            release.set()
            self.wait_for(lambda: w._busy_read_worker is None and w._busy_read_pending is None)
        self.assertEqual(calls, [self.source, final])
        self.assertEqual(w._current_preview_source_path, final)
        self.assertEqual(w.selection_metadata_table.item(0, 1).text(), final.name)
        self.assertFalse(w._job_dirty)
        w._set_busy(False)

    def test_modified_file_drops_result_and_allows_reselection(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        w = self.window
        def read(request):
            token, path, before, *_rest = request
            path.write_bytes(b'externally changed')
            return token, path, before, before, [('오래된', '값')], QImage(), ''
        with patch.object(BusyDetailWorker, 'read', side_effect=read):
            w._set_busy(True)
            w._update_selection_detail('preview')
            self.wait_for(lambda: w._busy_read_worker is None)
        self.assertIsNone(w._busy_read_current_key)
        self.assertEqual(w.selection_metadata_table.item(0, 1).text(), '메타정보 없음')
        self.assertIn('변경', w.preview_image_view.text())
        w._set_busy(False)

    def test_missing_target_never_starts_background_reader(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        self.target.unlink()
        with patch.object(BusyDetailWorker, 'read') as read:
            self.window._set_busy(True)
            self.click(1)
        read.assert_not_called()
        self.assertEqual(self.window.selection_metadata_table.item(0, 1).text(), '메타정보 없음')
        self.assertIn('아직 없습니다', self.window.selection_detail.toPlainText())
        self.window._set_busy(False)

    def test_background_reader_is_independent_of_running_engine(self):
        w = self.window
        w._preview_metadata_fingerprints.clear()
        w._set_busy(True)
        w._update_selection_detail('preview')
        self.wait_for(lambda: w._busy_read_worker is None)
        w.engine.describe_media_path.assert_not_called()
        self.assertFalse(w.preview_image_view.pixmap().isNull())
        self.assertGreater(w.selection_metadata_table.rowCount(), 0)
        w._set_busy(False)

    def test_read_error_is_distinct_from_changed_or_missing_file(self):
        w = self.window
        w._preview_metadata_fingerprints.clear()
        with patch('photo_organizer.ui.busy_detail_worker.ReadOnlyInspector.describe_media_path', side_effect=RuntimeError('test read failure')):
            w._set_busy(True)
            w._update_selection_detail('preview')
            self.wait_for(lambda: w._busy_read_worker is None)
        self.assertIn('파일 조회 실패', w.preview_image_view.text())
        self.assertIn('test read failure', w.selection_metadata_table.item(0, 1).text())
        self.assertNotIn(str(self.source), w._detail_metadata_cache)
        self.assertIsNone(w._busy_read_current_key)
        w._set_busy(False)

    def test_busy_video_thumbnail_has_bounded_process_timeout(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        from PySide6.QtCore import QSize
        import subprocess
        video = self.base / 'video.mp4'
        video.write_bytes(b'test video')
        fingerprint = self.window._file_detail_fingerprint(video)
        with patch('photo_organizer.video_thumbnail.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 15)) as run:
            result = BusyDetailWorker.read((1, video, fingerprint, QSize(640, 420), (), False))
        self.assertEqual(run.call_args.kwargs['timeout'], 15)
        self.assertTrue(result[5].isNull())
        self.assertEqual(result[3], fingerprint)

    def test_limited_busy_video_metadata_does_not_replace_full_idle_lookup(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        w = self.window
        video = self.base / 'video.mp4'
        video.write_bytes(b'test video')
        def read(request):
            token, path, before, *_rest = request
            return token, path, before, before, [('작업 중 조회', 'ffprobe only')], QImage(), ''
        with patch.object(BusyDetailWorker, 'read', side_effect=read), patch.object(w, '_selected_image_source_path', return_value=str(video)):
            w._set_busy(True)
            w._update_selection_detail('preview')
            self.wait_for(lambda: w._busy_read_worker is None)
        self.assertEqual(w._metadata_entries_for_path(video), [('작업 중 조회', 'ffprobe only')])
        self.assertNotIn(str(video), w._detail_metadata_cache)
        w._set_busy(False)
        self.assertEqual(w._busy_detail_metadata_cache, {})
        w.engine.describe_media_path.reset_mock()
        w.engine.describe_media_path.return_value = [('전체 조회', 'MediaInfo')]
        w.engine.describe_media_path.side_effect = None
        self.assertEqual(w._metadata_entries_for_path(video), [('전체 조회', 'MediaInfo')])
        w.engine.describe_media_path.assert_called_once_with(video)

    def test_close_waits_for_reader_then_clears_pending_close_intent(self):
        from photo_organizer.ui.busy_detail_worker import BusyDetailWorker
        w = self.window
        w.show()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def read(request):
            entered.set()
            release.wait(10)
            token, path, before, *_rest = request
            return token, path, before, before, [], QImage(), ''
        with patch.object(BusyDetailWorker, 'read', side_effect=read):
            w._set_busy(True)
            w._update_selection_detail('preview')
            self.wait_for(entered.is_set)
            w._set_busy(False)
            w._job_dirty = False
            w.close()
            self.assertTrue(w._busy_read_close_pending)
            self.assertTrue(w.isVisible())
            release.set()
            self.wait_for(lambda: w._busy_read_worker is None and not w.isVisible())
        self.assertFalse(w._busy_read_close_pending)
