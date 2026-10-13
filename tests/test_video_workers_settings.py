import json
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import test_execution_controller as fixture
from photo_organizer.config import ConfigManager
from photo_organizer.models import AppSettings, OrganizeRequest, PreviewBundle
from photo_organizer.job_store import _settings, JobState, save_job, load_job
from photo_organizer.resume_models import processing_settings, ensure_plan
from photo_organizer.ui.main_window import SettingsDialog


class VideoWorkersSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ExecutionControllerTests.setUpClass()

    def test_defaults_and_toml_roundtrip_normalization(self):
        self.assertEqual(AppSettings().video_workers, 1)
        self.assertEqual(OrganizeRequest(Path('s'), Path('t')).video_workers, 1)
        with tempfile.TemporaryDirectory() as folder:
            manager = ConfigManager(Path(folder))
            manager.save(AppSettings(video_workers=2))
            self.assertEqual(manager.load().video_workers, 2)
            for value in ('true', '0', '3', '"2"'):
                manager.config_path.write_text('[app]\nvideo_workers='+value)
                self.assertEqual(manager.load().video_workers, 1)

    def test_legacy_json_normalization(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ConfigManager(Path(folder))
            for value, expected in ((2,2),(True,1),(3,1),('2',1)):
                manager.config_path.unlink(missing_ok=True)
                manager.legacy_config_path.write_text(json.dumps({'video_workers':value}))
                self.assertEqual(manager.load().video_workers, expected)

    def test_job_strict_validation_default_and_roundtrip(self):
        base = {'source_path':'', 'target_path':'', 'operation_mode':'copy'}
        self.assertEqual(_settings(base).video_workers, 1)
        for value in (True,0,3,'2',2.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _settings(dict(base, video_workers=value))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'job.pojob.json'
            save_job(JobState(settings=AppSettings(video_workers=2)),path)
            self.assertEqual(load_job(path).settings.video_workers, 2)

    def test_serial_plan_keeps_preexisting_settings_hash_projection(self):
        job = JobState(phase='PREVIEW_READY', preview_bundle=PreviewBundle(),
                       settings=AppSettings(source_path=str(Path.cwd() / 'source'),
                                            target_path=str(Path.cwd() / 'target')))
        self.assertNotIn('video_workers', processing_settings(job.settings))
        ensure_plan(job)
        signature = job.plan_signature
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.pojob.json'
            save_job(job, path)
            data = json.loads(path.read_text(encoding='utf-8'))
            del data['settings']['video_workers']
            path.write_text(json.dumps(data), encoding='utf-8')
            old = load_job(path)
            self.assertEqual(old.settings.video_workers, 1)
            self.assertEqual(old.plan_signature, signature)
        job.execution_started = True
        ensure_plan(job)
        self.assertEqual(job.plan_signature,signature)
        job.settings.video_workers = 2
        with self.assertRaises(ValueError):
            ensure_plan(job)

    def test_ui_request_signature_reset_and_readonly(self):
        case=fixture.ExecutionControllerTests();case.setUp()
        self.addCleanup(case.doCleanups)
        window=case.window
        dialog=SettingsDialog(window,window.settings)
        self.addCleanup(dialog.close)
        before=window._request_signature(window._request_from_inputs(True))
        dialog._set_combo_value(dialog.video_workers_combo,2)
        window.settings=dialog.to_settings(window.settings)
        request=window._request_from_inputs(True)
        self.assertEqual(request.video_workers,2)
        self.assertEqual(window._current_settings().video_workers,2)
        self.assertNotEqual(before,window._request_signature(request))
        window._update_mobile_output_summary()
        self.assertIn('영상 2개',window.mobile_output_summary.text())
        dialog._restore_defaults()
        self.assertEqual(dialog.video_workers_combo.currentData(),1)
        readonly=SettingsDialog(window,AppSettings(video_workers=2),read_only=True)
        self.addCleanup(readonly.close)
        self.assertFalse(readonly.video_workers_combo.isEnabled())
        readonly._restore_defaults()
        self.assertEqual(readonly.video_workers_combo.currentData(),2)
