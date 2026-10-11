import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSplitter, QWidget
from photo_organizer.ui.view_preferences import ViewPreferences


class ViewPreferencesReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_oversized_splitter_integer_is_ignored_before_qt_conversion(self):
        splitter = QSplitter(Qt.Horizontal)
        self.addCleanup(splitter.close)
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        splitter.setSizes([100, 200])
        original = splitter.sizes()
        prefs = ViewPreferences.__new__(ViewPreferences)
        prefs.window = SimpleNamespace(workspace_splitter=splitter)
        prefs._saved_sizes = {str(Qt.Horizontal.value): [10 ** 100, 1]}
        prefs.restore_splitter()
        self.assertEqual(splitter.sizes(), original)


if __name__ == "__main__":
    unittest.main()
