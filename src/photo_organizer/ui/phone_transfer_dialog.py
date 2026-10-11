from __future__ import annotations

from pathlib import Path
import sys
from queue import Queue
from threading import Event
from typing import Callable

from ..logging_utils import AppLogger
from ..models import LogEvent

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


def scan_outputs(target: Path):
    from ..phone_transfer import scan_outputs as scan
    return scan(target)


def transfer_outputs(backend, parent_id, folders, progress=None, cancelled=None, conflict_policy="overwrite", limit_video_bytes=None):
    from ..phone_transfer import transfer_outputs as transfer
    return transfer(backend, parent_id, folders, progress=progress, cancelled=cancelled, conflict_policy=conflict_policy, limit_video_bytes=limit_video_bytes)


def _default_backend():
    from ..phone_wpd import WpdBackend
    return WpdBackend()


class PhoneTransferWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)
    progress = Signal(object)

    def __init__(self, backend_factory: Callable, log_base_dir: Path, parent=None, conflict_policy: str = "overwrite", video_limit_bytes=None):
        super().__init__(parent)
        self.backend_factory = backend_factory
        self.log_base_dir = log_base_dir
        self.conflict_policy = conflict_policy
        self.video_limit_bytes = video_limit_bytes
        self.jobs = Queue()
        self.cancel_event = Event()

    def submit(self, operation: str, *args) -> None:
        self.jobs.put((operation, args))

    def shutdown(self) -> None:
        self.cancel_event.set()
        self.jobs.put(None)

    def run(self) -> None:
        try:
            with self.backend_factory() as backend:
                while True:
                    job = self.jobs.get()
                    if job is None:
                        break
                    operation, args = job
                    try:
                        if operation == "initialize":
                            from ..phone_transfer import plan_video_transfer
                            folders = scan_outputs(args[0])
                            plans = [plan_video_transfer([folder], self.video_limit_bytes) for folder in folders]
                            result = (folders, backend.list_devices(), plans)
                        elif operation == "open":
                            backend.open_device(args[0])
                            result = backend.list_children("DEVICE")
                        elif operation == "browse":
                            result = backend.list_children(args[0])
                        elif operation == "create":
                            backend.create_folder(args[0], args[1])
                            result = backend.list_children(args[0])
                        elif operation == "transfer":
                            options = {"limit_video_bytes": self.video_limit_bytes} if self.video_limit_bytes is not None else {}
                            results = transfer_outputs(backend, args[0], args[1], progress=self.progress.emit, cancelled=self.cancel_event.is_set, conflict_policy=self.conflict_policy, **options)
                            levels = {"FAILED": "ERROR", "UNVERIFIED": "WARNING", "CANCELLED": "WARNING"}
                            events = [LogEvent(levels.get(entry.status, "INFO"), f"USB TRANSFER {entry.status}: {entry.message}", str(entry.source), entry.remote_id) for entry in results]
                            result = {"results": results, "log_error": self._write_log(events)}
                        else:
                            raise ValueError("지원하지 않는 작업입니다.")
                        self.completed.emit(operation, result)
                    except Exception as exc:
                        message = str(exc)
                        if operation == "transfer":
                            error = self._write_log([LogEvent("ERROR", f"USB TRANSFER 실패: {message}", target_path=str(args[0]))])
                            if error:
                                message += f"; 로그 저장 실패: {error}"
                        self.failed.emit(operation, message)
        except Exception as exc:
            self.failed.emit("initialize", str(exc))

    def _write_log(self, events: list[LogEvent]) -> str:
        try:
            AppLogger(self.log_base_dir).write_session_log(events)
            return ""
        except Exception as exc:
            return str(exc)


class PhoneTransferDialog(QDialog):
    """Browse portable-device folders and copy actual mobile output files."""

    def __init__(self, parent: QWidget | None, target: Path, backend_factory: Callable | None = None, log_base_dir: Path | None = None, conflict_policy: str = "overwrite", video_limit_bytes=None):
        super().__init__(parent)
        self.setWindowTitle("모바일로 복사")
        self.resize(820, 690)
        self.target = target
        self.video_limit_bytes = video_limit_bytes
        self.folder_plans = []
        self.conflict_policy = conflict_policy if conflict_policy in ("overwrite", "skip", "rename") else "overwrite"
        self.busy = False
        self.closing = False
        self.device_open = False
        self.folders = []
        self.destination_stack = [("DEVICE", "기기")]
        self.pending_stack = None
        self._build_ui()
        default_log_base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
        self.worker = PhoneTransferWorker(backend_factory or _default_backend, log_base_dir or default_log_base, self, conflict_policy=self.conflict_policy, video_limit_bytes=self.video_limit_bytes)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self._submit("initialize", target)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        hint = QLabel("휴대폰을 USB 파일 전송 모드로 연결하고 잠금을 해제해주세요. 선택한 모바일 출력 폴더를 복사합니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        labels = {"overwrite": "덮어쓰기", "skip": "건너뛰기", "rename": "새 이름으로 복사"}
        self.conflict_policy_label = QLabel(f"동일 이름 파일 처리: {labels[self.conflict_policy]} (휴대폰의 같은 폴더 기준)")
        layout.addWidget(self.conflict_policy_label)
        self.video_limit_label = QLabel(
            f"동영상 용량 제한: {self.video_limit_bytes / 1000000:g} MB 이상 제외 (1 MB = 1,000,000 bytes)"
            if self.video_limit_bytes is not None else "동영상 용량 제한: 해제")
        self.video_limit_label.setWordWrap(True)
        layout.addWidget(self.video_limit_label)
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        self.refresh_button = QPushButton("기기 다시 찾기")
        self.refresh_button.clicked.connect(lambda: self._submit("initialize", self.target))
        row = QHBoxLayout()
        row.addWidget(QLabel("휴대폰"))
        row.addWidget(self.device_combo, 1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.destination_label = QLabel("저장 위치: 선택 전")
        self.destination_label.setWordWrap(True)
        layout.addWidget(self.destination_label)
        self.up_button = QPushButton("상위 폴더")
        self.up_button.clicked.connect(self._go_up)
        self.new_folder_button = QPushButton("새 폴더")
        self.new_folder_button.clicked.connect(self._new_folder)
        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(self.up_button)
        folder_buttons.addWidget(self.new_folder_button)
        folder_buttons.addStretch()
        layout.addLayout(folder_buttons)
        self.remote_tree = QTreeWidget()
        self.remote_tree.setHeaderLabels(["휴대폰 폴더 — 더블클릭하여 열기"])
        self.remote_tree.itemDoubleClicked.connect(self._enter_folder)
        layout.addWidget(self.remote_tree, 1)
        layout.addWidget(QLabel("복사할 모바일 출력 폴더"))
        self.output_tree = QTreeWidget()
        self.output_tree.setHeaderLabels(["날짜 / 모델 폴더", "전송 파일 수", "전송 용량", "용량 제한 제외"])
        self.output_tree.itemChanged.connect(self._update_selection)
        layout.addWidget(self.output_tree, 1)
        self.selection_label = QLabel()
        layout.addWidget(self.selection_label)
        self.status_label = QLabel("기기와 출력 파일 확인 중")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        layout.addWidget(self.progress_bar)
        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["결과", "파일", "설명"])
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.results_table, 1)
        self.copy_button = QPushButton("선택 폴더 복사")
        self.copy_button.clicked.connect(self._start_transfer)
        self.cancel_button = QPushButton("전송 취소")
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for button in (self.copy_button, self.cancel_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _submit(self, operation: str, *args) -> None:
        if self.busy or self.closing or not self.worker.isRunning():
            return
        self.busy = True
        self.active_operation = operation
        self._update_buttons()
        self.progress_bar.setRange(0, 0)
        self.status_label.setText({"initialize": "출력 파일과 연결 기기 확인 중", "open": "휴대폰 저장소 확인 중", "browse": "폴더 확인 중", "create": "새 폴더 만드는 중", "transfer": "복사 중"}[operation])
        self.worker.submit(operation, *args)

    def _device_changed(self, index: int) -> None:
        if index < 0 or self.busy:
            return
        self.device_open = False
        self.destination_stack = [("DEVICE", self.device_combo.currentText())]
        self.remote_tree.clear()
        self._show_destination()
        self._submit("open", self.device_combo.currentData())

    def _enter_folder(self, item: QTreeWidgetItem, column: int = 0) -> None:
        if self.busy:
            return
        self.pending_stack = self.destination_stack + [(item.data(0, Qt.UserRole), item.text(0))]
        self._submit("browse", self.pending_stack[-1][0])

    def _go_up(self) -> None:
        if len(self.destination_stack) > 1 and not self.busy:
            self.pending_stack = self.destination_stack[:-1]
            self._submit("browse", self.pending_stack[-1][0])

    def _new_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "새 폴더", "폴더 이름")
        if not accepted or not name:
            return
        if any(character in name for character in '<>:"/\\|?*') or name in {".", ".."} or name[-1:] in {" ", "."} or any(ord(character) < 32 for character in name):
            self.status_label.setText("사용할 수 없는 폴더 이름입니다.")
            return
        self._submit("create", self.destination_stack[-1][0], name)

    def _selected_folders(self):
        return [folder for index, folder in enumerate(self.folders) if self.output_tree.topLevelItem(index).checkState(0) == Qt.Checked]

    def _update_selection(self, *args) -> None:
        selected = self._selected_folders()
        plans = [self.folder_plans[index] for index in range(len(self.folders)) if self.output_tree.topLevelItem(index).checkState(0) == Qt.Checked]
        count = sum(len(folder.files) for eligible, _ in plans for folder in eligible)
        size = sum(folder.size for eligible, _ in plans for folder in eligible)
        excluded = sum(len(skipped) for _, skipped in plans)
        self.selection_label.setText(f"선택 {len(selected)}개 폴더 / 전송 {count}개 파일 / {self._size(size)} / 용량 제한 제외 {excluded}개")
        self._update_buttons()

    def _update_buttons(self) -> None:
        idle = not self.busy and not self.closing and self.worker.isRunning()
        self.device_combo.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        self.remote_tree.setEnabled(idle and self.device_open)
        self.output_tree.setEnabled(idle)
        self.up_button.setEnabled(idle and len(self.destination_stack) > 1)
        self.new_folder_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1)
        self.copy_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1 and bool(self._selected_folders()))
        self.cancel_button.setEnabled(self.busy and getattr(self, "active_operation", "") == "transfer")

    def _start_transfer(self) -> None:
        if self.busy or not self.device_open or len(self.destination_stack) <= 1:
            return
        selected = self._selected_folders()
        if not selected:
            self.status_label.setText("복사할 폴더를 선택해주세요.")
            return
        self.results_table.setRowCount(0)
        self.worker.cancel_event.clear()
        self.active_operation = "transfer"
        self._submit("transfer", self.destination_stack[-1][0], selected)

    def _cancel(self) -> None:
        self.worker.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("취소 요청됨 — 현재 전송 작업을 정리하고 있습니다.")

    def _show_destination(self) -> None:
        self.destination_label.setText("저장 위치: " + " / ".join(name for _, name in self.destination_stack))

    def _completed(self, operation: str, result) -> None:
        self.busy = False
        self.active_operation = ""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        if operation == "initialize":
            self.folders, devices, self.folder_plans = result
            self.output_tree.blockSignals(True)
            self.output_tree.clear()
            for index, folder in enumerate(self.folders):
                try:
                    name = str(folder.path.relative_to(self.target))
                except ValueError:
                    name = str(folder.path)
                eligible, skipped = self.folder_plans[index]
                item = QTreeWidgetItem([name, str(sum(len(f.files) for f in eligible)), self._size(sum(f.size for f in eligible)), str(len(skipped))])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked)
                self.output_tree.addTopLevelItem(item)
            self.output_tree.blockSignals(False)
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            for device in devices:
                self.device_combo.addItem(device.name, device.id)
            self.device_combo.blockSignals(False)
            self.device_open = False
            self.remote_tree.clear()
            self.destination_stack = [("DEVICE", "기기")]
            self._show_destination()
            self._update_selection()
            if not self.folders:
                self.status_label.setText("Target에 복사할 모바일 출력 파일이 없습니다. 모바일 출력을 먼저 실행해주세요.")
            elif not devices:
                self.status_label.setText("연결된 기기가 없습니다. 잠금 해제와 USB 파일 전송 모드를 확인한 뒤 다시 찾아주세요.")
            else:
                self._device_changed(0)
        elif operation in {"open", "browse", "create"}:
            if operation == "open":
                self.device_open = True
            if self.pending_stack is not None:
                self.destination_stack = self.pending_stack
                self.pending_stack = None
            self._show_destination()
            self.remote_tree.clear()
            for entry in result:
                if entry.is_folder:
                    item = QTreeWidgetItem([entry.name])
                    item.setData(0, Qt.UserRole, entry.id)
                    self.remote_tree.addTopLevelItem(item)
            self.status_label.setText("폴더를 더블클릭하여 저장 위치를 선택해주세요." if len(self.destination_stack) == 1 else "현재 폴더가 저장 위치입니다. 선택 폴더를 복사할 수 있습니다.")
        elif operation == "transfer":
            log_error = result["log_error"]
            result = result["results"]
            labels = {"COPIED": "복사 완료", "SKIPPED": "건너뜀", "SIZE_EXCLUDED": "용량 제한 제외", "FAILED": "실패", "CANCELLED": "취소", "UNVERIFIED": "검증 미완료"}
            self.results_table.setRowCount(len(result))
            for row, entry in enumerate(result):
                for column, text in enumerate((labels.get(entry.status, entry.status), str(entry.source), entry.message)):
                    self.results_table.setItem(row, column, QTableWidgetItem(text))
            counts = {status: sum(entry.status == status for entry in result) for status in labels}
            self.status_label.setText("전송 결과: " + " / ".join(f"{labels[status]} {count}개" for status, count in counts.items() if count))
            if counts["FAILED"] or counts["UNVERIFIED"]:
                self._invalidate_device()
                self.status_label.setText(self.status_label.text() + " — 기기를 다시 찾고 저장 위치를 선택해주세요.")
            if log_error:
                self.status_label.setText(self.status_label.text() + f" — 로그 저장 실패: {log_error}")
        self._update_buttons()
        if self.closing:
            self.worker.shutdown()

    def _failed(self, operation: str, message: str) -> None:
        self.busy = False
        self.active_operation = ""
        self.pending_stack = None
        self._invalidate_device()
        self.progress_bar.setRange(0, 1)
        self.status_label.setText(f"작업 실패: {message} — 기기를 다시 찾고 저장 위치를 선택해주세요.")
        self._update_buttons()
        if self.closing:
            self.worker.shutdown()

    def _invalidate_device(self) -> None:
        self.device_open = False
        self.pending_stack = None
        self.destination_stack = [("DEVICE", "기기")]
        self.remote_tree.clear()
        self._show_destination()

    def _progress(self, progress: dict) -> None:
        total = max(1, int(progress.get("total_files", 0)))
        completed = int(progress.get("completed", 0))
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.status_label.setText(f"복사 중: {progress.get('file', '')} / {completed}/{total}개 / {self._size(int(progress.get('bytes', 0)))}/{self._size(int(progress.get('total_bytes', 0)))}")

    @staticmethod
    def _size(size: int) -> str:
        return f"{size / 1000000:.1f} MB" if size >= 1000000 else f"{size / 1000:.1f} KB"

    def reject(self) -> None:
        if self.worker.isRunning():
            self.closing = True
            self._cancel()
            self._update_buttons()
            self.worker.shutdown()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker.isRunning():
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)

    def _worker_finished(self) -> None:
        if self.closing:
            super().reject()
        else:
            self.busy = False
            self.status_label.setText(self.status_label.text() + " — 창을 닫고 다시 열어주세요.")
            self._update_buttons()
