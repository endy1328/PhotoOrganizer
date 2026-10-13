import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication


class PhoneModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from photo_organizer.ui.phone_model_selection import PhoneModelSelection
        self.widget=PhoneModelSelection()
        self.addCleanup(self.widget.close)

    @staticmethod
    def folder(name):
        return SimpleNamespace(path=Path('target')/name)

    def test_folder_identification_preserves_model_and_unknown(self):
        identify=self.widget.model_for_folder
        self.assertEqual(identify(self.folder('OuTpUt_20241012_Galaxy_Z_Fold6')), 'Galaxy_Z_Fold6')
        self.assertEqual(identify(Path('output_20241012_UNKNOWN')), 'UNKNOWN')
        for name in ('output_misc','output_20241012_','other_20241012_CAM','output_20241342_CAM'):
            self.assertEqual(identify(self.folder(name)), '미분류')

    def test_defaults_all_selected_and_folder_counts(self):
        self.widget.set_folders([self.folder('output_20241012_CAM_A'),self.folder('output_20241013_CAM_A'),
                                 self.folder('output_20241012_UNKNOWN'),self.folder('output_misc')])
        self.assertEqual(self.widget.selected_models(),{'CAM_A','UNKNOWN','미분류'})
        self.assertIn('폴더 2개',self.widget.checkboxes['CAM_A'].text())
        self.assertLessEqual(self.widget.scroll_area.maximumHeight(),100)

    def test_rescan_keeps_known_choices_and_new_models_default_on(self):
        w=self.widget
        w.set_folders([self.folder('output_20241012_A'),self.folder('output_20241012_B')])
        w.checkboxes['A'].setChecked(False)
        w.set_folders([self.folder('output_20241013_A'),self.folder('output_20241013_C')])
        self.assertEqual(w.selected_models(),{'C'})
        w.set_folders([self.folder('output_20241014_A'),self.folder('output_20241014_B')])
        self.assertEqual(w.selected_models(),{'B'})

    def test_none_means_empty_and_signal_contains_model_set(self):
        w=self.widget;seen=[]
        w.selection_changed.connect(seen.append)
        w.set_folders([self.folder('output_20241012_A')])
        w.checkboxes['A'].setChecked(False)
        self.assertEqual(w.selected_models(),set())
        self.assertEqual(seen[-1],set())
        w.set_folders([])
        self.assertEqual(w.selected_models(),set())

    def test_wrapped_models_scroll_in_small_height(self):
        w=self.widget
        w.set_folders([self.folder(f'output_20241012_Camera_{i:02d}') for i in range(30)])
        w.resize(420,150);w.show();self.app.processEvents()
        self.assertLessEqual(w.scroll_area.height(),100)
        self.assertGreater(w.scroll_area.verticalScrollBar().maximum(),0)

    def test_all_none_buttons_emit_once_and_preserve_rescan_choices(self):
        w=self.widget
        w.set_folders([self.folder('output_20241012_A'),self.folder('output_20241012_B')])
        seen=[];w.selection_changed.connect(seen.append)
        w.none_button.click()
        self.assertEqual(seen,[set()])
        w.set_folders([self.folder('output_20241013_A'),self.folder('output_20241013_B')])
        self.assertEqual(w.selected_models(),set())
        seen.clear()
        w.all_button.click()
        self.assertEqual(seen,[{'A','B'}])
