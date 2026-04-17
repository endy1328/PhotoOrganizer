from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigManager
from ..engine import OrganizerEngine
from .. import __version__
from ..models import AppSettings, DeleteReviewItem, OrganizeRequest, PreviewBundle, PreviewItem


class ClippedItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        clipped_option = option
        clipped_option.textElideMode = Qt.ElideNone
        painter.save()
        painter.setClipRect(option.rect)
        super().paint(painter, clipped_option, index)
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, engine: OrganizerEngine, config_manager: ConfigManager) -> None:
        super().__init__()
        self.engine = engine
        self.config_manager = config_manager
        self.settings = self.config_manager.load()
        self.current_delete_candidates: list[DeleteReviewItem] = []
        self.last_preview_bundle = None
        self.last_preview_signature: tuple[str, str, str, str] | None = None
        self._current_preview_source_path: Path | None = None

        self.setWindowTitle(f"PhotoOrganizer {__version__}")
        self.resize(1400, 860)
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form_layout = QFormLayout()
        self.source_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.device_name_edit = QLineEdit()
        self.device_name_edit.setPlaceholderText("비워두면 메타데이터/파일명 기준, 입력하면 이 값을 우선 사용")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["copy", "move"])
        self.mode_combo.currentTextChanged.connect(lambda _value: self._save_current_inputs())
        self.device_name_edit.editingFinished.connect(self._save_current_inputs)
        source_button = QPushButton("Source 선택")
        target_button = QPushButton("Target 선택")
        source_button.clicked.connect(lambda: self._select_directory(self.source_edit))
        target_button.clicked.connect(lambda: self._select_directory(self.target_edit))

        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit)
        source_row.addWidget(source_button)
        target_row = QHBoxLayout()
        target_row.addWidget(self.target_edit)
        target_row.addWidget(target_button)

        source_wrapper = QWidget()
        source_wrapper.setLayout(source_row)
        target_wrapper = QWidget()
        target_wrapper.setLayout(target_row)

        form_layout.addRow("Source 경로", source_wrapper)
        form_layout.addRow("Target 경로", target_wrapper)
        form_layout.addRow("디바이스명(선택)", self.device_name_edit)
        form_layout.addRow("처리 모드", self.mode_combo)
        layout.addLayout(form_layout)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("미리보기")
        self.execute_button = QPushButton("실행")
        self.delete_button = QPushButton("삭제 리뷰 실행")
        self.delete_button.setEnabled(False)
        self.preview_button.clicked.connect(self._handle_preview)
        self.execute_button.clicked.connect(self._handle_execute)
        self.delete_button.clicked.connect(self._handle_delete_review)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.execute_button)
        button_row.addWidget(self.delete_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("초기/미선택")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("대기 중")
        layout.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)

        self.preview_table = self._build_table(["원본 경로", "대상 경로", "처리 방식", "새 파일명", "일시 근거", "모델명 근거", "오류 예상"])
        self.results_table = self._build_table(["상태", "동작", "처리 방식", "원본", "대상", "메시지"])
        self.error_table = self._build_table(["원본 경로", "오류 내용"])
        self.delete_table = self._build_delete_table()

        self.tabs.addTab(self.preview_table, "미리보기")
        self.tabs.addTab(self.results_table, "실행 결과")
        self.tabs.addTab(self.error_table, "오류")
        self.tabs.addTab(self.delete_table, "삭제 리뷰")

        self.selection_splitter = QSplitter(Qt.Horizontal)
        self.selection_splitter.setChildrenCollapsible(False)
        self.selection_image_panel = self._build_selection_image_panel()
        self.selection_detail = QPlainTextEdit()
        self.selection_detail.setReadOnly(True)
        self.selection_detail.setPlaceholderText("선택한 항목의 전체 경로와 세부 내용이 여기에 표시됩니다.")
        self.selection_detail.setMinimumHeight(120)
        self.selection_splitter.addWidget(self.selection_image_panel)
        self.selection_splitter.addWidget(self.selection_detail)
        self.selection_splitter.setStretchFactor(0, 1)
        self.selection_splitter.setStretchFactor(1, 2)
        splitter.addWidget(self.selection_splitter)

        self.preview_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("preview"))
        self.results_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("results"))
        self.error_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("error"))
        self.delete_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("delete"))
        self.tabs.currentChanged.connect(self._handle_tab_changed)

    def _build_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideNone)
        table.setItemDelegate(ClippedItemDelegate(table))
        header = table.horizontalHeader()
        header.setSectionsMovable(False)
        for index in range(len(headers)):
            header.setSectionResizeMode(index, QHeaderView.Interactive)
        self._apply_default_column_widths(table, headers)
        return table

    def _build_selection_image_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("선택 파일 이미지")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self.preview_image_scroll = QScrollArea()
        self.preview_image_scroll.setWidgetResizable(True)
        self.preview_image_scroll.setMinimumWidth(320)
        self.preview_image_scroll.setMinimumHeight(220)

        self.preview_image_view = QLabel()
        self.preview_image_view.setAlignment(Qt.AlignCenter)
        self.preview_image_view.setWordWrap(True)
        self.preview_image_view.setMinimumSize(280, 200)
        self.preview_image_view.setStyleSheet(
            "QLabel { border: 1px solid #9aa0a6; background: #1f1f1f; color: #d0d0d0; padding: 12px; }"
        )
        self.preview_image_scroll.setWidget(self.preview_image_view)
        layout.addWidget(self.preview_image_scroll, 1)

        self.preview_image_info = QLabel("사진 파일은 축소 로드해서 표시하고, 비사진/영상은 미리보기 불가로 표시합니다.")
        self.preview_image_info.setWordWrap(True)
        self.preview_image_info.setStyleSheet("color: #666;")
        layout.addWidget(self.preview_image_info)
        self._set_preview_image_placeholder("미리보기에서 사진을 선택하면 왼쪽에 이미지가 표시됩니다.")
        return panel

    def _build_delete_table(self) -> QTableWidget:
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["선택", "삭제 대상", "사유"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideNone)
        table.setItemDelegate(ClippedItemDelegate(table))
        header = table.horizontalHeader()
        header.setSectionsMovable(False)
        for index in range(3):
            header.setSectionResizeMode(index, QHeaderView.Interactive)
        table.setColumnWidth(0, 70)
        table.setColumnWidth(1, 620)
        table.setColumnWidth(2, 320)
        return table

    def _apply_default_column_widths(self, table: QTableWidget, headers: list[str]) -> None:
        width_map = {
            "원본 경로": 520,
            "대상 경로": 620,
            "처리 방식": 120,
            "새 파일명": 260,
            "일시 근거": 150,
            "모델명 근거": 180,
            "오류 예상": 260,
            "상태": 100,
            "동작": 100,
            "처리 방식": 120,
            "원본": 520,
            "대상": 620,
            "메시지": 260,
            "오류 내용": 420,
        }
        for index, header in enumerate(headers):
            table.setColumnWidth(index, width_map.get(header, 220))

    def _load_settings(self) -> None:
        self.source_edit.setText(self.settings.source_path)
        self.target_edit.setText(self.settings.target_path)
        self.device_name_edit.setText(self.settings.device_name_override)
        index = self.mode_combo.findText(self.settings.operation_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)

    def _save_settings(self) -> None:
        self.config_manager.save(self._current_settings())

    def _save_current_inputs(self) -> None:
        self.config_manager.save(self._current_settings())

    def _current_settings(self) -> AppSettings:
        return AppSettings(
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            device_name_override=self.device_name_edit.text().strip(),
            operation_mode=self.mode_combo.currentText(),
        )

    def _select_directory(self, line_edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "폴더 선택", line_edit.text() or str(Path.cwd()))
        if directory:
            line_edit.setText(directory)
            self._save_current_inputs()

    def _build_request(self, preview_only: bool) -> OrganizeRequest | None:
        source = Path(self.source_edit.text().strip())
        target = Path(self.target_edit.text().strip())
        if not source.exists() or not source.is_dir():
            self._set_status("Source 없음 또는 경로 오류")
            QMessageBox.warning(self, "경로 오류", "유효한 Source 폴더를 선택해주세요.")
            return None
        if not target.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
            except Exception:
                self._set_status("Target 없음 또는 경로 오류")
                QMessageBox.warning(self, "경로 오류", "Target 폴더를 생성할 수 없습니다.")
                return None
        try:
            source_resolved = source.resolve()
            target_resolved = target.resolve()
            if source_resolved == target_resolved or source_resolved in target_resolved.parents or target_resolved in source_resolved.parents:
                self._set_status("경로 오류")
                QMessageBox.warning(self, "경로 오류", "Source와 Target은 서로 포함 관계가 아니어야 합니다.")
                return None
        except Exception:
            pass
        self._save_settings()
        return OrganizeRequest(
            source_path=source,
            target_path=target,
            device_name_override=self.device_name_edit.text().strip(),
            operation_mode=self.mode_combo.currentText(),
            preview_only=preview_only,
        )

    def _request_signature(self, request: OrganizeRequest) -> tuple[str, str, str, str]:
        return (
            str(request.source_path.resolve()),
            str(request.target_path.resolve()),
            request.device_name_override.strip(),
            request.operation_mode,
        )

    def _handle_preview(self) -> None:
        request = self._build_request(preview_only=True)
        if request is None:
            return
        self._set_busy(True)
        self._update_progress("미리보기 준비 중", 0, 0)
        bundle = self.engine.preview(request, progress_callback=self._update_progress)
        self.last_preview_bundle = bundle
        self.last_preview_signature = self._request_signature(request)
        self.current_delete_candidates = []
        self._fill_preview_table(bundle.preview_items)
        self._fill_error_table(bundle.error_items)
        self.results_table.setRowCount(0)
        self.delete_table.setRowCount(0)
        self.delete_button.setEnabled(False)
        self._set_status("부분 성공" if bundle.error_items and bundle.preview_items else "오류 발생" if bundle.error_items else "미리보기 준비 완료")
        preview_count = len(bundle.preview_items)
        error_count = len(bundle.error_items)
        self._set_idle_progress(f"미리보기 완료: 준비 {preview_count}건, 오류 {error_count}건")
        self._set_busy(False)
        self._update_selection_detail("preview")

    def _handle_execute(self) -> None:
        request = self._build_request(preview_only=False)
        if request is None:
            return
        self._set_busy(True)
        self._update_progress("실행 준비 중", 0, 0)
        current_signature = self._request_signature(request)
        if self.last_preview_bundle is not None and self.last_preview_signature == current_signature:
            bundle = self.engine.execute(request, progress_callback=self._update_progress, preview_bundle=self.last_preview_bundle)
        else:
            bundle = self.engine.execute(request, progress_callback=self._update_progress)
            self.last_preview_bundle = PreviewBundle(
                preview_items=bundle.preview_items,
                error_items=bundle.error_items,
                log_events=bundle.log_events,
            )
            self.last_preview_signature = current_signature
        self.current_delete_candidates = bundle.delete_review_items
        self._fill_preview_table(bundle.preview_items)
        self._fill_results_table(bundle.execution_results)
        self._fill_error_table(bundle.error_items)
        self._fill_delete_table(bundle.delete_review_items)
        self.delete_button.setEnabled(bool(bundle.delete_review_items))
        if bundle.error_items and bundle.execution_results:
            self._set_status("부분 성공")
        elif bundle.error_items:
            self._set_status("오류 발생")
        elif bundle.delete_review_items:
            self._set_status("삭제 리뷰 대기")
        else:
            self._set_status("실행 완료")
        success_count = len([item for item in bundle.execution_results if item.status == "SUCCESS"])
        error_count = len(bundle.error_items)
        self._set_idle_progress(f"실행 완료: 성공 {success_count}건, 오류 {error_count}건")
        self._set_busy(False)
        self._update_selection_detail("results")

    def _handle_delete_review(self) -> None:
        selected_items: list[DeleteReviewItem] = []
        for row, item in enumerate(self.current_delete_candidates):
            checkbox = self.delete_table.cellWidget(row, 0)
            selected = isinstance(checkbox, QCheckBox) and checkbox.isChecked()
            selected_items.append(DeleteReviewItem(item_id=item.item_id, delete_path=item.delete_path, reason=item.reason, selected=selected))
        chosen = [item for item in selected_items if item.selected]
        if not chosen:
            QMessageBox.information(self, "삭제 리뷰", "선택된 항목이 없습니다.")
            return
        answer = QMessageBox.question(self, "삭제 확인", f"{len(chosen)}개 항목을 휴지통으로 이동할까요?")
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._update_progress("휴지통 이동 중", 0, len(chosen))
        results = self.engine.delete_selected(chosen)
        self._fill_results_table(results, append=True)
        self._set_status("휴지통 이동 완료")
        self._set_idle_progress(f"휴지통 이동 완료: {len(results)}건 처리")
        self._set_busy(False)
        self._update_selection_detail("delete")

    def _fill_preview_table(self, items: list[PreviewItem]) -> None:
        self.preview_table.setRowCount(len(items))
        for row, item in enumerate(items):
            warning_text = "; ".join(item.warnings) if item.warnings else ""
            action_text = self._write_mode_label(item.write_mode)
            values = [item.source_path, item.target_path, action_text, item.new_filename, item.datetime_source, item.model_source, warning_text]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.preview_table.setItem(row, column, cell)

    def _fill_results_table(self, items, append: bool = False) -> None:
        start_row = self.results_table.rowCount() if append else 0
        if not append:
            self.results_table.setRowCount(0)
        self.results_table.setRowCount(start_row + len(items))
        for offset, item in enumerate(items):
            row = start_row + offset
            values = [item.status, item.action, self._write_mode_label(item.write_mode), item.source_path, item.target_path, item.message]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.results_table.setItem(row, column, cell)

    def _fill_error_table(self, items) -> None:
        self.error_table.setRowCount(len(items))
        for row, item in enumerate(items):
            source_cell = QTableWidgetItem(item.source_path)
            source_cell.setToolTip(item.source_path)
            message_cell = QTableWidgetItem(item.message)
            message_cell.setToolTip(item.message)
            self.error_table.setItem(row, 0, source_cell)
            self.error_table.setItem(row, 1, message_cell)

    def _fill_delete_table(self, items: list[DeleteReviewItem]) -> None:
        self.delete_table.setRowCount(len(items))
        for row, item in enumerate(items):
            checkbox = QCheckBox()
            checkbox.setChecked(item.selected)
            checkbox.setStyleSheet("margin-left: 20px;")
            self.delete_table.setCellWidget(row, 0, checkbox)
            path_cell = QTableWidgetItem(item.delete_path)
            path_cell.setToolTip(item.delete_path)
            reason_cell = QTableWidgetItem(item.reason)
            reason_cell.setToolTip(item.reason)
            self.delete_table.setItem(row, 1, path_cell)
            self.delete_table.setItem(row, 2, reason_cell)

    def _handle_tab_changed(self, _index: int) -> None:
        current = self.tabs.currentWidget()
        if current is self.preview_table:
            self._update_selection_detail("preview")
        elif current is self.results_table:
            self._update_selection_detail("results")
        elif current is self.error_table:
            self._update_selection_detail("error")
        elif current is self.delete_table:
            self._update_selection_detail("delete")

    def _update_selection_detail(self, table_name: str) -> None:
        self._update_preview_image(table_name)
        if table_name == "preview":
            selected_items = self.preview_table.selectedItems()
            if not selected_items:
                self.selection_detail.setPlainText("미리보기 항목을 선택하면 전체 원본 경로와 대상 경로를 여기서 확인할 수 있습니다.")
                return
            row = selected_items[0].row()
            lines = [
                f"원본 경로: {self._cell_text(self.preview_table, row, 0)}",
                f"대상 경로: {self._cell_text(self.preview_table, row, 1)}",
                f"처리 방식: {self._cell_text(self.preview_table, row, 2)}",
                f"새 파일명: {self._cell_text(self.preview_table, row, 3)}",
                f"일시 근거: {self._cell_text(self.preview_table, row, 4)}",
                f"모델명 근거: {self._cell_text(self.preview_table, row, 5)}",
                f"오류 예상: {self._cell_text(self.preview_table, row, 6)}",
            ]
            self.selection_detail.setPlainText("\n".join(lines))
            return
        if table_name == "results":
            selected_items = self.results_table.selectedItems()
            if not selected_items:
                self.selection_detail.setPlainText("실행 결과 항목을 선택하면 전체 원본 경로와 대상 경로를 여기서 확인할 수 있습니다.")
                return
            row = selected_items[0].row()
            lines = [
                f"상태: {self._cell_text(self.results_table, row, 0)}",
                f"동작: {self._cell_text(self.results_table, row, 1)}",
                f"처리 방식: {self._cell_text(self.results_table, row, 2)}",
                f"원본 경로: {self._cell_text(self.results_table, row, 3)}",
                f"대상 경로: {self._cell_text(self.results_table, row, 4)}",
                f"메시지: {self._cell_text(self.results_table, row, 5)}",
            ]
            self.selection_detail.setPlainText("\n".join(lines))
            return
        if table_name == "error":
            selected_items = self.error_table.selectedItems()
            if not selected_items:
                self.selection_detail.setPlainText("오류 항목을 선택하면 전체 원본 경로와 오류 내용을 여기서 확인할 수 있습니다.")
                return
            row = selected_items[0].row()
            lines = [
                f"원본 경로: {self._cell_text(self.error_table, row, 0)}",
                f"오류 내용: {self._cell_text(self.error_table, row, 1)}",
            ]
            self.selection_detail.setPlainText("\n".join(lines))
            return
        selected_items = self.delete_table.selectedItems()
        if not selected_items:
            self.selection_detail.setPlainText("삭제 리뷰 항목을 선택하면 전체 삭제 대상 경로와 사유를 여기서 확인할 수 있습니다.")
            return
        row = selected_items[0].row()
        checkbox = self.delete_table.cellWidget(row, 0)
        selected = isinstance(checkbox, QCheckBox) and checkbox.isChecked()
        lines = [
            f"선택 여부: {'선택됨' if selected else '선택 안 됨'}",
            f"삭제 대상 경로: {self._cell_text(self.delete_table, row, 1)}",
            f"사유: {self._cell_text(self.delete_table, row, 2)}",
        ]
        self.selection_detail.setPlainText("\n".join(lines))

    def _update_preview_image(self, table_name: str) -> None:
        source_path = self._selected_image_source_path(table_name)
        if not source_path:
            self._current_preview_source_path = None
            if table_name == "delete":
                self._set_preview_image_placeholder("삭제 리뷰에서는 원본 이미지 미리보기를 표시하지 않습니다.")
            else:
                self._set_preview_image_placeholder("사진 파일을 선택하면 축소 미리보기가 표시됩니다. 비사진/영상은 미리보기 불가입니다.")
            return
        path = Path(source_path)
        if not path.exists() or not path.is_file():
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("선택한 파일을 찾을 수 없습니다.")
            self.preview_image_info.setText(str(path))
            return
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if not reader.canRead():
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("비사진/영상 또는 지원되지 않는 이미지 형식이라 미리보기할 수 없습니다.")
            self.preview_image_info.setText(str(path))
            return
        target_size = self.preview_image_scroll.viewport().size()
        if target_size.width() < 240 or target_size.height() < 180:
            target_size = QSize(640, 420)
        source_size = reader.size()
        if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
            scaled_size = source_size.scaled(target_size, Qt.KeepAspectRatio)
            if scaled_size.isValid():
                reader.setScaledSize(scaled_size)
        image = reader.read()
        if image.isNull():
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("이미지를 불러오지 못했습니다.")
            self.preview_image_info.setText(str(path))
            return
        self._current_preview_source_path = path
        pixmap = QPixmap.fromImage(image)
        self.preview_image_view.setPixmap(pixmap)
        self.preview_image_view.setText("")
        self.preview_image_info.setText(f"{path.name} | {image.width()} x {image.height()} | 축소 로드")

    def _selected_image_source_path(self, table_name: str) -> str:
        if table_name == "preview":
            table = self.preview_table
            column = 0
        elif table_name == "results":
            table = self.results_table
            column = 3
        elif table_name == "error":
            table = self.error_table
            column = 0
        else:
            return ""
        selected_items = table.selectedItems()
        if not selected_items:
            return ""
        row = selected_items[0].row()
        return self._cell_text(table, row, column)

    def _set_preview_image_placeholder(self, text: str) -> None:
        self.preview_image_view.setPixmap(QPixmap())
        self.preview_image_view.setText(text)
        self.preview_image_info.setText(text)

    def _cell_text(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text() if item is not None else "-"

    def _write_mode_label(self, write_mode: str) -> str:
        labels = {
            "NEW": "신규 생성",
            "OVERWRITE": "덮어쓰기",
            "SEQ": "SEQ 증가",
            "CONFLICT": "충돌",
            "DELETE": "삭제",
        }
        return labels.get(write_mode, write_mode)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_busy(self, busy: bool) -> None:
        self.preview_button.setEnabled(not busy)
        self.execute_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and bool(self.current_delete_candidates))
        QApplication.processEvents()

    def _update_progress(self, message: str, current: int, total: int) -> None:
        self._set_status(message if total == 0 else f"{message} ({current}/{total})")
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(message)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_bar.setFormat(f"{message} ({current}/{total})")
        QApplication.processEvents()

    def _set_idle_progress(self, message: str) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.setFormat(message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_current_inputs()
        super().closeEvent(event)
