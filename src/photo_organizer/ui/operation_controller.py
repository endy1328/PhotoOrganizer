"""Cooperative controls and worker lifetime in the Qt GUI thread."""
from PySide6.QtCore import QEventLoop, QTimer, Qt, Slot
from PySide6.QtWidgets import QPushButton, QTableWidgetItem

from ..operation_control import OperationControl
from ..engine import OrganizerEngine
from .operation_worker import OperationWorker


class OperationControllerMixin:
    def _init_operation_controller(self):
        self._operation_control = None
        self._operation_worker = None
        self._operation_active = False
        self._operation_stopped = False
        self._operation_autosave_pending = False
        self._operation_poll_timer = QTimer(self)
        self._operation_poll_timer.setInterval(100)
        self._operation_poll_timer.timeout.connect(lambda: self._poll_operation_control())

    def _build_operation_controls(self, row):
        self.pause_button = QPushButton('일시정지')
        self.stop_button = QPushButton('중단')
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_operation_pause)
        self.stop_button.clicked.connect(self._request_operation_stop)
        self.pause_button.setToolTip('현재 파일과 완료 기록을 마친 뒤 일시정지합니다. 정지 요청 중에도 재개할 수 있습니다.')
        self.stop_button.setToolTip('현재 파일을 마친 뒤 남은 파일을 시작하지 않습니다. 긴 영상은 변환이 끝난 뒤 중단합니다.')
        row.addWidget(self.pause_button)
        row.addWidget(self.stop_button)

    def _toggle_operation_pause(self):
        control = self._operation_control
        if not self._operation_active or control is None or control.stop_requested:
            return
        if control.pause_requested or control.paused:
            control.resume()
            self._set_status('재개 — 작업을 계속 진행합니다.')
        else:
            control.request_pause()
        self._poll_operation_control()

    def _request_operation_stop(self):
        if self._operation_active and self._operation_control:
            self._operation_control.request_stop()
            self._poll_operation_control()

    def _poll_operation_control(self):
        control = self._operation_control
        active = self._operation_active and control is not None
        self.pause_button.setEnabled(active and not control.stop_requested)
        self.stop_button.setEnabled(active and not control.stop_requested)
        if not active:
            self.pause_button.setText('일시정지')
            return
        self.pause_button.setText('재개' if control.pause_requested or control.paused else '일시정지')
        if control.stop_requested:
            self._set_status('중단 요청 중 — 현재 파일과 완료 기록을 마친 뒤 중단합니다.')
        elif control.paused:
            self._set_status('일시정지 — 재개 또는 중단을 선택할 수 있습니다.')
        elif control.pause_requested:
            self._set_status('일시정지 요청 중 — 현재 파일과 완료 기록을 마친 뒤 대기합니다.')

    @Slot(str, int, int)
    def _receive_operation_progress(self, message, current, total):
        self._update_progress(message, current, total)
        self._poll_operation_control()

    def _run_engine_operation(self, method, *args, **kwargs):
        self._operation_stopped = False
        kwargs.pop('progress_callback', None)
        if not isinstance(self.engine, OrganizerEngine):
            return method(*args, progress_callback=self._update_progress, **kwargs)
        self._job_timer.stop()
        self._operation_autosave_pending = True
        control = OperationControl()
        self._operation_control = control
        self._operation_active = True
        options = dict(kwargs, control=control)
        worker = OperationWorker(method, args, options, self)
        self._operation_worker = worker
        loop = QEventLoop(self)
        worker.progress.connect(self._receive_operation_progress, Qt.QueuedConnection)
        worker.finished.connect(loop.quit, Qt.QueuedConnection)
        was_busy = self._busy
        self._set_busy(True)
        self._poll_operation_control()
        self._operation_poll_timer.start()
        try:
            worker.start()
            loop.exec()
            worker.wait()
            self._operation_stopped = control.stopped
            if worker.error is not None:
                raise worker.error
            return worker.result
        finally:
            self._operation_poll_timer.stop()
            self._operation_active = False
            self._operation_worker = None
            self._poll_operation_control()
            worker.deleteLater()
            loop.deleteLater()
            if not was_busy:
                self._set_busy(False)

    def _schedule_operation_autosave(self):
        if self._operation_autosave_pending and not self._busy and not self._operation_active:
            QTimer.singleShot(0, self._restart_operation_autosave)

    def _restart_operation_autosave(self):
        if not self._operation_autosave_pending or self._busy or self._operation_active:
            return
        self._operation_autosave_pending = False
        if (self._job_dirty and self._job_state is not None and not self._job_restoring
                and self._global_settings.autosave_job_changes):
            self._job_timer.start()

    def _show_operation_error(self, title, error):
        self._set_status(f'{title}: {error}')
        self._set_idle_progress(f'{title}: {error}')
        row = self.error_table.rowCount()
        self.error_table.insertRow(row)
        self.error_table.setItem(row, 0, QTableWidgetItem(self.source_edit.text().strip()))
        self.error_table.setItem(row, 1, QTableWidgetItem(f'{title}: {error}'))
