"""Execution confirmation and display-only progress integration."""
from time import monotonic
from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QPushButton

from ..execution_estimate import EstimateHistory, estimate_execution, remaining_estimate
from .execution_progress import ExecutionProgressPanel


def duration_text(seconds):
    if seconds is None:
        return '계산 중'
    seconds = max(0, ceil(seconds))
    if seconds < 60:
        return f'{seconds}초'
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f'{minutes}분 {seconds}초'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}시간 {minutes}분'


def estimate_text(estimate):
    return f'약 {duration_text(estimate.lower_seconds)} ~ {duration_text(estimate.upper_seconds)} ({estimate.basis})'


class ExecutionConfirmDialog(QDialog):
    def __init__(self, parent, estimate, settings, *, mode='initial'):
        super().__init__(parent)
        self.setWindowTitle('실행 확인' if mode == 'initial' else '복구 실행 확인')
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        encoder = {'auto': '자동', 'cpu': 'CPU', 'gpu': 'NVIDIA GPU'}.get(settings.video_encoder, settings.video_encoder)
        operation = '이동' if settings.operation_mode == 'move' else '복사'
        self.summary_label = QLabel(
            f'사진 {estimate.photo_count}개 / 동영상 {estimate.video_count}개\n'
            f'처리 방식: {operation} / 사진 동시 처리: {settings.photo_workers}개\n'
            f'영상 인코더: {encoder} / 모바일 출력: {"사용" if settings.mobile_output_enabled else "사용 안 함"}')
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.estimate_label = QLabel('예상 소요 시간: ' + estimate_text(estimate))
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)
        note = QLabel('초기 추정은 파일 크기·영상 길이·설정과 처리 이력을 기준으로 합니다. '
                      '디스크와 GPU 상태에 따라 달라지며 실행 후 실제 속도로 보정합니다.\n\n진행하시겠습니까?')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('실행')
        self.buttons.button(QDialogButtonBox.Cancel).setText('취소')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)


class ExecutionControllerMixin:
    def _init_execution_controller(self):
        base = getattr(self.config_manager, 'base_dir', None)
        self._estimate_history_path = base / 'execution_estimates.json' if isinstance(base, Path) else None
        self._estimate_history = (EstimateHistory.load(self._estimate_history_path)
                                  if self._estimate_history_path else EstimateHistory())
        self._pending_execution_estimate = None
        self._pending_recovery_counts = None
        self._execution_tracking = False
        self._execution_clock = monotonic

    def _build_execution_progress(self, button_row):
        self.execution_progress_button = QPushButton('진행 상세')
        self.execution_progress_button.clicked.connect(self._show_execution_progress)
        button_row.addWidget(self.execution_progress_button)
        self.execution_progress_dock = ExecutionProgressPanel(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.execution_progress_dock, Qt.Vertical)
        self._execution_dock_sized = False
        self.execution_progress_dock.hide()
        self._dock_user_visibility['execution_progress'] = False
        self.execution_progress_dock.visibilityChanged.connect(self._execution_dock_visibility_changed)
        self.execution_progress_dock.dockLocationChanged.connect(lambda area: self._dock_placement_changed('execution_progress'))
        self.execution_progress_dock.topLevelChanged.connect(lambda floating: self._dock_placement_changed('execution_progress'))
        self.execution_progress_dock.installEventFilter(self)
        self.view_menu.insertAction(self.reset_docks_action, self.execution_progress_dock.toggleViewAction())

    def _execution_dock_visibility_changed(self, visible):
        if not self._arranging_docks:
            self._dock_user_visibility['execution_progress'] = not self.execution_progress_dock.isHidden()

    def _show_execution_progress(self):
        self.execution_progress_dock.show()
        if not self._execution_dock_sized and not self._custom_dock_layout and not self.execution_progress_dock.isFloating():
            self._arrange_default_execution_progress()
        self._execution_dock_sized = True
        # Only a deliberate user click raises this panel; work never steals focus.
        self.execution_progress_dock.raise_()

    def _arrange_default_execution_progress(self):
        old_guard = self._arranging_docks
        self._arranging_docks = True
        try:
            panel = self.execution_progress_dock
            self.removeDockWidget(panel)
            self.addDockWidget(Qt.BottomDockWidgetArea, panel, Qt.Vertical)
            panel.show()
            self.layout().activate()
            self.resizeDocks([panel], [220], Qt.Vertical)
            if self.width() < 1400:
                self.resizeDocks([self.image_dock, self.detail_dock], [120, 120], Qt.Vertical)
        finally:
            self._arranging_docks = old_guard

    def _confirm_execution(self, settings, bundle, *, job=None, item_ids=None, mode='initial'):
        self._pending_execution_estimate = None
        self._pending_recovery_counts = None
        estimate = estimate_execution(bundle, settings,
                                      source_fingerprints=getattr(job, 'source_fingerprints', None),
                                      ledger=getattr(job, 'ledger', None), history=self._estimate_history,
                                      item_ids=item_ids)
        dialog = ExecutionConfirmDialog(self, estimate, settings, mode=mode)
        accepted = dialog.exec() == QDialog.Accepted
        dialog.deleteLater()
        if not accepted:
            return False
        self._pending_execution_estimate = estimate
        return True

    def _begin_execution_progress(self):
        estimate = self._pending_execution_estimate
        self._pending_execution_estimate = None
        if estimate is None:
            return
        self._execution_estimate = estimate
        self._execution_started_at = self._execution_clock()
        self._execution_paused_at = None
        self._execution_pause_seconds = 0.0
        self._execution_completed_ids = set()
        self._execution_count = 0
        self._execution_total = estimate.photo_count + estimate.video_count
        self._execution_had_error = False
        self._execution_last_eta_tick = -1
        self._execution_tracking = True
        self.execution_progress_dock.begin(self._execution_total, estimate_text(estimate))
        if self._pending_recovery_counts:
            self.execution_progress_dock.set_recovery_counts(**self._pending_recovery_counts)
        self._pending_recovery_counts = None
        self.status_label.hide()
        self.execution_summary_label.show()
        self._refresh_execution_progress(force=True)

    def _execution_progress_received(self, message, current, total):
        if self._execution_tracking and total > 0:
            self._execution_count, self._execution_total = current, total
            self.execution_progress_dock.update_progress(message, current, total)

    def _refresh_execution_progress(self, *, force=False):
        if not self._execution_tracking:
            return
        control = self._operation_control
        for result in control.drain_file_results() if control is not None else ():
            self._execution_had_error |= result.status != 'SUCCESS'
            self.execution_progress_dock.note_result(result.source_path, result.status, result.message)
        if control is not None:
            summary = control.result_summary()
            self._execution_completed_ids = summary.completed_keys
            self._execution_had_error |= summary.had_error
            self.execution_progress_dock.set_result_counts(summary.succeeded, summary.failed, summary.incomplete)
        activities = control.activity_snapshot() if control is not None else ()
        self.execution_progress_dock.update_activities(activities)
        now = self._execution_clock()
        paused = bool(control and control.paused)
        if paused and self._execution_paused_at is None:
            self._execution_paused_at = now
        elif not paused and self._execution_paused_at is not None:
            self._execution_pause_seconds += now - self._execution_paused_at
            self._execution_paused_at = None
        elapsed = max(0.0, now - self._execution_started_at)
        active_elapsed = max(0.0, elapsed - self._execution_pause_seconds -
                             (now - self._execution_paused_at if self._execution_paused_at is not None else 0))
        self._execution_active_elapsed = active_elapsed
        tick = int(elapsed)
        if not force and tick == self._execution_last_eta_tick:
            return
        self._execution_last_eta_tick = tick
        remaining = remaining_estimate(self._execution_estimate, active_elapsed,
                                       completed_item_ids=self._execution_completed_ids, paused=paused)
        if control and control.stop_requested:
            phase, eta = '중단 요청 중', '현재 파일 완료 후 중단'
        elif paused:
            phase, eta = '일시정지', '재개 후 보정'
        elif control and control.pause_requested:
            phase, eta = '일시정지 요청 중', '현재 파일 완료 후 대기'
        else:
            phase = '실행 중'
            eta = ('0초' if self._execution_count >= self._execution_total else
                   '초기 예상 초과 — 처리 속도 확인 중' if remaining.total_seconds <= 0 and activities else
                   f'{duration_text(remaining.lower_seconds)} ~ {duration_text(remaining.upper_seconds)}')
        text = (f'{phase} · 완료 {self._execution_count}/{self._execution_total} · '
                f'경과 {duration_text(elapsed)} · 남은 시간 {eta}')
        self.execution_summary_label.setText(text)
        self.execution_summary_label.setToolTip(text)
        self.execution_progress_dock.status_label.setText(phase)
        self.execution_progress_dock.set_eta_text('예상 남은 시간: ' + eta)

    def _finish_execution_progress(self, *, error=None):
        if not self._execution_tracking:
            return
        self._refresh_execution_progress(force=True)
        stopped = self._operation_stopped
        if error is None and not stopped and not self._execution_had_error and self._execution_count >= self._execution_total:
            if self._estimate_history.record(self._execution_estimate, self._execution_active_elapsed, completed=True):
                if self._estimate_history_path is not None:
                    self._estimate_history.save(self._estimate_history_path)
        self.execution_progress_dock.finish(stopped=stopped, error=error)
        phase = '오류' if error is not None or self._execution_had_error else '중단' if stopped else '완료'
        self.execution_summary_label.setText(
            f'{phase} · 완료 {self._execution_count}/{self._execution_total} · '
            f'경과 {duration_text(self._execution_clock() - self._execution_started_at)}')
        self._execution_tracking = False
        self.status_label.show()
        self.execution_summary_label.hide()
