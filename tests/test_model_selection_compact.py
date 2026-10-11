import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from photo_organizer.ui.model_selection import ModelSelectionPanel


class ModelSelectionCompactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.items = [SimpleNamespace(model_name=f"CAMERA_{i:02d}", media_type="photo", included=True,
                                      output_model_name=f"별칭_{i:02d}") for i in range(20)]
        self.panel = ModelSelectionPanel()
        self.panel.set_items(self.items)
        self.panel.setEnabled(True)
        self.panel.resize(300, 200)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_default_collapsed_retains_header_and_summary(self):
        self.assertFalse(self.panel.toggle_button.isChecked())
        self.assertFalse(self.panel.scroll_area.isVisible())
        self.assertTrue(self.panel.title_label.isVisible())
        self.assertTrue(self.panel.summary_label.isVisible())
        self.assertLessEqual(self.panel.minimumSizeHint().height(), 45)
        self.assertEqual(self.panel.title_label.geometry().y(), self.panel.summary_label.geometry().y())
        self.assertLessEqual(self.panel.minimumSizeHint().width(), 300)

    def test_expanded_twenty_models_scroll_without_growing_panel(self):
        self.panel.toggle_button.click()
        self.app.processEvents()
        self.assertTrue(self.panel.scroll_area.isVisible())
        self.assertLessEqual(self.panel.scroll_area.height(), 120)
        self.assertGreater(self.panel.scroll_area.verticalScrollBar().maximum(), 0)
        last = self.panel.checkboxes["CAMERA_19"]
        self.panel.scroll_area.ensureWidgetVisible(last)
        self.app.processEvents()
        self.assertGreater(self.panel.scroll_area.verticalScrollBar().value(), 0)

    def test_selection_alias_summary_and_busy_lock_are_preserved(self):
        selected = []
        self.panel.selection_changed.connect(selected.append)
        self.panel.checkboxes["CAMERA_00"].setChecked(False)
        self.assertNotIn("CAMERA_00", selected[-1])
        self.assertIn("CAMERA_00 → 별칭_00", self.panel.checkboxes["CAMERA_00"].text())
        self.items[0].included = False
        self.panel.refresh(self.items)
        self.assertIn("처리 19건", self.panel.summary_label.text())
        self.assertIn("제외 1건", self.panel.summary_label.text())
        self.panel.setEnabled(False)
        self.assertFalse(self.panel.toggle_button.isEnabled())
        self.assertFalse(self.panel.checkboxes["CAMERA_01"].isEnabled())


if __name__ == "__main__":
    unittest.main()
