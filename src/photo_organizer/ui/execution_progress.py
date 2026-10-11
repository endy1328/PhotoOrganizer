"""Display-only execution dock; opening or closing it never controls execution."""
from collections import deque
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QHeaderView, QLabel,
                              QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .responsive_layout import ElidedLabel


def _duration(seconds):
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


class ExecutionProgressPanel(QDockWidget):
    """Public methods are GUI-thread updates from immutable operation snapshots."""
    def __init__(self, parent=None, *, clock=monotonic):
        super().__init__('실행 진행', parent)
        self.setObjectName('photo_execution_progress_dock')
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.setMinimumSize(160, 100)
        self._clock = clock
        self._started = None
        self._finished_elapsed = None
        self._active = {}
        self._rendered_active_keys = ()
        self._history = deque(maxlen=50)
        self._completed = self._total = 0
        self._success = self._failed = self._skipped = 0
        self.running = False
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        self.status_label = ElidedLabel('실행 대기')
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.time_label = QLabel('전체 경과 00:00')
        self.estimate_label = QLabel('남은 시간: 계산 전')
        self.estimate_label.setWordWrap(True)
        self.recovery_label = QLabel()
        self.recovery_label.setWordWrap(True)
        self.recovery_label.hide()
        for label in (self.status_label, self.summary_label, self.time_label,
                      self.estimate_label, self.recovery_label):
            layout.addWidget(label)
        layout.addWidget(QLabel('현재 처리 파일'))
        self.active_table = self._table(['파일', '단계', '파일 경과'])
        self.active_table.setMaximumHeight(160)
        layout.addWidget(self.active_table)
        layout.addWidget(QLabel('최근 완료 / 실패 (최대 50건)'))
        self.history_table = self._table(['파일', '결과', '안내'])
        layout.addWidget(self.history_table, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(0, 0)
        scroll.setWidget(content)
        self.setWidget(scroll)
        self._refresh_summary()
        self.hide()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setWordWrap(False)
        table.setMinimumSize(0, 70)
        table.verticalHeader().setDefaultSectionSize(25)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setColumnWidth(0, 210)
        table.setColumnWidth(1, 95)
        table.setColumnWidth(2, 90)
        return table

    def begin(self, total, estimate_text=''):
        self._started = self._clock()
        self._finished_elapsed = None
        self._completed, self._total = 0, max(0, int(total))
        self._success = self._failed = self._skipped = 0
        self._active.clear()
        self._rendered_active_keys = ()
        self._history.clear()
        self.active_table.setRowCount(0)
        self.history_table.setRowCount(0)
        self.recovery_label.hide()
        self.running = True
        self.status_label.setText('실행 준비')
        self.set_eta_text(estimate_text or '남은 시간: 계산 중')
        self._refresh_summary()
        self._refresh_time()

    def update_activities(self, activities):
        now = self._clock()
        active = {}
        for activity in activities:
            key = activity.key
            started = self._active[key][2] if key in self._active else now
            active[key] = (str(activity.source_path), activity.stage, started)
        self._active = active
        keys = tuple(active)
        changed = keys != self._rendered_active_keys
        if changed:
            self.active_table.setRowCount(len(active))
            self._rendered_active_keys = keys
        stages = {'metadata': '메타정보 조회', 'copy': '정리 파일 생성',
                  'main': '정리 파일 생성', 'output': '출력 변환', 'source_remove': '원본 이동 마무리'}
        for row, (path, stage, started) in enumerate(active.values()):
            values = (Path(path).name, stages.get(stage, stage), _duration(now - started))
            for column, value in enumerate(values):
                cell = None if changed else self.active_table.item(row, column)
                if cell is None:
                    cell = QTableWidgetItem(value)
                    self.active_table.setItem(row, column, cell)
                elif cell.text() != value:
                    cell.setText(value)
                if column == 0 and cell.toolTip() != path:
                    cell.setToolTip(path)
        self._refresh_summary()
        self._refresh_time()

    def update_progress(self, message, current, total):
        self._total = max(0, int(total))
        self._completed = min(self._total, max(0, int(current)))
        self.status_label.setText(str(message))
        self._refresh_summary()
        self._refresh_time()

    def set_eta_text(self, text):
        self.estimate_label.setText(str(text))
        self.estimate_label.setToolTip(str(text))

    def set_result_counts(self, succeeded, failed, incomplete):
        """Lossless operation totals, independent of bounded recent-file history."""
        self._success = max(0, int(succeeded))
        self._failed = max(0, int(failed))
        self._skipped = max(0, int(incomplete))
        self._refresh_summary()

    def set_recovery_counts(self, *, kept=0, pending=0, failed=0, blocked=0):
        self.recovery_label.setText(f'복구: 완료 유지 {kept} / 미처리 {pending} / 실패 {failed} / 확인 필요 {blocked}')
        self.recovery_label.setVisible(any((kept, pending, failed, blocked)))

    def note_result(self, source_path, status, message=''):
        status = str(status).upper()
        self._history.appendleft((str(source_path), status, str(message)))
        if status in {'ERROR', 'FAILED', 'UNCERTAIN'}:
            self._failed += 1
        elif status in {'SKIPPED', 'SIZE_EXCLUDED', 'NOT_REQUIRED'}:
            self._skipped += 1
        elif status in {'SUCCESS', 'DONE'}:
            self._success += 1
        self.history_table.setRowCount(len(self._history))
        labels = {'SUCCESS': '완료', 'DONE': '완료', 'ERROR': '실패', 'FAILED': '실패',
                  'UNCERTAIN': '확인 필요', 'SKIPPED': '제외', 'SIZE_EXCLUDED': '용량 제외',
                  'INCOMPLETE': '미완료'}
        for row, (path, state, detail) in enumerate(self._history):
            values = (Path(path).name, labels.get(state, state), detail)
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(path if column == 0 else value)
                self.history_table.setItem(row, column, cell)
        self._refresh_summary()

    def finish(self, stopped=False, error=None):
        if self._started is not None:
            self._finished_elapsed = max(0, self._clock() - self._started)
        self.running = False
        self._active.clear()
        self._rendered_active_keys = ()
        self.active_table.setRowCount(0)
        self.status_label.setText('실행 오류: ' + str(error) if error is not None else
                                  '중단 — 완료된 결과를 유지합니다.' if stopped else '실행 종료')
        self._refresh_summary()
        self._refresh_time()

    def _refresh_summary(self):
        self.summary_label.setText(f'처리 {self._completed} / {self._total} · 진행 중 {len(self._active)}\n'
                                   f'완료 {self._success} / 실패 {self._failed} / 미완료/제외 {self._skipped}')

    def _refresh_time(self):
        elapsed = self._finished_elapsed if self._finished_elapsed is not None else (
            max(0, self._clock() - self._started) if self._started is not None else 0)
        self.time_label.setText('전체 경과 ' + _duration(elapsed))
