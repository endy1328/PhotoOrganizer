from __future__ import annotations

from pathlib import Path
import sys
from queue import Queue
from threading import Event
import time
from typing import Callable

from ..logging_utils import AppLogger
from ..models import LogEvent
from ..phone_locations import PhoneLocationStore, resolve_location
from .phone_model_selection import PhoneModelSelection
from .output_path_delegate import OutputPathDelegate
from .phone_view_preferences import PhoneViewPreferences

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QSplitter, QSizePolicy,
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
    phase = Signal(str, bool)

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
                activity = getattr(backend, 'set_activity_callback', None)
                if callable(activity):
                    activity(self.phase.emit)
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
                        elif operation == "resolve":
                            result = resolve_location(backend, args[0])
                        elif operation == "create":
                            backend.create_folder(args[0], args[1])
                            result = backend.list_children(args[0])
                        elif operation in {"transfer", "retry"}:
                            from ..phone_retry import capture_retry_snapshot, retry_folders
                            folders = args[1]
                            if operation == 'retry':
                                folders = retry_folders(folders, args[2], args[3])
                                if not folders:
                                    raise ValueError('현재 선택에 재시도할 미전송 파일이 없습니다.')
                            try:
                                snapshot = capture_retry_snapshot(folders)
                            except ValueError:
                                snapshot = {}  # Core still validates originals; retry stays unavailable.
                            last_progress = {}
                            started = time.monotonic()
                            def report(update):
                                last_progress.update(update)
                                self.progress.emit(dict(update))
                            options = {"limit_video_bytes": self.video_limit_bytes} if self.video_limit_bytes is not None else {}
                            results = transfer_outputs(backend, args[0], folders, progress=report, cancelled=self.cancel_event.is_set, conflict_policy=self.conflict_policy, **options)
                            levels = {"FAILED": "ERROR", "UNVERIFIED": "WARNING", "CANCELLED": "WARNING"}
                            events = [LogEvent(levels.get(entry.status, "INFO"), f"USB TRANSFER {entry.status}: {entry.message}", str(entry.source), entry.remote_id) for entry in results]
                            if 'lookup_count' in last_progress:
                                events.append(LogEvent('INFO',
                                    f"USB TRANSFER 성능: 정책 목록 조회 {last_progress['lookup_count']}회 / "
                                    f"{last_progress.get('lookup_seconds', 0):.3f}초 / 전송 작업 {time.monotonic() - started:.3f}초 "
                                    '(WPD 내부 최종 검증 조회 제외)'))
                            result = {"results": results, "log_error": self._write_log(events), 'snapshot': snapshot}
                        else:
                            raise ValueError("지원하지 않는 작업입니다.")
                        self.completed.emit(operation, result)
                    except Exception as exc:
                        message = str(exc)
                        if operation in {"transfer", "retry"}:
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

    def __init__(self, parent: QWidget | None, target: Path, backend_factory: Callable | None = None, log_base_dir: Path | None = None, conflict_policy: str = "overwrite", video_limit_bytes=None, preferences_dir: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("모바일로 복사")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(820, 690)
        self._before_fullscreen_maximized = False
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
        self.preferences_dir = preferences_dir
        self.location_store = PhoneLocationStore(preferences_dir / 'phone_locations.json' if preferences_dir is not None else None)
        self.saved_locations = self.location_store.load()
        self.last_results = []
        self.retry_snapshot = {}
        self.retry_context = None
        self._transfer_started = None
        self._last_progress = None
        self._current_phase = ''
        self._phase_cancellable = True
        self._build_ui()
        self._refresh_locations()
        self.view_preferences = PhoneViewPreferences(self, preferences_dir / 'phone_view_preferences.json' if preferences_dir is not None else None)
        self.view_preferences.restore()
        default_log_base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
        self.worker = PhoneTransferWorker(backend_factory or _default_backend, log_base_dir or default_log_base, self, conflict_policy=self.conflict_policy, video_limit_bytes=self.video_limit_bytes)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.progress.connect(self._progress)
        self.worker.phase.connect(self._phase_changed)
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
        self.destination_hint = QLabel("휴대폰에서 복사의 기준 위치(예: Photos)를 선택해주세요. 선택한 위치 아래에 목록의 경로 구조를 그대로 복사합니다.")
        self.destination_hint.setWordWrap(True)
        layout.addWidget(self.destination_hint)
        self.location_combo = QComboBox()
        self.location_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.location_combo.setMinimumContentsLength(15)
        self.location_combo.setToolTip('저장한 휴대폰 경로를 선택한 뒤 불러오기를 누르세요.')
        self.save_location_button = QPushButton('경로 저장')
        self.load_location_button = QPushButton('불러오기')
        self.delete_location_button = QPushButton('삭제')
        self.save_location_button.clicked.connect(self._save_location)
        self.load_location_button.clicked.connect(self._load_location)
        self.delete_location_button.clicked.connect(self._delete_location)
        location_row = QHBoxLayout()
        location_row.addWidget(QLabel('저장한 경로'))
        location_row.addWidget(self.location_combo, 1)
        for button in (self.save_location_button, self.load_location_button, self.delete_location_button):
            location_row.addWidget(button)
        layout.addLayout(location_row)
        self.up_button = QPushButton("상위 폴더")
        self.up_button.clicked.connect(self._go_up)
        self.new_folder_button = QPushButton("새 폴더")
        self.new_folder_button.clicked.connect(self._new_folder)
        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(self.up_button)
        folder_buttons.addWidget(self.new_folder_button)
        folder_buttons.addStretch()
        layout.addLayout(folder_buttons)
        self.panel_splitter = QSplitter(Qt.Vertical)
        self.panel_splitter.setChildrenCollapsible(True)
        layout.addWidget(self.panel_splitter, 1)
        remote_panel = QWidget()
        remote_layout = QVBoxLayout(remote_panel)
        remote_layout.setContentsMargins(0, 0, 0, 0)
        self.remote_tree = QTreeWidget()
        self.remote_tree.setHeaderLabels(["휴대폰 폴더 — 더블클릭하여 열기"])
        self.remote_tree.itemDoubleClicked.connect(self._enter_folder)
        remote_layout.addWidget(self.remote_tree, 1)
        self.panel_splitter.addWidget(remote_panel)
        output_panel = QWidget()
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(QLabel("복사할 모바일 출력 폴더"))
        self.model_selection = PhoneModelSelection(self)
        self.model_selection.selection_changed.connect(self._model_selection_changed)
        output_layout.addWidget(self.model_selection)
        self.output_tree = QTreeWidget()
        self.output_tree.setHeaderLabels(["날짜 / 모델 폴더", "전송 파일 수", "전송 용량", "용량 제한 제외"])
        self.output_tree.setItemDelegateForColumn(0, OutputPathDelegate(self.output_tree))
        self.output_tree.itemChanged.connect(self._update_selection)
        output_layout.addWidget(self.output_tree, 1)
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        output_layout.addWidget(self.selection_label)
        self.panel_splitter.addWidget(output_panel)
        self.status_label = QLabel("기기와 출력 파일 확인 중")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.phase_label = QLabel()
        self.phase_label.setWordWrap(True)
        layout.addWidget(self.phase_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        layout.addWidget(self.progress_bar)
        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["결과", "파일", "설명"])
        self.results_table.setItemDelegateForColumn(1, OutputPathDelegate(self.results_table))
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(QLabel('전송 결과'))
        result_layout.addWidget(self.results_table, 1)
        self.panel_splitter.addWidget(result_panel)
        self.panel_splitter.setStretchFactor(0, 1)
        self.panel_splitter.setStretchFactor(1, 3)
        self.panel_splitter.setStretchFactor(2, 1)
        self.panel_splitter.setSizes([130, 300, 120])
        for view in (self.remote_tree, self.output_tree, self.results_table):
            view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
            view.setMinimumHeight(40)
        for header in (self.remote_tree.header(), self.output_tree.header(), self.results_table.horizontalHeader()):
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setSectionsMovable(True)
            header.setStretchLastSection(False)
        self.remote_tree.setColumnWidth(0, 440)
        for column, width in enumerate((480, 105, 100, 110)):
            self.output_tree.setColumnWidth(column, width)
        for column, width in enumerate((105, 450, 300)):
            self.results_table.setColumnWidth(column, width)
        self.copy_button = QPushButton("선택 폴더 복사")
        self.copy_button.clicked.connect(self._start_transfer)
        self.retry_button = QPushButton('미전송 파일 재시도')
        self.retry_button.setToolTip('완료·건너뜀·용량 제외·검증 미완료 파일은 재시도하지 않습니다.')
        self.retry_button.clicked.connect(self._start_retry)
        self.cancel_button = QPushButton("전송 취소")
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.reject)
        self.fullscreen_button = QPushButton("전체 화면")
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.setToolTip("전체 화면으로 확대합니다. Esc를 누르면 이전 창 크기로 돌아갑니다.")
        self.fullscreen_button.toggled.connect(self._toggle_fullscreen)
        buttons = QHBoxLayout()
        buttons.addWidget(self.fullscreen_button)
        buttons.addStretch()
        for button in (self.copy_button, self.retry_button, self.cancel_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _submit(self, operation: str, *args) -> None:
        if self.busy or self.closing or not self.worker.isRunning():
            return
        self.busy = True
        self.active_operation = operation
        self._update_buttons()
        self.progress_bar.setRange(0, 0)
        self.status_label.setText({"initialize": "출력 파일과 연결 기기 확인 중", "open": "휴대폰 저장소 확인 중", "browse": "폴더 확인 중", "resolve": "저장한 휴대폰 경로 확인 중", "create": "새 폴더 만드는 중", "transfer": "복사 중", 'retry':'미전송 파일 재시도 준비 중'}[operation])
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
        models = self.model_selection.selected_models()
        return [folder for index, folder in enumerate(self.folders)
                if self.output_tree.topLevelItem(index).checkState(0) == Qt.Checked
                and self.model_selection.model_for_folder(folder) in models]

    def _refresh_locations(self, selected_label=None) -> None:
        self.location_combo.clear()
        for location in self.saved_locations:
            self.location_combo.addItem(f"{location['label']} — {location['device']}", location)
            self.location_combo.setItemData(self.location_combo.count() - 1,
                ' / '.join([location['device'], *location['components']]), Qt.ToolTipRole)
            if location['label'] == selected_label:
                self.location_combo.setCurrentIndex(self.location_combo.count() - 1)

    def _save_location(self) -> None:
        if self.busy or not self.device_open or len(self.destination_stack) < 2:
            return
        label, accepted = QInputDialog.getText(self, '휴대폰 경로 저장', '저장할 경로 이름', text=self.destination_stack[-1][1])
        label = label.strip()
        if not accepted or not label:
            return
        location = {'label': label, 'device': self.device_combo.currentText(),
                    'components': [name for _, name in self.destination_stack[1:]]}
        updated = [item for item in self.saved_locations if (item['label'], item['device']) != (label, location['device'])]
        updated.append(location)
        try:
            self.location_store.save(updated)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f'경로 저장 실패: {exc}')
            return
        self.saved_locations = updated
        self._refresh_locations(label)
        self.status_label.setText(f'휴대폰 경로 저장 완료: {label}')
        self._update_buttons()

    def _load_location(self) -> None:
        location = self.location_combo.currentData()
        if self.busy or not self.device_open or not isinstance(location, dict):
            return
        if location['device'] != self.device_combo.currentText():
            self.status_label.setText(f"이 경로는 {location['device']}에 저장한 경로입니다. 해당 휴대폰을 선택해주세요.")
            return
        self._submit('resolve', list(location['components']))

    def _delete_location(self) -> None:
        location = self.location_combo.currentData()
        if self.busy or not isinstance(location, dict):
            return
        updated = [item for item in self.saved_locations if item != location]
        try:
            self.location_store.save(updated)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f'저장 경로 삭제 실패: {exc}')
            return
        self.saved_locations = updated
        self._refresh_locations()
        self.status_label.setText('저장한 경로를 삭제했습니다. 휴대폰 폴더는 그대로 유지됩니다.')
        self._update_buttons()

    def _model_selection_changed(self, *args) -> None:
        selected = self.model_selection.selected_models()
        self.output_tree.blockSignals(True)
        try:
            for index, folder in enumerate(self.folders):
                item = self.output_tree.topLevelItem(index)
                if item is not None:
                    excluded = self.model_selection.model_for_folder(folder) not in selected
                    item.setDisabled(excluded)
                    item.setToolTip(0, self._output_folder_tooltip(folder, excluded))
        finally:
            self.output_tree.blockSignals(False)
        self._update_selection()

    def _update_selection(self, *args) -> None:
        selected = self._selected_folders()
        selected_paths = {folder.path for folder in selected}
        plans = [plan for folder, plan in zip(self.folders, self.folder_plans) if folder.path in selected_paths]
        count = sum(len(folder.files) for eligible, _ in plans for folder in eligible)
        size = sum(folder.size for eligible, _ in plans for folder in eligible)
        excluded = sum(len(skipped) for _, skipped in plans)
        self.selection_label.setText(f"선택 {len(selected)}개 폴더 / 전송 {count}개 파일 / {self._size(size)} / 용량 제한 제외 {excluded}개")
        self._update_buttons()

    def _update_buttons(self) -> None:
        idle = not self.busy and not self.closing and self.worker.isRunning()
        self.device_combo.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        self.remote_tree.setEnabled(not self.closing and self.device_open)
        self.output_tree.setEnabled(not self.closing)
        self.output_tree.blockSignals(True)
        try:
            for index in range(self.output_tree.topLevelItemCount()):
                item = self.output_tree.topLevelItem(index)
                flags = item.flags()
                item.setFlags(flags | Qt.ItemIsUserCheckable if idle else flags & ~Qt.ItemIsUserCheckable)
        finally:
            self.output_tree.blockSignals(False)
        self.model_selection.setEnabled(idle)
        self.location_combo.setEnabled(idle)
        self.save_location_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1)
        self.load_location_button.setEnabled(idle and self.device_open and bool(self.saved_locations))
        self.delete_location_button.setEnabled(idle and bool(self.saved_locations))
        self.up_button.setEnabled(idle and len(self.destination_stack) > 1)
        self.new_folder_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1)
        self.copy_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1 and bool(self._selected_folders()))
        self.cancel_button.setEnabled(self.busy and getattr(self, "active_operation", "") in {"transfer", 'retry'}
            and not self.worker.cancel_event.is_set())
        selected_paths = {folder.path for folder in self._selected_folders()}
        pending = any(entry.status in {'FAILED', 'CANCELLED'} and entry.source in self.retry_snapshot
            and any(entry.source in folder.files for folder in self.folders if folder.path in selected_paths)
            for entry in self.last_results)
        self.retry_button.setEnabled(idle and self.device_open and len(self.destination_stack) > 1
            and pending and self.retry_context == self._destination_context())

    def _destination_context(self):
        return self.device_combo.currentData(), self.device_combo.currentText(), tuple(name for _, name in self.destination_stack[1:])

    def _reset_transfer_progress(self):
        self._transfer_started = time.monotonic()
        self._last_progress = None
        self._current_phase = ''
        self._phase_cancellable = True
        self.phase_label.setText('전송 준비 중')
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)

    def _start_retry(self) -> None:
        if self.busy or not self.device_open or self.retry_context != self._destination_context():
            return
        selected = self._selected_folders()
        if not selected or not self.last_results or not self.retry_snapshot:
            return
        self.worker.cancel_event.clear()
        self._reset_transfer_progress()
        self._submit('retry', self.destination_stack[-1][0], selected, list(self.last_results), dict(self.retry_snapshot))

    def _start_transfer(self) -> None:
        if self.busy or not self.device_open or len(self.destination_stack) <= 1:
            return
        selected = self._selected_folders()
        if not selected:
            self.status_label.setText("복사할 폴더를 선택해주세요.")
            return
        self.results_table.setRowCount(0)
        self.last_results = []
        self.retry_snapshot = {}
        self.retry_context = self._destination_context()
        self.worker.cancel_event.clear()
        self._reset_transfer_progress()
        self.active_operation = "transfer"
        self._submit("transfer", self.destination_stack[-1][0], selected)

    def _cancel(self) -> None:
        self.worker.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("취소 요청됨 — 현재 전송 작업을 정리하고 있습니다.")
        if not self._phase_cancellable:
            self.phase_label.setText('기존 파일 보호를 위해 교체 확인 후 취소됩니다.')

    def _show_destination(self) -> None:
        self.destination_label.setText("저장 위치: " + " / ".join(name for _, name in self.destination_stack))
        for index, folder in enumerate(self.folders):
            item = self.output_tree.topLevelItem(index)
            if item is not None:
                item.setToolTip(0, self._output_folder_tooltip(folder, item.isDisabled()))

    def _output_folder_tooltip(self, folder, excluded=False) -> str:
        from ..phone_transfer import output_relative_parts
        parts = output_relative_parts(folder)
        if self.device_open and len(self.destination_stack) > 1:
            destination = ' / '.join([name for _, name in self.destination_stack] + list(parts))
        else:
            destination = '(기준 위치 선택 전) / ' + ' / '.join(parts)
        return (f'PC 원본: {folder.path}\n복사될 휴대폰 경로: {destination}' +
                ('\n모델 선택 해제: 전송 대상에서 제외' if excluded else ''))

    def _completed(self, operation: str, result) -> None:
        self.busy = False
        self.active_operation = ""
        if operation not in {'transfer', 'retry'}:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
        if operation == "initialize":
            folder_choices = {
                folder.path: self.output_tree.topLevelItem(index).checkState(0)
                for index, folder in enumerate(self.folders)
            }
            self.folders, devices, self.folder_plans = result
            self.output_tree.blockSignals(True)
            self.output_tree.clear()
            for index, folder in enumerate(self.folders):
                from ..phone_transfer import output_relative_parts
                name = str(Path(*output_relative_parts(folder)))
                eligible, skipped = self.folder_plans[index]
                item = QTreeWidgetItem([name, str(sum(len(f.files) for f in eligible)), self._size(sum(f.size for f in eligible)), str(len(skipped))])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, folder_choices.get(folder.path, Qt.Checked))
                self.output_tree.addTopLevelItem(item)
            self.output_tree.blockSignals(False)
            self.model_selection.set_folders(self.folders)
            self._model_selection_changed()
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
        elif operation in {"open", "browse", "create", "resolve"}:
            if operation == 'resolve':
                stack, result = result
                self.destination_stack = [("DEVICE", self.device_combo.currentText()), *stack]
                self.pending_stack = None
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
        elif operation in {"transfer", 'retry'}:
            log_error = result["log_error"]
            snapshot = result.get('snapshot', {})
            result = result["results"]
            if operation == 'retry':
                replacements = {entry.source: entry for entry in result}
                result = [replacements.pop(entry.source, entry) for entry in self.last_results] + list(replacements.values())
                self.retry_snapshot.update(snapshot)
            else:
                self.retry_snapshot = snapshot
            self.last_results = list(result)
            labels = {"COPIED": "복사 완료", "SKIPPED": "건너뜀", "SIZE_EXCLUDED": "용량 제한 제외", "FAILED": "실패", "CANCELLED": "취소", "UNVERIFIED": "검증 미완료"}
            self.results_table.setRowCount(len(result))
            for row, entry in enumerate(result):
                for column, text in enumerate((labels.get(entry.status, entry.status), str(entry.source), entry.message)):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(text)
                    self.results_table.setItem(row, column, cell)
            counts = {status: sum(entry.status == status for entry in result) for status in labels}
            self.status_label.setText("전송 결과: " + " / ".join(f"{labels[status]} {count}개" for status, count in counts.items() if count))
            if not any(counts[status] for status in ('FAILED', 'CANCELLED', 'UNVERIFIED')):
                self.progress_bar.setRange(0, 1000)
                self.progress_bar.setValue(1000)
            elif self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 1000)
                self.progress_bar.setValue(0)
            self.phase_label.setText('취소됨' if counts['CANCELLED'] else
                ('전송 결과 확인 필요' if counts['FAILED'] or counts['UNVERIFIED'] else '처리 완료'))
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
        if operation not in {'transfer', 'retry'} or self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)
        self.phase_label.setText('작업 실패')
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
        if self.worker.cancel_event.is_set():
            return  # Preserve last progress, rather than counting cancelled queue entries as done.
        self._last_progress = dict(progress)
        total = max(1, int(progress.get("total_files", 0)))
        completed = int(progress.get("completed", 0))
        transferred = max(0, int(progress.get('bytes', 0)))
        total_bytes = max(0, int(progress.get('total_bytes', 0)))
        if total_bytes:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(min(1000, int(transferred / total_bytes * 1000)))
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(total, completed))
        current = str(progress.get('file', ''))
        self.status_label.setToolTip(current)
        summary = f"복사 중: {Path(current).name} / {completed}/{total}개 / {self._size(transferred)}/{self._size(total_bytes)}"
        if self._transfer_started is not None:
            elapsed = max(0.001, time.monotonic() - self._transfer_started)
            if elapsed >= 2 and transferred:
                speed = transferred / elapsed
                remaining = max(0, total_bytes - transferred) / speed
                summary += f' / {self._size(int(speed))}/초 / 남은 시간 약 {int(remaining // 60)}분 {int(remaining % 60)}초'
        self.status_label.setText(summary)

    def _phase_changed(self, phase: str, cancellable: bool) -> None:
        if not self.busy or getattr(self, 'active_operation', '') not in {'transfer', 'retry'}:
            return
        self._current_phase, self._phase_cancellable = phase, cancellable
        waiting = phase.startswith('waiting:')
        step = phase.removeprefix('waiting:')
        names = {'upload':'전송 준비', 'overwrite':'기존 파일 교체 준비', 'prepare':'전송 준비',
                 'write':'파일 전송', 'commit':'저장 확인', 'swap_prepare':'교체 준비', 'swap':'기존 파일 교체',
                 'list':'폴더 확인'}
        text = names.get(step, '휴대폰 작업')
        if waiting:
            text += ' — 휴대폰 응답 대기 중'
        if not cancellable:
            text += ' — 기존 파일 보호를 위해 교체 확인 후 취소됩니다.'
        if self.worker.cancel_event.is_set():
            text = '취소 요청됨 — ' + text
        self.phase_label.setText(text)

    @staticmethod
    def _size(size: int) -> str:
        return f"{size / 1000000:.1f} MB" if size >= 1000000 else f"{size / 1000:.1f} KB"

    def reject(self) -> None:
        self.view_preferences.save()
        if self.worker.isRunning():
            self.closing = True
            self._cancel()
            self._update_buttons()
            self.worker.shutdown()
            return
        super().reject()

    def _toggle_fullscreen(self, enabled: bool) -> None:
        if enabled:
            self._before_fullscreen_maximized = self.isMaximized()
            self.showFullScreen()
            self.fullscreen_button.setText("전체 화면 해제")
        else:
            if self._before_fullscreen_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.fullscreen_button.setText("전체 화면")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.fullscreen_button.setChecked(False)
            event.accept()
            return
        super().keyPressEvent(event)

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
