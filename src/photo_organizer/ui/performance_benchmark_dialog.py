"""Responsive, opt-in local benchmark; recommendations never save settings."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QFileDialog, QTableWidget,
                              QTableWidgetItem, QHeaderView, QAbstractItemView,
                              QScrollArea, QWidget)
from ..operation_control import OperationControl


def _run_benchmark(*args, **kwargs):
    from ..performance_benchmark import run_benchmark
    return run_benchmark(*args, **kwargs)


class BenchmarkWorker(QThread):
    progress = Signal(str)

    def __init__(self, settings, source, target, video, photo, runner, parent=None):
        super().__init__(parent)
        self.settings = deepcopy(settings)
        self.source, self.target, self.video, self.photo = source, target, video, photo
        self.runner = runner
        self.control = OperationControl()
        self.report = None
        self.error = None

    def run(self):
        try:
            self.report = self.runner(self.settings, self.source, self.target,
                                      video_path=self.video, photo_path=self.photo,
                                      control=self.control, progress_callback=self.progress.emit)
        except BaseException as exc:
            self.error = exc


class PerformanceBenchmarkDialog(QDialog):
    recommendation_applied = Signal(int, bool)
    CASE_LABELS = {'video_serial': '동영상 1개씩', 'video_parallel': '동영상 2개 동시',
                   'mixed_serial': '사진·영상 순차', 'mixed_parallel': '사진·영상 혼합 동시'}

    def __init__(self, parent, settings, source_path, target_path, *, runner=_run_benchmark):
        super().__init__(parent)
        self.setWindowTitle('변환 성능 테스트')
        self.setWindowModality(Qt.WindowModal)
        available = self.screen().availableGeometry()
        self.resize(min(620, available.width() - 40), min(520, available.height() - 60))
        self.setMinimumSize(320, 260)
        self.settings = deepcopy(settings)
        self._runner = runner
        self._worker = None
        self._report = None
        self.running = False
        self._close_pending = False
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(0, 0)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        note = QLabel('현재 출력 설정으로 동영상 1개/2개 동시 변환과 사진·영상 혼합 처리를 비교합니다. '
                      '원본은 보존하고 Target 아래 임시 출력만 사용합니다. 디스크·GPU 상태에 따라 결과는 달라집니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self._inputs = []
        self.source_edit = self._path_row(form, 'Source', str(source_path or ''), directory=True)
        self.target_edit = self._path_row(form, 'Target (필수)', str(target_path or ''), directory=True)
        self.video_edit = self._path_row(form, '영상 샘플 (선택)', '', directory=False, video=True)
        self.photo_edit = self._path_row(form, '사진 샘플 (선택)', '', directory=False)
        layout.addLayout(form)
        self.video_edit.setPlaceholderText('비우면 Source 아래에서 자동 선택')
        self.photo_edit.setPlaceholderText('비우면 자동 선택, 없으면 영상 비교만 수행')
        self.status_label = QLabel('테스트 전 — 추천은 적용 버튼을 눌러야 반영됩니다.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(['측정', '소요 시간', '기준 대비', '결과'])
        self.results_table.setMinimumHeight(140)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.results_table.horizontalHeader().setSectionsMovable(True)
        self.results_table.setColumnWidth(0, 230)
        self.results_table.setColumnWidth(2, 140)
        self.results_table.setColumnWidth(3, 260)
        layout.addWidget(self.results_table)
        self.recommendation_label = QLabel()
        self.recommendation_label.setWordWrap(True)
        layout.addWidget(self.recommendation_label)
        row = QHBoxLayout()
        self.start_button = QPushButton('테스트 시작')
        self.cancel_button = QPushButton('테스트 중단')
        self.apply_button = QPushButton('추천값 적용')
        self.close_button = QPushButton('닫기')
        self.cancel_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        for button in (self.start_button, self.cancel_button, self.apply_button, self.close_button):
            row.addWidget(button)
        outer.addLayout(row)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self.request_cancel)
        self.apply_button.clicked.connect(self._apply_recommendation)
        self.close_button.clicked.connect(self.reject)

    def _path_row(self, form, title, value, *, directory, video=False):
        row = QHBoxLayout()
        edit = QLineEdit(value)
        button = QPushButton('선택')
        def browse():
            if directory:
                path = QFileDialog.getExistingDirectory(self, title, edit.text())
            else:
                extension = '동영상 (*.mp4 *.mov *.m4v *.avi *.mkv *.wmv)' if video else '사진 (*.jpg *.jpeg *.png *.heic)'
                path, _ = QFileDialog.getOpenFileName(self, title, self.source_edit.text(), extension)
            if path:
                edit.setText(path)
        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(title, row)
        self._inputs.extend((edit, button))
        return edit

    def _start(self):
        if self.running:
            return
        if not self.target_edit.text().strip() or not Path(self.target_edit.text().strip()).is_absolute():
            self.status_label.setText('임시 출력을 생성할 Target의 절대 경로를 선택해주세요.')
            return
        if not self.source_edit.text().strip() and not self.video_edit.text().strip():
            self.status_label.setText('자동 샘플을 찾을 Source 또는 영상 샘플을 선택해주세요.')
            return
        source = (Path(self.source_edit.text().strip()) if self.source_edit.text().strip() else
                  Path(self.video_edit.text().strip()).parent)
        target = Path(self.target_edit.text().strip())
        video = Path(self.video_edit.text().strip()) if self.video_edit.text().strip() else None
        photo = Path(self.photo_edit.text().strip()) if self.photo_edit.text().strip() else None
        self._report = None
        self.apply_button.setEnabled(False)
        self.results_table.setRowCount(0)
        self.recommendation_label.clear()
        self.running = True
        self._close_pending = False
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        for widget in self._inputs:
            widget.setEnabled(False)
        self.status_label.setText('성능 측정 준비 중')
        self._worker = BenchmarkWorker(self.settings, source, target, video, photo, self._runner, self)
        self._worker.progress.connect(self._progress)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _finished(self):
        worker = self._worker
        self.running = False
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        for widget in self._inputs:
            widget.setEnabled(True)
        if worker.error is not None or worker.control.stop_requested:
            self.status_label.setText('테스트 중단' if worker.control.stop_requested else f'테스트 실패: {worker.error}')
        else:
            self._report = worker.report
            cases = {case.name: case for case in self._report.cases}
            self.results_table.setRowCount(len(self._report.cases))
            for row, case in enumerate(self._report.cases):
                baseline = cases.get({'video_parallel': 'video_serial', 'mixed_parallel': 'mixed_serial'}.get(case.name))
                comparison = '기준' if case.name in {'video_serial', 'mixed_serial'} else '비교 불가'
                if baseline is not None and baseline.success and case.success and baseline.elapsed > 0:
                    difference = (case.elapsed / baseline.elapsed - 1) * 100
                    comparison = f'시간 {abs(difference):.1f}% {"감소" if difference < 0 else "증가"}' if difference else '시간 차이 없음'
                for column, value in enumerate((self.CASE_LABELS.get(case.name, case.name), f'{case.elapsed:.2f}초', comparison,
                                                '완료' if case.success else case.error or '실패')):
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(value)
                    self.results_table.setItem(row, column, cell)
            self.recommendation_label.setText(
                f'추천: 동영상 {self._report.video_workers}개 동시 / 사진·영상 혼합 '
                f'{"사용" if self._report.mixed_media_workers else "사용 안 함"}\n' + '\n'.join(self._report.notes))
            baseline = cases.get('video_serial')
            recommendable = baseline is not None and baseline.success
            self.status_label.setText('측정 완료 — 추천값을 적용하려면 아래 버튼을 누르세요.' if recommendable else
                                      '측정 완료 — 동영상 1개씩 비교가 실패해 추천값을 적용할 수 없습니다.')
            self.apply_button.setEnabled(recommendable)
        worker.deleteLater()
        if self._close_pending:
            self._close_pending = False
            super().reject()

    def request_cancel(self):
        if self.running:
            self._worker.control.request_stop()
            self.cancel_button.setEnabled(False)
            self.status_label.setText('테스트 중단 요청 중 — 임시 파일 정리를 기다립니다.')

    def _progress(self, message):
        self.status_label.setText(self.CASE_LABELS.get(message, str(message)) + ' 측정 중')

    def _apply_recommendation(self):
        if not self.running and self._report is not None and self.apply_button.isEnabled():
            self.recommendation_applied.emit(self._report.video_workers, self._report.mixed_media_workers)
            self.accept()

    def reject(self):
        if self.running:
            self._close_pending = True
            self.request_cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.running:
            self._close_pending = True
            self.request_cancel()
            event.ignore()
        else:
            super().closeEvent(event)
