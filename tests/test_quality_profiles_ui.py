import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QComboBox
from photo_organizer.models import AppSettings
from photo_organizer.config import ConfigManager
from photo_organizer.ui.main_window import SettingsDialog, MainWindow


class QualityProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_labels_values_and_dynamic_description(self):
        dialog = SettingsDialog(None, AppSettings())
        self.addCleanup(dialog.close)
        combo = dialog.video_quality_combo
        self.assertEqual(combo.count(), 6)
        self.assertEqual(combo.currentData(), 'balanced')
        self.assertEqual(combo.sizeAdjustPolicy(), QComboBox.AdjustToContents)
        for index, (key, crf, audio) in enumerate([('very_high',18,192),('high_plus',20,192),('high',22,160),('balanced',24,128),('compact',26,128),('small',28,96)]):
            combo.setCurrentIndex(index)
            self.assertEqual(combo.currentData(), key)
            self.assertIn(f'CRF {crf}', combo.currentText())
            self.assertIn(f'오디오 {audio} kbps', combo.currentText())
            self.assertTrue(dialog.video_quality_description.text())
        combo.setCurrentIndex(4)
        self.assertIn('균형보다', dialog.video_quality_description.text())
        self.assertIn('낮을수록', dialog.video_quality_hint.text())
        self.assertIn('최대 가로 크기', dialog.video_quality_hint.text())
        dialog._restore_defaults()
        self.assertEqual(combo.currentData(), 'balanced')

    def test_existing_keys_and_invalid_fallback(self):
        for key in ['high','balanced','small','invalid']:
            dialog=SettingsDialog(None, AppSettings(mobile_output_video_quality=key))
            self.assertEqual(dialog.video_quality_combo.currentData(), key if key != 'invalid' else 'balanced')
            dialog.close()

    def test_configuration_roundtrip_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager=ConfigManager(Path(temporary))
            for key in ['very_high','high_plus','high','balanced','compact','small']:
                manager.save(AppSettings(mobile_output_video_quality=key))
                self.assertEqual(manager.load().mobile_output_video_quality,key)
            manager.config_path.write_text('[app]\nsource_path="keep"\nmobile_output_video_quality="bad"',encoding='utf-8')
            settings=manager.load()
            self.assertEqual(settings.mobile_output_video_quality,'balanced')
            self.assertEqual(settings.source_path,'keep')

    def test_summary_uses_new_names_and_values(self):
        config=Mock()
        config.load.return_value=AppSettings(mobile_output_video_quality='compact')
        window=MainWindow(Mock(),config)
        self.addCleanup(window.close)
        text=window.mobile_output_summary.text()
        self.assertIn('용량 절약',text)
        self.assertIn('CRF 26',text)
