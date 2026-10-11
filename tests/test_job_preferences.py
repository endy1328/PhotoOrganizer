import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from photo_organizer.models import AppSettings
from photo_organizer.config import ConfigManager

class JobPreferencesTests(unittest.TestCase):
    def test_defaults_and_toml_roundtrip(self):
        defaults=AppSettings()
        self.assertTrue(defaults.restore_last_job)
        self.assertTrue(defaults.autosave_job_changes)
        with tempfile.TemporaryDirectory() as temp:
            manager=ConfigManager(Path(temp))
            defaults.restore_last_job=False
            defaults.autosave_job_changes=False
            manager.save(defaults)
            loaded=manager.load()
            self.assertFalse(loaded.restore_last_job)
            self.assertFalse(loaded.autosave_job_changes)

    def test_invalid_settings_and_legacy_json(self):
        with tempfile.TemporaryDirectory() as temp:
            manager=ConfigManager(Path(temp))
            manager.config_path.write_text('[app]\nsource_path="keep"\nrestore_last_job="false"\nautosave_job_changes=0',encoding='utf-8')
            loaded=manager.load()
            self.assertTrue(loaded.restore_last_job)
            self.assertTrue(loaded.autosave_job_changes)
            self.assertEqual(loaded.source_path,'keep')
            manager.config_path.unlink()
            manager.legacy_config_path.write_text(json.dumps({'restore_last_job':False,'autosave_job_changes':True}),encoding='utf-8')
            loaded=manager.load()
            self.assertFalse(loaded.restore_last_job)
            self.assertTrue(loaded.autosave_job_changes)
