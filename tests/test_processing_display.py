import unittest
from types import SimpleNamespace
import test_responsive_ui as fixtures


class ProcessingDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResponsiveUiTests.setUpClass()
        cls.app = fixtures.ResponsiveUiTests.app

    setUp = fixtures.ResponsiveUiTests.setUp
    cleanup = fixtures.ResponsiveUiTests.cleanup

    def test_parallel_activity_names_and_full_path_tooltip(self):
        w = self.window
        items = tuple(SimpleNamespace(key=str(i), source_path=f'C:/source/photo{i}.jpg', stage='output') for i in range(4))
        w._update_active_file_display(items)
        for i in range(4):
            self.assertIn(f'photo{i}.jpg', w.active_files_label.text())
            self.assertIn(f'C:/source/photo{i}.jpg', w.active_files_label.toolTip())
        self.assertTrue(w.active_files_label.isVisible())
        w._update_active_file_display(())
        self.assertFalse(w.active_files_label.isVisible())

    def test_short_screen_preserves_current_files_and_list(self):
        w = self.window
        for width, height, minimum in ((602, 480, 100), (1024, 650, 150)):
            w.resize(width, height)
            self.app.processEvents()
            w._update_active_file_display((SimpleNamespace(key='1', source_path='C:/video.mp4', stage='output'),))
            self.app.processEvents()
            self.assertTrue(w.active_files_label.isVisible())
            self.assertFalse(w.mobile_output_summary.isVisible())
            self.assertGreaterEqual(w.preview_table.viewport().height(), minimum)
        w._update_active_file_display(())
        self.assertTrue(w.mobile_output_summary.isVisible())
