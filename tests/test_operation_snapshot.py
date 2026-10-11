import copy
import threading
import unittest
from PySide6.QtCore import QTimer
import test_operation_ui as fixtures
from photo_organizer.models import OrganizeRequest
from photo_organizer.job_store import JobState
from pathlib import Path


class OperationSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.OperationUiTests.setUpClass()
        cls.app = fixtures.OperationUiTests.app

    setUp = fixtures.OperationUiTests.setUp
    cleanup_window = fixtures.OperationUiTests.cleanup_window

    def test_submitted_request_settings_are_frozen_before_worker_starts(self):
        w = self.window
        request = OrganizeRequest(Path('source'), Path('target'), photo_workers=4)
        captured = []
        def inspect():
            snapshot = getattr(w, '_active_operation_settings', None)
            captured.append(copy.deepcopy(snapshot))
            w.settings.photo_workers = 1
        QTimer.singleShot(5, inspect)
        def operation(req, *, control, progress_callback):
            threading.Event().wait(.05)
            return 'ok'
        self.assertEqual(w._run_engine_operation(operation, request), 'ok')
        self.assertIsNotNone(captured[0])
        self.assertEqual(captured[0].photo_workers, 4)
        self.assertIsNone(w._active_operation_settings)

    def test_activity_snapshot_is_delivered_on_poll_and_cleared_on_error(self):
        w = self.window
        displays = []
        w._update_active_file_display = lambda activities: displays.append(tuple(activities))
        def operation(*, control, progress_callback):
            with control.file_activity('one', 'source/test.jpg', 'copy'):
                threading.Event().wait(.15)
                raise ValueError('test error')
        with self.assertRaisesRegex(ValueError, 'test error'):
            w._run_engine_operation(operation)
        self.assertTrue(any(values and values[0].source_path == 'source/test.jpg' for values in displays))
        self.assertEqual(displays[-1], ())
        self.assertIsNone(w._active_operation_settings)

    def test_resume_settings_snapshot_comes_from_job_and_owns_mapping_values(self):
        job = JobState(settings=copy.deepcopy(self.window.settings))
        job.settings.photo_workers = 4
        job.settings.model_name_mappings = {'SM-F956N': 'Fold6'}
        self.window.settings.photo_workers = 1
        snapshot = self.window._snapshot_operation_settings((job,), {})
        job.settings.model_name_mappings['SM-F956N'] = 'Changed'
        self.assertEqual(snapshot.photo_workers, 4)
        self.assertEqual(snapshot.model_name_mappings, {'SM-F956N': 'Fold6'})
