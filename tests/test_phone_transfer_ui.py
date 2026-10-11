import importlib.util
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication


class FakeBackend:
    def __init__(self):
        self.thread_ids = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def list_devices(self):
        self.thread_ids.append(threading.get_ident())
        return [SimpleNamespace(id="phone", name="Test phone")]

    def open_device(self, device_id):
        self.thread_ids.append(threading.get_ident())

    def list_children(self, parent_id):
        self.thread_ids.append(threading.get_ident())
        return [SimpleNamespace(id="storage", name="Internal storage", is_folder=True)] if parent_id == "DEVICE" else []

    def create_folder(self, parent_id, name):
        self.thread_ids.append(threading.get_ident())
        return "new-folder"

    def close(self):
        self.thread_ids.append(threading.get_ident())
        self.closed = True


class PhoneTransferUiTests(unittest.TestCase):
    def setUp(self):
        for method in ("_confirm_job_transition", "_restore_recent_job", "_autosave_job"):
            fixture = patch(f"photo_organizer.ui.main_window.MainWindow.{method}", new=(lambda self: True) if method == "_confirm_job_transition" else (lambda self: None))
            fixture.start()
            self.addCleanup(fixture.stop)
        self.logger_patch = patch("photo_organizer.ui.phone_transfer_dialog.AppLogger", create=True)
        self.logger_factory = self.logger_patch.start()
        self.addCleanup(self.logger_patch.stop)
        self.addCleanup(self._close_worker_dialogs)

    def _close_worker_dialogs(self):
        for widget in self.app.topLevelWidgets():
            if hasattr(widget, "worker") and isinstance(widget.worker, QThread):
                widget.reject()
                widget.worker.wait(2000)
        self.app.processEvents()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Worker did not finish in time")

    def test_dialog_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("photo_organizer.ui.phone_transfer_dialog"))

    def test_main_window_has_copy_button_disabled_while_busy(self):
        from photo_organizer.ui.main_window import MainWindow
        from photo_organizer.models import AppSettings
        from unittest.mock import Mock
        settings = Mock()
        settings.load.return_value = AppSettings()
        window = MainWindow(Mock(), settings)
        try:
            self.assertTrue(hasattr(window, "phone_transfer_button"))
            window._set_busy(True)
            self.assertFalse(window.phone_transfer_button.isEnabled())
            window._set_busy(False)
            self.assertTrue(window.phone_transfer_button.isEnabled())
        finally:
            window.close()

    def test_settings_preserve_phone_conflict_policy_and_pass_it_to_dialog(self):
        from photo_organizer.ui.main_window import MainWindow, SettingsDialog
        from photo_organizer.models import AppSettings
        from unittest.mock import Mock
        self.assertTrue(hasattr(AppSettings(), "phone_conflict_policy"))
        settings = AppSettings(phone_conflict_policy="skip")
        dialog = SettingsDialog(None, settings)
        self.assertEqual(dialog.phone_conflict_combo.currentData(), "skip")
        dialog.phone_conflict_combo.setCurrentIndex(dialog.phone_conflict_combo.findData("rename"))
        settings = dialog.to_settings(settings)
        self.assertEqual(settings.phone_conflict_policy, "rename")
        config = Mock()
        config.load.return_value = settings
        engine = Mock()
        engine.base_dir = Path("logs_base")
        window = MainWindow(engine, config)
        window.target_edit.setText("target")
        try:
            self.assertEqual(window._current_settings().phone_conflict_policy, "rename")
            with patch("photo_organizer.ui.main_window.Path.is_dir", return_value=True), patch("photo_organizer.ui.phone_transfer_dialog.PhoneTransferDialog") as factory:
                window._open_phone_transfer()
                self.assertEqual(factory.call_args.kwargs["conflict_policy"], "rename")
        finally:
            window.close()

    def test_empty_outputs_show_guidance_and_disable_copy(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        backend = FakeBackend()
        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[]):
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend)
            self.wait_until(lambda: not dialog.busy)
            self.assertIn("모바일 출력 파일이 없습니다", dialog.status_label.text())
            self.assertFalse(dialog.copy_button.isEnabled())
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())

    def test_selected_conflict_policy_reaches_transfer_worker_and_core(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog, transfer_outputs
        backend = FakeBackend()
        folder = SimpleNamespace(path=Path("target/output_20240101_CAM"), files=(Path("target/output_20240101_CAM/a.jpg"),), size=8)
        results = [SimpleNamespace(source=folder.files[0], status="COPIED", message="renamed", remote_id="file")]
        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[folder]), patch("photo_organizer.phone_transfer.transfer_outputs", return_value=results) as core:
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend, conflict_policy="rename")
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            self.assertIn("새 이름으로 복사", dialog.conflict_policy_label.text())
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            dialog._start_transfer()
            self.wait_until(lambda: not dialog.busy)
            self.assertEqual(core.call_args.kwargs["conflict_policy"], "rename")
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())

    def test_browse_failure_clears_stale_destination_and_disables_copy(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        backend = FakeBackend()
        folder = SimpleNamespace(path=Path("target/output_20240101_CAM"), files=(Path("target/output_20240101_CAM/a.jpg"),), size=8)
        original_list = backend.list_children

        def list_children(parent):
            if parent == "storage":
                raise OSError("USB disconnected")
            return original_list(parent)

        backend.list_children = list_children
        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[folder]):
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend)
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            self.assertFalse(dialog.device_open)
            self.assertFalse(dialog.copy_button.isEnabled())
            self.assertEqual(dialog.destination_stack, [("DEVICE", "기기")])
            self.assertIn("다시 찾고", dialog.status_label.text())
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())

    def test_unverified_results_require_device_refresh_before_retry(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        backend = FakeBackend()
        folder = SimpleNamespace(path=Path("target/output_20240101_CAM"), files=(Path("target/output_20240101_CAM/a.jpg"),), size=8)
        results = [SimpleNamespace(source=folder.files[0], status="UNVERIFIED", message="size not available", remote_id="file")]
        log_threads = []
        self.logger_factory.return_value.write_session_log.side_effect = lambda events: log_threads.append(threading.get_ident())
        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[folder]), patch("photo_organizer.ui.phone_transfer_dialog.transfer_outputs", return_value=results) as transfer:
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend, log_base_dir=Path("specific_logs"))
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            dialog._start_transfer()
            self.wait_until(lambda: not dialog.busy)
            self.assertEqual(dialog.results_table.item(0, 0).text(), "검증 미완료")
            self.assertEqual(dialog.results_table.item(0, 2).text(), "size not available")
            self.assertTrue(self.logger_factory.return_value.write_session_log.called)
            event = self.logger_factory.return_value.write_session_log.call_args.args[0][0]
            self.assertEqual(event.source_path, str(folder.files[0]))
            self.assertIn("UNVERIFIED", event.message)
            self.assertEqual(event.level, "WARNING")
            self.assertEqual(event.target_path, "file")
            self.logger_factory.assert_called_with(Path("specific_logs"))
            self.assertEqual(log_threads[0], backend.thread_ids[0])
            self.assertFalse(dialog.copy_button.isEnabled())
            self.assertFalse(dialog.device_open)
            self.assertEqual(dialog.remote_tree.topLevelItemCount(), 0)
            dialog.refresh_button.click()
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            dialog._start_transfer()
            self.wait_until(lambda: not dialog.busy)
            self.assertEqual(transfer.call_count, 2)
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())

    def test_log_failure_does_not_discard_successful_transfer_results(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        backend = FakeBackend()
        folder = SimpleNamespace(path=Path("target/output_20240101_CAM"), files=(Path("target/output_20240101_CAM/a.jpg"),), size=8)
        results = [SimpleNamespace(source=folder.files[0], status="COPIED", message="verified", remote_id="file")]
        self.logger_factory.return_value.write_session_log.side_effect = OSError("log access denied")
        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[folder]), patch("photo_organizer.ui.phone_transfer_dialog.transfer_outputs", return_value=results) as transfer:
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend)
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            dialog._start_transfer()
            self.wait_until(lambda: not dialog.busy)
            self.assertEqual(dialog.results_table.item(0, 0).text(), "복사 완료")
            self.assertIn("로그 저장 실패", dialog.status_label.text())
            self.assertEqual(transfer.call_count, 1)
            self.assertEqual(transfer.call_args.kwargs.get("conflict_policy"), "overwrite")
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())

    def test_browse_and_copy_run_on_one_worker_thread_and_cancel_is_responsive(self):
        self.assertIsNotNone(importlib.util.find_spec("photo_organizer.ui.phone_transfer_dialog"))
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        backend = FakeBackend()
        folder = SimpleNamespace(path=Path("target/output_20240101_CAM"), files=(Path("target/output_20240101_CAM/a.jpg"),), size=8)
        started = threading.Event()
        calls = []

        def transfer(backend_arg, parent_id, folders, progress=None, cancelled=None, conflict_policy=None):
            self.assertEqual(conflict_policy, "overwrite")
            calls.append((threading.get_ident(), parent_id, folders))
            started.set()
            while not cancelled():
                time.sleep(0.005)
            return [SimpleNamespace(source=folder.files[0], status="CANCELLED", message="stopped", remote_id="")]

        with patch("photo_organizer.ui.phone_transfer_dialog.scan_outputs", return_value=[folder]), patch("photo_organizer.ui.phone_transfer_dialog.transfer_outputs", side_effect=transfer):
            dialog = PhoneTransferDialog(None, Path("target"), backend_factory=lambda: backend)
            dialog.show()
            self.wait_until(lambda: dialog.remote_tree.topLevelItemCount() == 1 and not dialog.busy)
            self.assertEqual(dialog.output_tree.topLevelItem(0).checkState(0), Qt.Checked)
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)
            self.assertIn("Internal storage", dialog.destination_label.text())
            dialog._start_transfer()
            self.wait_until(started.is_set)
            self.assertTrue(dialog.cancel_button.isEnabled())
            dialog.cancel_button.click()
            self.wait_until(lambda: dialog.results_table.rowCount() == 1 and not dialog.busy)
            self.assertEqual(dialog.results_table.item(0, 0).text(), "취소")
            self.assertEqual(calls[0][1], "storage")
            self.assertEqual(calls[0][2], [folder])
            dialog.reject()
            self.wait_until(lambda: not dialog.worker.isRunning())
            self.assertTrue(backend.closed)
        self.assertEqual(len(set(backend.thread_ids + [calls[0][0]])), 1)
        self.assertNotEqual(calls[0][0], threading.get_ident())

