import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import test_execution_controller as fixtures
from PySide6.QtCore import QEventLoop, QTimer
from photo_organizer.models import AppSettings
from photo_organizer.ui.main_window import SettingsDialog


class PerformanceBenchmarkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ExecutionControllerTests.setUpClass()
        cls.app=fixtures.ExecutionControllerTests.app

    def wait_worker(self, dialog):
        loop=QEventLoop()
        dialog._worker.finished.connect(loop.quit)
        QTimer.singleShot(3000,loop.quit)
        loop.exec()
        self.app.processEvents()
        self.assertFalse(dialog.running)

    def test_background_results_require_manual_recommendation_apply(self):
        from photo_organizer.ui.performance_benchmark_dialog import PerformanceBenchmarkDialog
        observed=[]
        report=SimpleNamespace(cases=(SimpleNamespace(name='video_serial',elapsed=2.0,success=True,error=''),),
                               video_workers=2,mixed_media_workers=True,notes=('테스트 안내',))
        def runner(settings, source, target, **kwargs):
            observed.append(threading.current_thread())
            kwargs['progress_callback']('측정 중')
            return report
        dialog=PerformanceBenchmarkDialog(None,AppSettings(),Path('source'),Path.cwd(),runner=runner)
        self.addCleanup(dialog.close)
        applied=[];dialog.recommendation_applied.connect(lambda video,mixed:applied.append((video,mixed)))
        dialog._start()
        self.wait_worker(dialog)
        self.assertIsNot(observed[0],threading.current_thread())
        self.assertEqual(applied,[])
        self.assertEqual(dialog.results_table.rowCount(),1)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog._apply_recommendation()
        self.assertEqual(applied,[(2,True)])

    def test_cancel_close_waits_for_worker_and_does_not_apply(self):
        from photo_organizer.ui.performance_benchmark_dialog import PerformanceBenchmarkDialog
        started=threading.Event()
        def runner(settings,source,target,**kwargs):
            started.set()
            control=kwargs['control']
            while not control.stop_requested:
                time.sleep(.01)
            raise RuntimeError('사용자 중단')
        dialog=PerformanceBenchmarkDialog(None,AppSettings(),Path('source'),Path.cwd(),runner=runner)
        self.addCleanup(dialog.close)
        dialog.show();dialog._start()
        self.assertTrue(started.wait(2))
        dialog.close()
        self.assertTrue(dialog._close_pending)
        self.wait_worker(dialog)
        self.assertFalse(dialog.isVisible())
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_settings_manual_apply_reset_and_busy_lock(self):
        settings=AppSettings()
        dialog=SettingsDialog(None,settings)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.mixed_media_checkbox.isChecked())
        dialog._apply_benchmark_recommendation(2,True)
        updated=dialog.to_settings(settings)
        self.assertEqual(updated.video_workers,2)
        self.assertTrue(updated.mixed_media_workers)
        self.assertEqual(settings.video_workers,1)
        dialog._restore_defaults()
        self.assertFalse(dialog.mixed_media_checkbox.isChecked())
        locked=SettingsDialog(None,settings,read_only=True)
        self.addCleanup(locked.close)
        self.assertFalse(locked.benchmark_button.isEnabled())
        self.assertFalse(locked.mixed_media_checkbox.isEnabled())

    def test_missing_target_prevents_worker_and_source_selection_is_explicit(self):
        from photo_organizer.ui.performance_benchmark_dialog import PerformanceBenchmarkDialog
        from unittest.mock import Mock
        runner=Mock()
        dialog=PerformanceBenchmarkDialog(None,AppSettings(),None,None,runner=runner)
        self.addCleanup(dialog.close)
        dialog._start()
        self.assertFalse(dialog.running)
        self.assertIn('Target',dialog.status_label.text())
        dialog.target_edit.setText(str(Path.cwd()))
        dialog._start()
        self.assertFalse(dialog.running)
        self.assertIn('Source',dialog.status_label.text())
        runner.assert_not_called()

    def test_mixed_setting_propagates_without_saving_and_changes_request_signature(self):
        case=fixtures.ExecutionControllerTests();case.setUp()
        self.addCleanup(case.doCleanups)
        window=case.window
        before=window._request_signature(window._request_from_inputs(True))
        dialog=SettingsDialog(window,window.settings)
        self.addCleanup(dialog.close)
        dialog.mixed_media_checkbox.setChecked(True)
        window.settings=dialog.to_settings(window.settings)
        self.assertTrue(window._current_settings().mixed_media_workers)
        request=window._request_from_inputs(True)
        self.assertTrue(request.mixed_media_workers)
        self.assertNotEqual(before,window._request_signature(request))
        window.config_manager.save.assert_not_called()

    def test_relative_times_and_failed_baseline_recommendation_guard(self):
        from photo_organizer.ui.performance_benchmark_dialog import PerformanceBenchmarkDialog
        report=SimpleNamespace(cases=(
            SimpleNamespace(name='video_serial',elapsed=2,success=True,error=''),
            SimpleNamespace(name='video_parallel',elapsed=1,success=True,error=''),
            SimpleNamespace(name='mixed_serial',elapsed=2,success=True,error=''),
            SimpleNamespace(name='mixed_parallel',elapsed=3,success=True,error='')),
            video_workers=2,mixed_media_workers=False,notes=())
        dialog=PerformanceBenchmarkDialog(None,AppSettings(),Path('source'),Path.cwd(),runner=lambda *a,**k:report)
        self.addCleanup(dialog.close)
        dialog._start();self.wait_worker(dialog)
        self.assertEqual(dialog.results_table.item(1,2).text(),'시간 50.0% 감소')
        self.assertEqual(dialog.results_table.item(3,2).text(),'시간 50.0% 증가')
        dialog._progress('mixed_parallel')
        self.assertIn('사진·영상 혼합 동시',dialog.status_label.text())
        report.cases[0].success=False
        dialog._start();self.wait_worker(dialog)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn('추천',dialog.status_label.text())

    def test_long_notes_scroll_without_growing_small_window(self):
        from photo_organizer.ui.performance_benchmark_dialog import PerformanceBenchmarkDialog
        from PySide6.QtWidgets import QScrollArea
        report=SimpleNamespace(cases=(SimpleNamespace(name='video_serial',elapsed=1,success=True,error=''),),
                               video_workers=1,mixed_media_workers=False,notes=tuple('긴 측정 안내 '+str(i) for i in range(80)))
        dialog=PerformanceBenchmarkDialog(None,AppSettings(),Path('source'),Path.cwd(),runner=lambda *a,**k:report)
        self.addCleanup(dialog.close)
        dialog.resize(602,480);dialog.show()
        dialog._start();self.wait_worker(dialog)
        self.app.processEvents()
        self.assertEqual(dialog.size().width(),602)
        self.assertEqual(dialog.size().height(),480)
        self.assertGreaterEqual(dialog.results_table.height(),140)
        self.assertGreater(dialog.findChild(QScrollArea).verticalScrollBar().maximum(),0)
        self.assertLessEqual(dialog.apply_button.mapTo(dialog,dialog.apply_button.rect().bottomRight()).y(),dialog.height())
