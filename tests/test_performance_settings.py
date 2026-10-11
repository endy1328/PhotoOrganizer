import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication
from photo_organizer.models import AppSettings, OrganizeRequest, PreviewBundle, PreviewItem
from photo_organizer.execution_journal import ExecutionJournal
from photo_organizer.config import ConfigManager
from photo_organizer.job_store import JobState, _settings, save_job, load_job
from photo_organizer.resume_models import ensure_plan, plan_manifest
from photo_organizer.ui.main_window import MainWindow, SettingsDialog


class PerformanceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_new_defaults_and_config_roundtrip(self):
        settings = AppSettings()
        self.assertEqual((settings.video_encoder, settings.conversion_speed, settings.photo_workers), ('auto', 'balanced', 2))
        request = OrganizeRequest(Path('source'), Path('target'))
        self.assertEqual(request.photo_workers, 2)
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory))
            settings.video_encoder, settings.conversion_speed, settings.photo_workers = 'gpu', 'fast', 4
            config.save(settings)
            actual = config.load()
            self.assertEqual((actual.video_encoder, actual.conversion_speed, actual.photo_workers), ('gpu', 'fast', 4))

    def test_old_job_keeps_cpu_serial_and_old_signature(self):
        settings = _settings({'source_path': '', 'target_path': '', 'operation_mode': 'copy'})
        self.assertEqual((settings.video_encoder, settings.conversion_speed, settings.photo_workers), ('cpu', 'balanced', 1))
        job = JobState(settings=settings, preview_bundle=PreviewBundle())
        manifest = plan_manifest(job)
        for key in ('video_encoder', 'conversion_speed', 'photo_workers'):
            self.assertNotIn(key, manifest['settings'])
        job.plan_signature = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        job.execution_started = True
        ensure_plan(job)
        job.settings.photo_workers = 2
        with self.assertRaises(ValueError):
            ensure_plan(job)

    def test_legacy_cpu_serial_journal_register_update_and_changed_setting_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source' / '20240101_120000_X.jpg'
            target_directory = base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
            name = '20240101_120000_X_0001.jpg'
            row = PreviewItem('one', 'photo', str(source), str(target_directory), str(target_directory / name), name, 'NEW', '2024-01-01T12:00:00', 'filename', 'X', 'filename', [])
            settings = AppSettings(source_path=str(source.parent), target_path=str(base / 'target'), video_encoder='cpu', conversion_speed='balanced', photo_workers=1)
            job = JobState(phase='PREVIEW_READY', settings=settings, preview_bundle=PreviewBundle(preview_items=[row]))
            ensure_plan(job)
            journal = ExecutionJournal(base)
            journal.register(job)
            attempt = str(uuid4())
            journal.update(job, 'one', 'main', {'state': 'IN_PROGRESS', 'attempt_id': attempt})
            self.assertEqual(job.checkpoint, 1)
            job.settings.photo_workers = 2
            with self.assertRaises(ValueError):
                journal.update(job, 'one', 'main', {'state': 'FAILED', 'attempt_id': attempt, 'message': 'test'})

    def test_job_rejects_invalid_performance_settings(self):
        base = {'source_path': '', 'target_path': '', 'operation_mode': 'copy'}
        for key, value in [('video_encoder', 'cuda'), ('conversion_speed', 'turbo'), ('photo_workers', 3), ('photo_workers', True), ('photo_workers', 0)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                _settings(dict(base, **{key: value}))

    def test_new_job_roundtrip_and_performance_plan_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.pojob.json'
            save_job(JobState(), path)
            actual = load_job(path)
            self.assertEqual(actual.settings.video_encoder, 'auto')
            self.assertEqual(actual.settings.photo_workers, 2)
            data = json.loads(path.read_text(encoding='utf-8'))
            for key in ('video_encoder', 'conversion_speed', 'photo_workers'):
                del data['settings'][key]
            path.write_text(json.dumps(data), encoding='utf-8')
            old = load_job(path)
            self.assertEqual((old.settings.video_encoder, old.settings.conversion_speed, old.settings.photo_workers), ('cpu', 'balanced', 1))
        job = JobState(preview_bundle=PreviewBundle())
        ensure_plan(job)
        before = job.plan_signature
        job.settings.conversion_speed = 'fast'
        ensure_plan(job)
        self.assertNotEqual(before, job.plan_signature)

    def test_old_config_uses_new_defaults_and_invalid_values_normalize(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory))
            for content in ('[app]\noperation_mode="move"\n', '[app]\nvideo_encoder="cuda"\nconversion_speed="turbo"\nphoto_workers=true\n'):
                config.config_path.write_text(content, encoding='utf-8')
                actual = config.load()
                self.assertEqual((actual.video_encoder, actual.conversion_speed, actual.photo_workers), ('auto', 'balanced', 2))

    def test_dialog_defaults_propagation_and_started_lock(self):
        config = Mock()
        config.load.return_value = AppSettings(restore_last_job=False, autosave_job_changes=False)
        window = MainWindow(Mock(), config)
        try:
            dialog = SettingsDialog(window, window.settings)
            dialog._set_combo_value(dialog.video_encoder_combo, 'gpu')
            dialog._set_combo_value(dialog.conversion_speed_combo, 'fast')
            dialog._set_combo_value(dialog.photo_workers_combo, 4)
            window.settings = dialog.to_settings(window.settings)
            request = window._request_from_inputs(True)
            self.assertEqual((request.video_encoder, request.conversion_speed, request.photo_workers), ('gpu', 'fast', 4))
            self.assertEqual(window._current_settings().photo_workers, 4)
            self.assertEqual(window._request_signature(request)[-3:], ('gpu', 'fast', '4'))
            dialog._restore_defaults()
            self.assertEqual(dialog.to_settings(window.settings).photo_workers, 2)
            window._job_state.execution_started = True
            locked = SettingsDialog(window, window.settings)
            self.assertFalse(locked.performance_group.isEnabled())
            locked._restore_defaults()
            self.assertEqual(locked.to_settings(window.settings).video_encoder, 'gpu')
        finally:
            window._job_dirty = False
            window.close()
