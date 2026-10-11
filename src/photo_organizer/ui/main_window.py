from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QCloseEvent, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
    QSizePolicy,
    QSpinBox,
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
from .. import __version__, __release_date__
from ..models import AppSettings, DeleteReviewItem, ExecutionBundle, OrganizeRequest, PreviewBundle, PreviewItem, VIDEO_EXTENSIONS
from ..video_thumbnail import extract_video_thumbnail_bytes
from .model_selection import ModelSelectionPanel
from .job_controller import JobControllerMixin
from .operation_controller import OperationControllerMixin
from ..operation_control import OperationStopped
from ..model_mapping import model_mapping_signature
from ..video_output import VIDEO_QUALITY_PRESETS, normalize_video_quality, video_quality_display_label


class ClippedItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        clipped_option = option
        clipped_option.textElideMode = Qt.ElideNone
        painter.save()
        painter.setClipRect(option.rect)
        super().paint(painter, clipped_option, index)
        painter.restore()


class SettingsDialog(QDialog):
    VIDEO_WIDTH_OPTIONS = [
        ("1280 px", 1280),
        ("1920 px", 1920),
        ("원본 유지", 0),
    ]
    VIDEO_QUALITY_OPTIONS = [(video_quality_display_label(key), key) for key in VIDEO_QUALITY_PRESETS]

    def __init__(self, parent: QWidget | None, settings: AppSettings) -> None:
        super().__init__(parent)
        self.setWindowTitle("환경설정")
        self.setModal(True)
        self.resize(700, 620)

        dialog_layout = QVBoxLayout(self)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.settings_scroll.setWidget(content)
        dialog_layout.addWidget(self.settings_scroll, 1)
        mapping_group = QGroupBox("모델명 매핑")
        mapping_layout = QVBoxLayout(mapping_group)
        self.mapping_table = QTableWidget(0, 2)
        self.mapping_table.setHorizontalHeaderLabels(["원본 모델명", "사용할 별칭"])
        self.mapping_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.mapping_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mapping_table.setMinimumHeight(145)
        self.mapping_table.setMaximumHeight(230)
        for original, alias in sorted(settings.model_name_mappings.items()):
            row = self.mapping_table.rowCount()
            self.mapping_table.insertRow(row)
            self.mapping_table.setItem(row, 0, QTableWidgetItem(original))
            self.mapping_table.setItem(row, 1, QTableWidgetItem(alias))
        mapping_layout.addWidget(self.mapping_table)
        mapping_buttons = QHBoxLayout()
        add_mapping = QPushButton("추가")
        add_mapping.clicked.connect(self._add_model_mapping_row)
        delete_mapping = QPushButton("삭제")
        delete_mapping.clicked.connect(self._delete_model_mapping_rows)
        mapping_buttons.addWidget(add_mapping)
        mapping_buttons.addWidget(delete_mapping)
        mapping_buttons.addStretch()
        mapping_layout.addLayout(mapping_buttons)
        mapping_form = QFormLayout()
        self.model_mapping_scope_combo = QComboBox()
        self.model_mapping_scope_combo.addItem("새 파일명 + 분류 폴더", "filename_and_folders")
        self.model_mapping_scope_combo.addItem("새 파일명만", "filename_only")
        self._set_combo_value(self.model_mapping_scope_combo, settings.model_mapping_scope)
        mapping_form.addRow("적용 범위", self.model_mapping_scope_combo)
        mapping_layout.addLayout(mapping_form)
        mapping_note = QLabel("원본 모델명을 별칭으로 바꿔 출력합니다. 별칭의 공백은 밑줄로 바뀝니다. 설정 변경 후 미리보기를 다시 만들어주세요. 같은 Source·Target에서 매핑을 변경해 다시 미리보기하면 직접 수정한 파일명은 유지됩니다.")
        mapping_note.setWordWrap(True)
        mapping_layout.addWidget(mapping_note)
        layout.addWidget(mapping_group)
        inference_group = QGroupBox("영상 모델명 보완")
        inference_form = QFormLayout(inference_group)
        self.video_model_window_spin = QSpinBox()
        self.video_model_window_spin.setRange(0, 1440)
        self.video_model_window_spin.setSuffix(" 분")
        self.video_model_window_spin.setValue(settings.video_model_window_minutes)
        inference_form.addRow("전후 시간 범위(±)", self.video_model_window_spin)
        inference_hint = QLabel("같은 폴더의 확인된 사진·영상을 지정 범위에서 먼저 비교합니다(0분은 동일 시각). 미확인 영상은 같은 폴더의 앞뒤 사진으로 시간 제한 없이 보완합니다. 앞뒤 모델이 다르면 UNKNOWN을 유지합니다.")
        inference_hint.setWordWrap(True)
        inference_form.addRow(inference_hint)
        layout.addWidget(inference_group)
        phone_group = QGroupBox("휴대폰 복사")
        phone_form = QFormLayout(phone_group)
        self.phone_conflict_combo = QComboBox()
        for label, value in (("덮어쓰기 (기본)", "overwrite"), ("건너뛰기", "skip"), ("새 이름으로 복사", "rename")):
            self.phone_conflict_combo.addItem(label, value)
        self._set_combo_value(self.phone_conflict_combo, settings.phone_conflict_policy)
        phone_form.addRow("동일 이름 파일 처리", self.phone_conflict_combo)
        phone_hint = QLabel("휴대폰의 같은 폴더에 같은 이름의 파일이 있을 때 적용합니다. 덮어쓰기는 기존 파일을 교체합니다. 파일 내용으로 중복을 비교하지 않습니다.")
        phone_hint.setWordWrap(True)
        phone_form.addRow(phone_hint)
        self.phone_video_limit_checkbox = QCheckBox("용량이 큰 동영상 복사 제외")
        self.phone_video_limit_checkbox.setChecked(settings.phone_video_limit_enabled)
        self.phone_video_limit_spin = QSpinBox()
        self.phone_video_limit_spin.setRange(1, 1000000)
        self.phone_video_limit_spin.setSuffix(" MB 이상 제외")
        self.phone_video_limit_spin.setValue(settings.phone_video_limit_mb)
        self.phone_video_limit_spin.setToolTip("1 MB = 1,000,000 바이트. 실제 전송할 output_ 영상의 크기가 기준 이상이면 제외합니다.")
        self.phone_video_limit_spin.setEnabled(self.phone_video_limit_checkbox.isChecked())
        self.phone_video_limit_checkbox.toggled.connect(self.phone_video_limit_spin.setEnabled)
        phone_form.addRow(self.phone_video_limit_checkbox)
        phone_form.addRow("제외 기준 용량", self.phone_video_limit_spin)
        phone_size_hint = QLabel("실제 전송할 output_ 동영상 크기를 기준으로 합니다(1 MB = 1,000,000 바이트). 기준과 같은 크기도 제외하며 사진과 PC 출력 파일은 유지합니다.")
        phone_size_hint.setWordWrap(True)
        phone_form.addRow(phone_size_hint)
        layout.addWidget(phone_group)
        description = QLabel(
            "모바일 출력은 사진과 동영상 모두 대상으로 하고, 결과는 각 모델 디렉토리 아래 "
            "`output_YYYYMMDD_MODEL` 폴더에 생성됩니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.enabled_checkbox = QCheckBox("모바일 출력 생성 사용")
        self.enabled_checkbox.setChecked(settings.mobile_output_enabled)
        layout.addWidget(self.enabled_checkbox)

        output_size_group = QGroupBox("출력 용량 제한")
        output_size_form = QFormLayout(output_size_group)
        self.mobile_output_limit_checkbox = QCheckBox("기준 용량 이상의 출력 파일 생성 제외")
        self.mobile_output_limit_checkbox.setChecked(settings.mobile_output_limit_enabled)
        self.mobile_output_limit_spin = QSpinBox()
        self.mobile_output_limit_spin.setRange(1, 1000000)
        self.mobile_output_limit_spin.setSuffix(" MB 이상 제외")
        self.mobile_output_limit_spin.setValue(settings.mobile_output_limit_mb)
        self.mobile_output_limit_spin.setToolTip("1 MB = 1,000,000 바이트. 사진·영상의 실제 변환 후 크기로 판단하며 미리보기에서는 확정하지 않습니다.")
        self.mobile_output_limit_checkbox.toggled.connect(lambda _: self._sync_enabled_state(self.enabled_checkbox.isChecked()))
        output_size_form.addRow(self.mobile_output_limit_checkbox)
        output_size_form.addRow("제외 기준 용량", self.mobile_output_limit_spin)
        output_size_note = QLabel("사진·영상 모두 적용합니다. 변환 후 크기로 판단하며 미리보기에서는 확정하지 않습니다.")
        output_size_note.setWordWrap(True)
        output_size_form.addRow(output_size_note)
        layout.addWidget(output_size_group)

        photo_group = QGroupBox("사진 출력")
        photo_form_layout = QFormLayout(photo_group)
        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(500, 8000)
        self.max_width_spin.setValue(settings.mobile_output_max_width)
        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(1, 100)
        self.jpeg_quality_spin.setValue(settings.mobile_output_jpeg_quality)
        self.keep_smaller_checkbox = QCheckBox("원본 가로가 더 작으면 원본 크기 유지")
        self.keep_smaller_checkbox.setChecked(settings.mobile_output_keep_smaller_original)
        self.keep_smaller_checkbox.setEnabled(False)
        photo_form_layout.addRow("최대 가로 크기(px)", self.max_width_spin)
        photo_form_layout.addRow("JPEG 품질", self.jpeg_quality_spin)
        photo_form_layout.addRow("", self.keep_smaller_checkbox)
        layout.addWidget(photo_group)

        video_group = QGroupBox("동영상 출력")
        video_form_layout = QFormLayout(video_group)
        self.video_max_width_combo = QComboBox()
        for label, value in self.VIDEO_WIDTH_OPTIONS:
            self.video_max_width_combo.addItem(label, value)
        self._set_combo_value(self.video_max_width_combo, settings.mobile_output_video_max_width)
        self.video_quality_combo = QComboBox()
        self.video_quality_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for label, value in self.VIDEO_QUALITY_OPTIONS:
            self.video_quality_combo.addItem(label, value)
        self._set_combo_value(self.video_quality_combo, normalize_video_quality(settings.mobile_output_video_quality))
        self.video_quality_description = QLabel()
        self.video_quality_description.setWordWrap(True)
        self.video_quality_combo.currentIndexChanged.connect(self._update_video_quality_description)
        self._update_video_quality_description()
        self.video_quality_hint = QLabel("CRF는 낮을수록 화질을 우선하며 용량은 커지는 경향이 있습니다. 해상도는 ‘최대 가로 크기’ 설정을 따릅니다.")
        self.video_quality_hint.setWordWrap(True)
        self.video_only_if_smaller_checkbox = QCheckBox("원본보다 작아질 때만 저장")
        self.video_only_if_smaller_checkbox.setChecked(settings.mobile_output_video_only_if_smaller)
        video_form_layout.addRow("출력 포맷", QLabel("MP4 (H.264 / AAC)"))
        video_form_layout.addRow("최대 가로 크기", self.video_max_width_combo)
        video_form_layout.addRow("품질 프로필", self.video_quality_combo)
        video_form_layout.addRow("", self.video_quality_description)
        video_form_layout.addRow("", self.video_quality_hint)
        video_form_layout.addRow("", self.video_only_if_smaller_checkbox)
        layout.addWidget(video_group)

        self.performance_group = QGroupBox("변환 성능")
        performance_layout = QFormLayout(self.performance_group)
        self.video_encoder_combo = QComboBox()
        for label, value in (("자동 (NVIDIA NVENC 가능 시 사용, 실패 시 CPU)", "auto"), ("CPU", "cpu"), ("GPU NVIDIA NVENC (사용할 수 없으면 실패)", "gpu")):
            self.video_encoder_combo.addItem(label, value)
        self._set_combo_value(self.video_encoder_combo, settings.video_encoder)
        self.conversion_speed_combo = QComboBox()
        for label, value in (("화질·압축 우선", "quality"), ("균형", "balanced"), ("빠름", "fast")):
            self.conversion_speed_combo.addItem(label, value)
        self._set_combo_value(self.conversion_speed_combo, settings.conversion_speed)
        self.conversion_speed_combo.setToolTip("영상 인코딩 속도와 압축 효율을 조절합니다. 사진의 ‘빠름’은 JPEG/PNG 저장 압축 속도를 우선하며 품질 수치는 유지합니다. GPU와 CPU의 결과는 다를 수 있습니다.")
        self.photo_workers_combo = QComboBox()
        for count in (1, 2, 4):
            self.photo_workers_combo.addItem(f"{count}개", count)
        self._set_combo_value(self.photo_workers_combo, settings.photo_workers)
        self.photo_workers_combo.setToolTip("사진 모바일 출력의 동시 처리 개수입니다. 일시정지·중단 시 진행 중인 파일을 모두 완료한 뒤 멈춥니다.")
        performance_layout.addRow("영상 인코더", self.video_encoder_combo)
        performance_layout.addRow("변환 속도", self.conversion_speed_combo)
        performance_layout.addRow("사진 동시 변환", self.photo_workers_combo)
        performance_note = QLabel("품질 프로필의 CRF는 CPU 기준이며 GPU에는 CQ를 적용합니다. 같은 숫자도 화질·용량이 다를 수 있습니다.")
        performance_note.setWordWrap(True)
        performance_layout.addRow("", performance_note)
        layout.addWidget(self.performance_group)

        note = QLabel(
            "사진은 JPG/JPEG/PNG/HEIC를 지원합니다.\n"
            "동영상 모바일 출력은 MP4(H.264/AAC)로 생성합니다.\n"
            "모바일 출력 생성 실패 시 전체 실행을 실패로 처리합니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        job_group = QGroupBox("작업 저장 및 복원")
        job_layout = QVBoxLayout(job_group)
        self.restore_last_job_checkbox = QCheckBox("시작 시 마지막 작업 복원")
        self.restore_last_job_checkbox.setChecked(settings.restore_last_job)
        self.autosave_job_checkbox = QCheckBox("작업 변경 시 최근 작업 자동 저장")
        self.autosave_job_checkbox.setChecked(settings.autosave_job_changes)
        self.save_defaults_checkbox = QCheckBox("기본 설정에도 저장")
        self.save_defaults_checkbox.setChecked(not getattr(parent, "_job_loaded", False))
        job_layout.addWidget(self.restore_last_job_checkbox)
        job_layout.addWidget(self.autosave_job_checkbox)
        job_note = QLabel("실행 시작·결과 복구 기록은 자동 저장 옵션과 관계없이 저장합니다.")
        job_note.setWordWrap(True)
        job_layout.addWidget(job_note)
        job_layout.addWidget(self.save_defaults_checkbox)
        layout.addWidget(job_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        restore_button = buttons.addButton("기본값 복원", QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore_button.clicked.connect(self._restore_defaults)
        dialog_layout.addWidget(buttons)

        self.enabled_checkbox.toggled.connect(self._sync_enabled_state)
        self._sync_enabled_state(self.enabled_checkbox.isChecked())
        self._processing_locked = bool(parent and getattr(parent, "_job_started", lambda: False)())
        if self._processing_locked:
            for widget in (mapping_group, inference_group, self.enabled_checkbox,
                           output_size_group, photo_group, video_group, self.performance_group):
                widget.setEnabled(False)
            locked_note = QLabel("실행을 시작한 작업의 처리 설정은 고정됩니다. 변경하려면 새 작업을 시작해주세요. 휴대폰 복사와 작업 복원 설정은 변경할 수 있습니다.")
            locked_note.setWordWrap(True)
            layout.addWidget(locked_note)

    def _update_video_quality_description(self, *_args) -> None:
        key = normalize_video_quality(self.video_quality_combo.currentData())
        self.video_quality_description.setText(VIDEO_QUALITY_PRESETS[key]["description"])

    def _restore_defaults(self) -> None:
        if getattr(self, "_processing_locked", False):
            self._set_combo_value(self.phone_conflict_combo, "overwrite")
            self.phone_video_limit_checkbox.setChecked(False)
            self.phone_video_limit_spin.setValue(500)
            self.restore_last_job_checkbox.setChecked(True)
            self.autosave_job_checkbox.setChecked(True)
            return
        self.mapping_table.setRowCount(0)
        self._set_combo_value(self.model_mapping_scope_combo, "filename_and_folders")
        self._set_combo_value(self.phone_conflict_combo, "overwrite")
        self.phone_video_limit_checkbox.setChecked(False)
        self.phone_video_limit_spin.setValue(500)
        self.enabled_checkbox.setChecked(True)
        self.mobile_output_limit_checkbox.setChecked(False)
        self.mobile_output_limit_spin.setValue(500)
        self.max_width_spin.setValue(3000)
        self.jpeg_quality_spin.setValue(75)
        self.keep_smaller_checkbox.setChecked(True)
        self._set_combo_value(self.video_max_width_combo, 1280)
        self._set_combo_value(self.video_quality_combo, "balanced")
        self._set_combo_value(self.video_encoder_combo, "auto")
        self._set_combo_value(self.conversion_speed_combo, "balanced")
        self._set_combo_value(self.photo_workers_combo, 2)
        self.video_only_if_smaller_checkbox.setChecked(True)
        self.restore_last_job_checkbox.setChecked(True)
        self.autosave_job_checkbox.setChecked(True)

    def _sync_enabled_state(self, enabled: bool) -> None:
        self.mobile_output_limit_checkbox.setEnabled(enabled)
        self.mobile_output_limit_spin.setEnabled(enabled and self.mobile_output_limit_checkbox.isChecked())
        self.max_width_spin.setEnabled(enabled)
        self.jpeg_quality_spin.setEnabled(enabled)
        self.keep_smaller_checkbox.setEnabled(False)
        self.video_max_width_combo.setEnabled(enabled)
        self.video_quality_combo.setEnabled(enabled)
        self.video_only_if_smaller_checkbox.setEnabled(enabled)

    def _set_combo_value(self, combo: QComboBox, expected_value: object) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == expected_value:
                combo.setCurrentIndex(index)
                return

    def _add_model_mapping_row(self) -> None:
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        self.mapping_table.setItem(row, 0, QTableWidgetItem(""))
        self.mapping_table.setItem(row, 1, QTableWidgetItem(""))
        self.mapping_table.setCurrentCell(row, 0)
        self.mapping_table.editItem(self.mapping_table.item(row, 0))

    def _delete_model_mapping_rows(self) -> None:
        rows = {index.row() for index in self.mapping_table.selectionModel().selectedRows()}
        for row in sorted(rows, reverse=True):
            self.mapping_table.removeRow(row)

    def _validated_model_mappings(self) -> dict[str, str]:
        from ..model_mapping import validate_model_mapping_rows
        rows = []
        for row in range(self.mapping_table.rowCount()):
            source, alias = self.mapping_table.item(row, 0), self.mapping_table.item(row, 1)
            rows.append((source.text() if source else "", alias.text() if alias else ""))
        return validate_model_mapping_rows(rows)

    def accept(self) -> None:
        self.mapping_table.setFocus()  # 표에서 편집 중인 값을 확정한 뒤 검증한다.
        try:
            self._validated_model_mappings()
        except ValueError as exc:
            QMessageBox.warning(self, "모델명 매핑", str(exc))
            return
        super().accept()

    def to_settings(self, current: AppSettings) -> AppSettings:
        return AppSettings(
            video_encoder=str(self.video_encoder_combo.currentData()),
            conversion_speed=str(self.conversion_speed_combo.currentData()),
            photo_workers=int(self.photo_workers_combo.currentData()),
            source_path=current.source_path,
            target_path=current.target_path,
            device_name_override=current.device_name_override,
            operation_mode=current.operation_mode,
            video_model_window_minutes=self.video_model_window_spin.value(),
            phone_conflict_policy=str(self.phone_conflict_combo.currentData()),
            phone_video_limit_enabled=self.phone_video_limit_checkbox.isChecked(),
            phone_video_limit_mb=self.phone_video_limit_spin.value(),
            model_name_mappings=self._validated_model_mappings(),
            model_mapping_scope=str(self.model_mapping_scope_combo.currentData()),
            mobile_output_enabled=self.enabled_checkbox.isChecked(),
            mobile_output_max_width=self.max_width_spin.value(),
            mobile_output_jpeg_quality=self.jpeg_quality_spin.value(),
            mobile_output_keep_smaller_original=self.keep_smaller_checkbox.isChecked(),
            mobile_output_video_max_width=int(self.video_max_width_combo.currentData()),
            mobile_output_video_quality=str(self.video_quality_combo.currentData()),
            mobile_output_video_only_if_smaller=self.video_only_if_smaller_checkbox.isChecked(),
            mobile_output_limit_enabled=self.mobile_output_limit_checkbox.isChecked(),
            mobile_output_limit_mb=self.mobile_output_limit_spin.value(),
            restore_last_job=self.restore_last_job_checkbox.isChecked(),
            autosave_job_changes=self.autosave_job_checkbox.isChecked(),
        )


class MainWindow(OperationControllerMixin, JobControllerMixin, QMainWindow):
    def __init__(self, engine: OrganizerEngine, config_manager: ConfigManager) -> None:
        super().__init__()
        self.engine = engine
        self.config_manager = config_manager
        self.settings = self.config_manager.load()
        self.current_delete_candidates: list[DeleteReviewItem] = []
        self.last_preview_bundle = None
        self.last_preview_signature: tuple[str, ...] | None = None
        self.last_execution_bundle: ExecutionBundle | None = None
        self._current_preview_source_path: Path | None = None
        self._video_thumbnail_cache: dict[tuple[str, int, int, int], QPixmap] = {}
        self._detail_metadata_cache: dict[str, tuple[tuple[int, int], list[tuple[str, str]]]] = {}
        self._preview_detail_column = 0
        self._preview_metadata_bundle = None
        self._preview_metadata_fingerprints: dict[str, tuple[int, int] | None] = {}
        self._results_detail_column = 3
        self._busy = False
        self._init_job_controller()
        self._init_operation_controller()

        self.setWindowTitle(f"PhotoOrganizer {__version__} ({__release_date__})")
        self.resize(1400, 860)
        self._build_ui()
        self._load_settings()
        from ..job_store import JobState
        self._job_state = JobState(settings=self._current_settings())
        self.source_edit.editingFinished.connect(self._save_current_inputs)
        self.target_edit.editingFinished.connect(self._save_current_inputs)
        for line_edit in (self.source_edit, self.target_edit, self.device_name_edit):
            line_edit.textChanged.connect(lambda _text: self._job_mark_changed())
        self._restore_recent_job()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form_layout = QFormLayout()
        self.source_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.device_name_edit = QLineEdit()
        self.device_name_edit.setPlaceholderText("비워두면 메타데이터/파일명 기준, 입력하면 이 값을 우선 사용")
        self.device_name_edit.setClearButtonEnabled(True)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["copy", "move"])
        self.mode_combo.currentTextChanged.connect(lambda _value: self._save_current_inputs())
        self.device_name_edit.textChanged.connect(self._handle_device_name_text_changed)
        self.device_name_edit.editingFinished.connect(self._save_current_inputs)
        source_button = QPushButton("Source 선택")
        target_button = QPushButton("Target 선택")
        self.source_select_button = source_button
        self.target_select_button = target_button
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
        self.device_name_hint = QLabel()
        self.device_name_hint.setWordWrap(True)
        form_layout.addRow("", self.device_name_hint)
        form_layout.addRow("처리 모드", self.mode_combo)
        layout.addLayout(form_layout)

        self._build_job_controls(layout)

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
        self.resume_button = QPushButton("이어서 실행")
        self.resume_button.setEnabled(False)
        self.resume_button.clicked.connect(lambda: self._handle_resume("continue"))
        self.retry_button = QPushButton("실패 항목 재시도")
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(lambda: self._handle_resume("retry"))
        button_row.addWidget(self.resume_button)
        button_row.addWidget(self.retry_button)
        self._build_operation_controls(button_row)
        button_row.addWidget(self.delete_button)
        self.phone_transfer_button = QPushButton("모바일로 복사")
        self.phone_transfer_button.clicked.connect(self._open_phone_transfer)
        button_row.addWidget(self.phone_transfer_button)
        button_row.addStretch(1)
        self.mobile_output_summary = QLabel()
        self.mobile_output_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mobile_output_summary.setWordWrap(True)
        self.mobile_output_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.settings_button = QPushButton("환경설정")
        self.settings_button.clicked.connect(self._open_settings_dialog)
        button_row.addWidget(self.mobile_output_summary, 1)
        button_row.addWidget(self.settings_button)
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

        self.preview_table = self._build_table(["원본 경로", "대상 경로", "처리 방식", "새 파일명", "일시 근거", "모델명 근거", "안내/오류", "영상 모델 조회"])
        self.preview_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.preview_table.itemChanged.connect(self._handle_filename_edit)
        self.preview_table.setToolTip("새 파일명을 더블클릭하거나 F2로 수정할 수 있습니다. 분류 폴더와 확장자는 유지됩니다.")
        self.results_table = self._build_table(["상태", "동작", "처리 방식", "원본", "대상", "모바일 출력", "모바일 출력 경로", "메시지"])
        self.error_table = self._build_table(["원본 경로", "오류 내용"])
        self.delete_table = self._build_delete_table()

        self.preview_tab = QWidget()
        preview_layout = QVBoxLayout(self.preview_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.model_selection_panel = ModelSelectionPanel()
        self.model_selection_panel.selection_changed.connect(self._handle_model_selection)
        preview_layout.addWidget(self.model_selection_panel)
        preview_layout.addWidget(self.preview_table, 1)
        self.tabs.addTab(self.preview_tab, "미리보기")
        self.tabs.addTab(self.results_table, "실행 결과")
        self.tabs.addTab(self.error_table, "오류")
        self.tabs.addTab(self.delete_table, "삭제 리뷰")

        self.selection_splitter = QSplitter(Qt.Horizontal)
        self.selection_splitter.setChildrenCollapsible(False)
        self.selection_image_panel = self._build_selection_image_panel()
        self.selection_detail_panel = self._build_selection_detail_panel()
        self.selection_splitter.addWidget(self.selection_image_panel)
        self.selection_splitter.addWidget(self.selection_detail_panel)
        self.selection_splitter.setStretchFactor(0, 1)
        self.selection_splitter.setStretchFactor(1, 2)
        splitter.addWidget(self.selection_splitter)

        self.preview_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("preview"))
        self.preview_table.itemClicked.connect(self._handle_preview_item_clicked)
        self.results_table.itemSelectionChanged.connect(lambda: self._update_selection_detail("results"))
        self.results_table.itemClicked.connect(self._handle_results_item_clicked)
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

        self.preview_image_info = QLabel("사진 파일은 축소 로드하고, 영상 파일은 썸네일을 추출해 표시합니다.")
        self.preview_image_info.setWordWrap(True)
        self.preview_image_info.setStyleSheet("color: #666;")
        layout.addWidget(self.preview_image_info)
        self._set_preview_image_placeholder("미리보기에서 사진을 선택하면 왼쪽에 이미지가 표시됩니다.")
        return panel

    def _build_selection_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        info_title = QLabel("선택 항목 정보")
        info_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(info_title)

        self.selection_detail = QPlainTextEdit()
        self.selection_detail.setReadOnly(True)
        self.selection_detail.setPlaceholderText("선택한 항목의 전체 경로와 세부 내용이 여기에 표시됩니다.")
        self.selection_detail.setMinimumHeight(140)
        layout.addWidget(self.selection_detail)

        metadata_title = QLabel("메타정보")
        metadata_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(metadata_title)

        self.selection_metadata_table = QTableWidget(0, 2)
        self.selection_metadata_table.setHorizontalHeaderLabels(["항목", "값"])
        self.selection_metadata_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.selection_metadata_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.selection_metadata_table.setFocusPolicy(Qt.NoFocus)
        self.selection_metadata_table.setWordWrap(False)
        self.selection_metadata_table.setTextElideMode(Qt.ElideNone)
        self.selection_metadata_table.setItemDelegate(ClippedItemDelegate(self.selection_metadata_table))
        self.selection_metadata_table.verticalHeader().setVisible(False)
        self.selection_metadata_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        metadata_header = self.selection_metadata_table.horizontalHeader()
        metadata_header.setSectionsMovable(False)
        metadata_header.setSectionResizeMode(0, QHeaderView.Interactive)
        metadata_header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.selection_metadata_table.setColumnWidth(0, 180)
        self.selection_metadata_table.setMinimumHeight(180)
        layout.addWidget(self.selection_metadata_table, 1)

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
            "안내/오류": 300,
            "영상 모델 조회": 230,
            "상태": 100,
            "동작": 100,
            "처리 방식": 120,
            "원본": 520,
            "대상": 620,
            "모바일 출력": 120,
            "모바일 출력 경로": 620,
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
        self._update_device_name_hint(self.settings.device_name_override)
        self._update_mobile_output_summary()

    def _save_settings(self) -> None:
        self._save_current_inputs()

    def _save_current_inputs(self) -> None:
        if self._job_restoring:
            return
        if not self._job_loaded:
            self.config_manager.save(self._current_settings())
            from copy import deepcopy
            self._global_settings = deepcopy(self._current_settings())
        self._job_mark_changed()

    def _current_settings(self) -> AppSettings:
        return AppSettings(
            video_encoder=self.settings.video_encoder,
            conversion_speed=self.settings.conversion_speed,
            photo_workers=self.settings.photo_workers,
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            device_name_override=self.device_name_edit.text().strip(),
            operation_mode=self.mode_combo.currentText(),
            video_model_window_minutes=self.settings.video_model_window_minutes,
            phone_conflict_policy=self.settings.phone_conflict_policy,
            phone_video_limit_enabled=self.settings.phone_video_limit_enabled,
            phone_video_limit_mb=self.settings.phone_video_limit_mb,
            model_name_mappings=dict(self.settings.model_name_mappings),
            model_mapping_scope=self.settings.model_mapping_scope,
            mobile_output_enabled=self.settings.mobile_output_enabled,
            mobile_output_max_width=self.settings.mobile_output_max_width,
            mobile_output_jpeg_quality=self.settings.mobile_output_jpeg_quality,
            mobile_output_keep_smaller_original=self.settings.mobile_output_keep_smaller_original,
            mobile_output_video_max_width=self.settings.mobile_output_video_max_width,
            mobile_output_video_quality=self.settings.mobile_output_video_quality,
            mobile_output_video_only_if_smaller=self.settings.mobile_output_video_only_if_smaller,
            mobile_output_limit_enabled=self.settings.mobile_output_limit_enabled,
            mobile_output_limit_mb=self.settings.mobile_output_limit_mb,
            restore_last_job=self._global_settings.restore_last_job,
            autosave_job_changes=self._global_settings.autosave_job_changes,
        )

    def _open_settings_dialog(self) -> None:
        if self._busy:
            return
        dialog = SettingsDialog(self, self._current_settings())
        if dialog.exec() != QDialog.Accepted:
            return
        self.settings = dialog.to_settings(self._current_settings())
        self._update_mobile_output_summary()
        from copy import deepcopy
        self._global_settings.restore_last_job = self.settings.restore_last_job
        self._global_settings.autosave_job_changes = self.settings.autosave_job_changes
        if dialog.save_defaults_checkbox.isChecked():
            self._global_settings = deepcopy(self._current_settings())
            self.config_manager.save(self._global_settings)
        else:
            self.config_manager.save(self._global_settings)
            self._job_loaded = True
        self._job_mark_changed()

    def _open_phone_transfer(self) -> None:
        if self._busy:
            return
        target_text = self.target_edit.text().strip()
        if not target_text or not Path(target_text).is_dir():
            QMessageBox.information(self, "Target 확인", "모바일 출력 파일이 있는 Target 폴더를 먼저 선택해주세요.")
            return
        from .phone_transfer_dialog import PhoneTransferDialog
        dialog = PhoneTransferDialog(
            self, Path(target_text), log_base_dir=self.engine.base_dir,
            conflict_policy=self.settings.phone_conflict_policy,
            video_limit_bytes=(self.settings.phone_video_limit_mb * 1000000 if self.settings.phone_video_limit_enabled else None),
        )
        dialog.exec()

    def _update_mobile_output_summary(self) -> None:
        if not self.settings.mobile_output_enabled:
            self.mobile_output_summary.setText("모바일 출력: 사용 안 함")
            return
        video_width_text = "원본 유지" if self.settings.mobile_output_video_max_width <= 0 else f"{self.settings.mobile_output_video_max_width}px"
        size_limit_text = (
            f" / 출력 {self.settings.mobile_output_limit_mb:,} MB 이상 제외 (변환 후 판단)"
            if self.settings.mobile_output_limit_enabled else ""
        )
        self.mobile_output_summary.setText(
            "모바일 출력: 사용 / "
            f"사진 {self.settings.mobile_output_max_width}px 품질 {self.settings.mobile_output_jpeg_quality} / "
            f"동영상 MP4 {video_width_text} {video_quality_display_label(self.settings.mobile_output_video_quality)}"
            f"{size_limit_text}"
            f" / 인코더 { {'auto': '자동', 'cpu': 'CPU', 'gpu': 'GPU'}[self.settings.video_encoder]}"
            f" · 속도 { {'quality': '화질·압축 우선', 'balanced': '균형', 'fast': '빠름'}[self.settings.conversion_speed]}"
            f" · 사진 {self.settings.photo_workers}개 동시"
        )

    def _select_directory(self, line_edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "폴더 선택", line_edit.text() or str(Path.cwd()))
        if directory:
            line_edit.setText(directory)
            self._save_current_inputs()

    def _handle_device_name_text_changed(self, text: str) -> None:
        self._update_device_name_hint(text)

    def _update_device_name_hint(self, text: str) -> None:
        override = text.strip()
        if override:
            self.device_name_hint.setText(f"현재 모델명 override 활성화: 이번 작업 전체에 `{override}` 를 우선 적용합니다.")
            self.device_name_hint.setStyleSheet("color: #b42318; font-weight: 600;")
            return
        self.device_name_hint.setText("현재는 메타데이터와 파일명 fallback 기준으로 모델명을 자동 추출합니다.")
        self.device_name_hint.setStyleSheet("color: #666;")

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
        return self._request_from_inputs(preview_only)

    def _request_from_inputs(self, preview_only: bool) -> OrganizeRequest:
        return OrganizeRequest(
            video_encoder=self.settings.video_encoder,
            conversion_speed=self.settings.conversion_speed,
            photo_workers=self.settings.photo_workers,
            source_path=Path(self.source_edit.text().strip()),
            target_path=Path(self.target_edit.text().strip()),
            device_name_override=self.device_name_edit.text().strip(),
            operation_mode=self.mode_combo.currentText(),
            video_model_window_minutes=self.settings.video_model_window_minutes,
            preview_only=preview_only,
            model_name_mappings=dict(self.settings.model_name_mappings),
            model_mapping_scope=self.settings.model_mapping_scope,
            mobile_output_enabled=self.settings.mobile_output_enabled,
            mobile_output_max_width=self.settings.mobile_output_max_width,
            mobile_output_jpeg_quality=self.settings.mobile_output_jpeg_quality,
            mobile_output_keep_smaller_original=self.settings.mobile_output_keep_smaller_original,
            mobile_output_video_max_width=self.settings.mobile_output_video_max_width,
            mobile_output_video_quality=self.settings.mobile_output_video_quality,
            mobile_output_video_only_if_smaller=self.settings.mobile_output_video_only_if_smaller,
            mobile_output_limit_enabled=self.settings.mobile_output_limit_enabled,
            mobile_output_limit_mb=self.settings.mobile_output_limit_mb,
        )

    def _request_signature(self, request: OrganizeRequest) -> tuple[str, ...]:
        return (
            str(request.source_path.resolve()),
            str(request.target_path.resolve()),
            request.device_name_override.strip(),
            request.operation_mode,
            str(request.video_model_window_minutes),
            repr(model_mapping_signature(request.model_name_mappings, request.model_mapping_scope)),
            request.model_mapping_scope,
            str(request.mobile_output_enabled),
            str(request.mobile_output_max_width),
            str(request.mobile_output_jpeg_quality),
            str(request.mobile_output_keep_smaller_original),
            str(request.mobile_output_video_max_width),
            request.mobile_output_video_quality,
            str(request.mobile_output_video_only_if_smaller),
            str(request.mobile_output_limit_enabled),
            str(request.mobile_output_limit_mb),
            request.video_encoder,
            request.conversion_speed,
            str(request.photo_workers),
        )

    def _handle_preview(self) -> None:
        if self._busy:
            return
        if self._job_started():
            QMessageBox.information(self, "새 작업 필요", "실행을 시작한 작업은 새 작업에서 미리보기를 만들어주세요.")
            return
        request = self._build_request(preview_only=True)
        if request is None:
            return
        signature = self._request_signature(request)
        manual_names = {}
        if (self.last_preview_bundle is not None and self.last_preview_signature is not None
                and self.last_preview_signature[:2] == signature[:2] and self._preview_mapping_changed(request)):
            manual_names = {item.source_path: item.new_filename for item in self.last_preview_bundle.preview_items if item.filename_edited}
        self._set_busy(True)
        self._update_progress("미리보기 준비 중", 0, 0)
        try:
            bundle = self._run_engine_operation(self.engine.preview, request)
        except OperationStopped:
            self._set_busy(False)
            self._set_status("미리보기 중단 — 기존 미리보기를 유지했습니다.")
            self._set_idle_progress("미리보기 중단")
            return
        except Exception as exc:
            self._set_busy(False)
            self._show_operation_error("미리보기 실패", exc)
            return
        restored_count = 0
        if manual_names:
            try:
                restored_count = self.engine.restore_manual_filenames(bundle, manual_names)
            except (ValueError, OSError) as exc:
                self._set_busy(False)
                self._set_status(f"수동 파일명 복원 실패: {exc}")
                QMessageBox.warning(self, "수동 파일명 복원 실패", f"기존 미리보기와 파일명은 유지했습니다. 파일명을 확인한 뒤 다시 미리보기해주세요.\n{exc}")
                return
        self.last_preview_bundle = bundle
        self._preview_detail_column = 0
        self.last_preview_signature = signature
        self.last_execution_bundle = None
        self.current_delete_candidates = []
        self.model_selection_panel.set_items(bundle.preview_items)
        self._fill_preview_table(bundle.preview_items)
        self._fill_error_table(bundle.error_items)
        self.results_table.setRowCount(0)
        self.delete_table.setRowCount(0)
        self.delete_button.setEnabled(False)
        self._set_status("부분 성공" if bundle.error_items and bundle.preview_items else "오류 발생" if bundle.error_items else "미리보기 준비 완료")
        if restored_count:
            self._set_status(self.status_label.text() + f" / 수동 파일명 {restored_count}건 유지")
        preview_count = len(bundle.preview_items)
        error_count = len(bundle.error_items)
        self._set_idle_progress(f"미리보기 완료: 준비 {preview_count}건, 오류 {error_count}건")
        self._set_busy(False)
        self._update_selection_detail("preview")
        self._job_preview_completed()

    def _handle_execute(self) -> None:
        if self._busy:
            return
        self.execute_button.setFocus()  # 편집 중인 셀을 확정한 뒤 실행한다.
        current = self._request_from_inputs(preview_only=False)
        if not self._job_validate_before_execute(current):
            return
        if self._preview_mapping_changed(current):
            QMessageBox.warning(self, "미리보기 필요", "모델명 매핑이나 적용 범위가 변경되었습니다. 미리보기를 다시 만들어주세요. 같은 Source·Target에서는 직접 수정한 파일명을 유지합니다.")
            return
        if self.last_preview_bundle is not None and getattr(self.last_preview_bundle, "selection_applied", False):
            if self.last_execution_bundle is not None or self.last_preview_signature != self._request_signature(current):
                QMessageBox.warning(self, "미리보기 필요", "모델 선택이 적용된 미리보기의 설정이 바뀌었거나 이미 실행되었습니다. 미리보기를 다시 만들어주세요.")
                return
        if self.last_preview_bundle is not None and not any(getattr(item, "included", True) for item in self.last_preview_bundle.preview_items):
            QMessageBox.information(self, "처리 모델 선택", "처리할 모델을 하나 이상 선택해주세요.")
            return
        request = self._build_request(preview_only=False)
        if request is None:
            return
        if self.last_preview_bundle and any(item.filename_edited for item in self.last_preview_bundle.preview_items):
            if self.last_execution_bundle is not None:
                QMessageBox.warning(self, "미리보기 필요", "이미 실행한 미리보기입니다. 다시 미리보기를 만들어주세요.")
                return
            if self.last_preview_signature != self._request_signature(request):
                QMessageBox.warning(self, "미리보기 필요", "설정이 변경되어 수정한 파일명을 그대로 실행할 수 없습니다. 미리보기를 다시 만든 뒤 수정해주세요.")
                return
        current_signature = self._request_signature(request)
        if self.last_preview_bundle is None or self.last_preview_signature != current_signature:
            self._set_busy(True)
            try:
                self.last_preview_bundle = self._run_engine_operation(self.engine.preview, request)
            except OperationStopped:
                self._set_status("미리보기 중단 — 실행을 시작하지 않았습니다.")
                self._set_idle_progress("미리보기 중단")
                return
            except Exception as exc:
                self._show_operation_error("미리보기 실패", exc)
                return
            finally:
                self._set_busy(False)
            self.last_preview_signature = current_signature
            self._job_preview_completed()
        if not self._job_execution_checkpoint():
            return
        self._set_busy(True)
        self._update_progress("실행 준비 중", 0, 0)
        if self.last_preview_bundle is not None and self.last_preview_signature == current_signature:
            try:
                execute_options = {"preview_bundle": self.last_preview_bundle}
                if isinstance(self.engine, OrganizerEngine):
                    execute_options["job_state"] = self._job_state
                bundle = self._run_engine_operation(self.engine.execute, request, **execute_options)
            except Exception as exc:
                try:
                    self._refresh_journal()
                    self._display_recovered_results()
                except (ValueError, OSError):
                    self._journal_available = False
                if getattr(self._job_state, "ledger", None):
                    self._job_execution_completed()
                    self._display_recovered_results()
                self._set_busy(False)
                self._show_operation_error("실행 완료 여부 미확인", exc)
                return
        else:
            bundle = self._run_engine_operation(self.engine.execute, request)
            self.last_preview_bundle = PreviewBundle(
                preview_items=bundle.preview_items,
                error_items=bundle.error_items,
                log_events=bundle.log_events,
                model_name_mappings=dict(request.model_name_mappings),
                model_mapping_scope=request.model_mapping_scope,
            )
            self.last_preview_signature = current_signature
            self.model_selection_panel.set_items(bundle.preview_items)
        self.last_execution_bundle = bundle
        self.model_selection_panel.refresh(bundle.preview_items)
        self.current_delete_candidates = bundle.delete_review_items
        self._fill_preview_table(bundle.preview_items)
        self._fill_results_table(bundle.execution_results)
        self._fill_error_table(bundle.error_items)
        self._fill_delete_table(bundle.delete_review_items)
        self.delete_button.setEnabled(bool(bundle.delete_review_items))
        mobile_output_failed = any(item.mobile_output_status == "ERROR" for item in bundle.execution_results)
        if mobile_output_failed:
            self._set_status("실행 실패")
        elif bundle.error_items and bundle.execution_results:
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
        self._job_execution_completed()
        if getattr(self._job_state, "ledger", None):
            self._display_recovered_results()
        if self._operation_stopped:
            self._set_status("사용자 요청으로 중단 — " + self._recovered_counts())
            self._set_idle_progress("사용자 요청으로 중단 — " + self._recovered_counts())
        self._set_busy(False)
        self._update_selection_detail("results")

    def _preview_mapping_changed(self, request: OrganizeRequest) -> bool:
        bundle = self.last_preview_bundle
        if bundle is None:
            return False
        mappings = getattr(bundle, "model_name_mappings", None)
        scope = getattr(bundle, "model_mapping_scope", None)
        if mappings is not None and scope is not None:
            return model_mapping_signature(mappings, scope) != model_mapping_signature(request.model_name_mappings, request.model_mapping_scope)
        # 구형 테스트/외부 미리보기 객체는 저장한 요청 서명을 사용한다.
        signature = self.last_preview_signature
        return signature is not None and signature[5:7] != self._request_signature(request)[5:7]

    def _handle_delete_review(self) -> None:
        if self._busy:
            return
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
        if not self._job_validate_delete(chosen):
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
        if self._preview_metadata_bundle is not self.last_preview_bundle:
            self._preview_metadata_bundle = self.last_preview_bundle
            self._preview_metadata_fingerprints = {}
            job = self._job_state
            baselines = job.source_fingerprints if job and job.preview_bundle is self.last_preview_bundle else {}
            for item in items:
                baseline = baselines.get(item.source_path)
                self._preview_metadata_fingerprints[item.source_path] = (
                    ((baseline['size'], baseline['mtime_ns']) if baseline.get('exists') else None)
                    if baseline is not None else self._file_detail_fingerprint(Path(item.source_path)))
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(items))
        for row, item in enumerate(items):
            entries = dict(item.metadata_entries)
            notices = ([entries["모델명 보완"]] if item.model_name == "UNKNOWN" and entries.get("모델명 보완") else [])
            if item.filename_edited:
                notices.append("사용자 파일명 수정(분류 폴더 유지)")
            warning_text = "; ".join(notices + item.warnings)
            included = getattr(item, "included", True)
            action_text = self._write_mode_label(item.write_mode) if included else "제외"
            values = [item.source_path, item.target_path, action_text, item.new_filename, item.datetime_source, item.model_source, warning_text, entries.get("영상 모델 조회", "-")]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if not included:
                    cell.setBackground(QColor("#f1f1f1"))
                    cell.setForeground(QColor("#777777"))
                elif item.model_name == "UNKNOWN":
                    cell.setBackground(QColor("#fff0f0"))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if column == 3 and included and self.last_execution_bundle is None and not self._job_started():
                    cell.setFlags(cell.flags() | Qt.ItemIsEditable)
                    cell.setData(Qt.UserRole, item.item_id)
                cell.setToolTip(value)
                self.preview_table.setItem(row, column, cell)
        self.preview_table.blockSignals(False)

    def _handle_model_selection(self, selected_models: set[str]) -> None:
        bundle = self.last_preview_bundle
        if bundle is None:
            return
        if self._busy or self.last_execution_bundle is not None or self._job_started():
            self.model_selection_panel.refresh(bundle.preview_items)
            return
        current = self._request_from_inputs(preview_only=True)
        if self.last_preview_signature != self._request_signature(current):
            self.model_selection_panel.refresh(bundle.preview_items)
            QMessageBox.warning(self, "미리보기 필요", "입력이나 설정이 변경되었습니다. 미리보기를 다시 만든 뒤 모델을 선택해주세요.")
            return
        try:
            self.engine.set_selected_models(bundle, selected_models)
        except (ValueError, OSError) as exc:
            self.model_selection_panel.refresh(bundle.preview_items)
            self._set_status(f"모델 선택 실패: {exc}")
            QMessageBox.warning(self, "모델 선택 실패", str(exc))
            return
        self.model_selection_panel.refresh(bundle.preview_items)
        self._fill_preview_table(bundle.preview_items)
        self._fill_error_table(bundle.error_items)
        self._set_status("모델 선택 적용: " + self.model_selection_panel.summary_label.text())
        self._update_selection_detail("preview")
        self._job_mark_changed()

    def _handle_filename_edit(self, cell: QTableWidgetItem) -> None:
        if self._busy or self._job_started():
            return
        if cell.column() != 3 or self.last_preview_bundle is None:
            return
        item_id = cell.data(Qt.UserRole)
        row = cell.row()
        item = next((item for item in self.last_preview_bundle.preview_items if item.item_id == item_id), None)
        if item is None or not getattr(item, "included", True) or cell.text() == item.new_filename:
            return
        try:
            self.engine.edit_preview_filename(self.last_preview_bundle, item_id, cell.text())
            self._set_status("파일명 수정 적용: 기존 분류 폴더 유지")
        except ValueError as exc:
            QMessageBox.warning(self, "파일명 수정 불가", str(exc))
        self._fill_preview_table(self.last_preview_bundle.preview_items)
        self.preview_table.selectRow(row)
        self._update_selection_detail("preview")
        self._job_mark_changed()

    def _fill_results_table(self, items, append: bool = False) -> None:
        start_row = self.results_table.rowCount() if append else 0
        if not append:
            self.results_table.setRowCount(0)
        self.results_table.setRowCount(start_row + len(items))
        for offset, item in enumerate(items):
            row = start_row + offset
            mobile_output_label = "생성 안 함"
            mobile_output_path = "-"
            if item.mobile_output_path:
                mobile_output_path = item.mobile_output_path
                mobile_output_label = {
                    "ERROR": "실패",
                    "SKIPPED": "건너뜀",
                    "SUCCESS": "생성됨",
                    "SIZE_EXCLUDED": "출력 용량 제한 제외",
                }.get(item.mobile_output_status, "생성 예정")
            values = [
                item.status,
                item.action,
                self._write_mode_label(item.write_mode),
                item.source_path,
                item.target_path,
                mobile_output_label,
                mobile_output_path,
                " / ".join(message for message in (item.message, getattr(item, "mobile_output_message", "")) if message),
            ]
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
        if self._busy:
            return
        self._job_mark_changed()
        current = self.tabs.currentWidget()
        if current is self.preview_tab:
            self._update_selection_detail("preview")
        elif current is self.results_table:
            self._update_selection_detail("results")
        elif current is self.error_table:
            self._update_selection_detail("error")
        elif current is self.delete_table:
            self._update_selection_detail("delete")

    def _handle_results_item_clicked(self, item: QTableWidgetItem) -> None:
        if self._busy:
            return
        if item.column() in (3, 4, 6):
            self._results_detail_column = item.column()
        self._update_selection_detail("results")

    def _handle_preview_item_clicked(self, item: QTableWidgetItem) -> None:
        if self._busy:
            return
        if item.column() in (0, 1, 3):
            self._preview_detail_column = item.column()
        self._update_selection_detail("preview")

    def _preview_detail_target(self, row: int) -> tuple[Path | None, str]:
        column = 0 if self._preview_detail_column == 0 else 1
        text = self._cell_text(self.preview_table, row, column)
        kind = '원본 파일' if column == 0 else '대상 파일'
        return (Path(text) if text and text != '-' else None), kind

    def _update_selection_detail(self, table_name: str) -> None:
        if self._busy:
            return
        self._update_preview_image(table_name)
        if table_name == "preview":
            selected_items = self.preview_table.selectedItems()
            if not selected_items:
                self._set_selection_detail_text("미리보기 항목을 선택하면 전체 원본 경로와 대상 경로를 여기서 확인할 수 있습니다.")
                self._set_selection_metadata([])
                return
            row = selected_items[0].row()
            preview_item = self.last_preview_bundle.preview_items[row] if self.last_preview_bundle and row < len(self.last_preview_bundle.preview_items) else None
            detail_path, detail_kind = self._preview_detail_target(row)
            lines = [
                f"원본 경로: {self._cell_text(self.preview_table, row, 0)}",
                f"대상 경로: {self._cell_text(self.preview_table, row, 1)}",
                f"처리 방식: {self._cell_text(self.preview_table, row, 2)}",
                f"새 파일명: {self._cell_text(self.preview_table, row, 3)}",
                f"일시 근거: {self._cell_text(self.preview_table, row, 4)}",
                f"모델명 근거: {self._cell_text(self.preview_table, row, 5)}",
                f"안내/오류: {self._cell_text(self.preview_table, row, 6)}",
                f"영상 모델 조회: {self._cell_text(self.preview_table, row, 7)}",
            ]
            if preview_item is not None:
                if preview_item.mobile_output_enabled and preview_item.mobile_output_path:
                    lines.append(f"모바일 출력 경로: {preview_item.mobile_output_path}")
                else:
                    lines.append("모바일 출력: 사용 안 함")
            lines[0:0] = [f'상세 기준: {detail_kind}', f'상세 파일 경로: {detail_path or "-"}']
            try:
                available = detail_path is not None and detail_path.is_file()
            except OSError:
                available = False
            if not available:
                lines.insert(2, '현재 파일 상태: 대상 파일이 아직 없습니다. 미생성 또는 누락된 파일입니다.'
                             if detail_kind == '대상 파일' else '현재 파일 상태: 원본 파일을 찾을 수 없습니다.')
                entries = []
            elif (detail_kind == '원본 파일' and preview_item is not None and preview_item.metadata_entries
                  and self._preview_metadata_fingerprints.get(preview_item.source_path) is not None
                  and self._file_detail_fingerprint(detail_path) == self._preview_metadata_fingerprints[preview_item.source_path]):
                entries = preview_item.metadata_entries
            else:
                entries = self._metadata_entries_for_path(detail_path)
            self._set_selection_detail_text("\n".join(lines))
            self._set_selection_metadata(entries)
            return
        if table_name == "results":
            selected_items = self.results_table.selectedItems()
            if not selected_items:
                self._set_selection_detail_text("실행 결과 항목을 선택하면 전체 원본 경로와 대상 경로를 여기서 확인할 수 있습니다.")
                self._set_selection_metadata([])
                return
            row = selected_items[0].row()
            result_item = self.last_execution_bundle.execution_results[row] if self.last_execution_bundle and row < len(self.last_execution_bundle.execution_results) else None
            detail_path, detail_kind = self._results_detail_target(row)
            lines = [
                f"상태: {self._cell_text(self.results_table, row, 0)}",
                f"동작: {self._cell_text(self.results_table, row, 1)}",
                f"처리 방식: {self._cell_text(self.results_table, row, 2)}",
                f"원본 경로: {self._cell_text(self.results_table, row, 3)}",
                f"대상 경로: {self._cell_text(self.results_table, row, 4)}",
                f"모바일 출력 상태: {self._cell_text(self.results_table, row, 5)}",
                f"모바일 출력 경로: {self._cell_text(self.results_table, row, 6)}",
                f"메시지: {self._cell_text(self.results_table, row, 7)}",
            ]
            lines.append(f"상세 기준: {detail_kind}")
            if result_item is not None:
                if getattr(result_item, "mobile_output_message", ""):
                    lines.append(f"모바일 출력 안내: {result_item.mobile_output_message}")
                if result_item.mobile_output_path:
                    lines.append(f"모바일 출력 처리 결과: {result_item.mobile_output_status or '-'}")
                else:
                    lines.append("모바일 출력: 생성 안 함")
            self._set_selection_detail_text("\n".join(lines))
            self._set_selection_metadata(self._metadata_entries_for_path(detail_path))
            return
        if table_name == "error":
            selected_items = self.error_table.selectedItems()
            if not selected_items:
                self._set_selection_detail_text("오류 항목을 선택하면 전체 원본 경로와 오류 내용을 여기서 확인할 수 있습니다.")
                self._set_selection_metadata([])
                return
            row = selected_items[0].row()
            lines = [
                f"원본 경로: {self._cell_text(self.error_table, row, 0)}",
                f"오류 내용: {self._cell_text(self.error_table, row, 1)}",
            ]
            self._set_selection_detail_text("\n".join(lines))
            self._set_selection_metadata([])
            return
        selected_items = self.delete_table.selectedItems()
        if not selected_items:
            self._set_selection_detail_text("삭제 리뷰 항목을 선택하면 전체 삭제 대상 경로와 사유를 여기서 확인할 수 있습니다.")
            self._set_selection_metadata([])
            return
        row = selected_items[0].row()
        checkbox = self.delete_table.cellWidget(row, 0)
        selected = isinstance(checkbox, QCheckBox) and checkbox.isChecked()
        lines = [
            f"선택 여부: {'선택됨' if selected else '선택 안 됨'}",
            f"삭제 대상 경로: {self._cell_text(self.delete_table, row, 1)}",
            f"사유: {self._cell_text(self.delete_table, row, 2)}",
        ]
        self._set_selection_detail_text("\n".join(lines))
        self._set_selection_metadata([])

    def _update_preview_image(self, table_name: str) -> None:
        if self._busy:
            return
        source_path = self._selected_image_source_path(table_name)
        if not source_path:
            self._current_preview_source_path = None
            if table_name == "delete":
                self._set_preview_image_placeholder("삭제 리뷰에서는 원본 이미지 미리보기를 표시하지 않습니다.")
            else:
                self._set_preview_image_placeholder("사진은 축소 미리보기, 영상은 썸네일 미리보기가 표시됩니다.")
            return
        path = Path(source_path)
        if not path.exists() or not path.is_file():
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("선택한 파일을 찾을 수 없습니다.")
            self.preview_image_info.setText(str(path))
            return
        target_size = self.preview_image_scroll.viewport().size()
        if target_size.width() < 240 or target_size.height() < 180:
            target_size = QSize(640, 420)
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            if self._load_video_thumbnail(path, target_size):
                return
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("영상 썸네일을 추출하지 못했습니다. ffmpeg가 없거나 지원되지 않는 영상일 수 있습니다.")
            self.preview_image_info.setText(str(path))
            return
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if not reader.canRead():
            self._current_preview_source_path = None
            self._set_preview_image_placeholder("비사진/영상 또는 지원되지 않는 이미지 형식이라 미리보기할 수 없습니다.")
            self.preview_image_info.setText(str(path))
            return
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

    def _load_video_thumbnail(self, path: Path, target_size: QSize) -> bool:
        max_width = max(240, target_size.width())
        try:
            info = path.stat()
        except OSError:
            return False
        cache_key = (str(path.resolve()), max_width, info.st_size, info.st_mtime_ns)
        pixmap = self._video_thumbnail_cache.get(cache_key)
        if pixmap is None:
            thumbnail_bytes = extract_video_thumbnail_bytes(path, max_width=max_width)
            if not thumbnail_bytes:
                return False
            pixmap = QPixmap()
            if not pixmap.loadFromData(thumbnail_bytes, "PNG"):
                return False
            self._video_thumbnail_cache[cache_key] = pixmap
        self._current_preview_source_path = path
        self.preview_image_view.setPixmap(pixmap)
        self.preview_image_view.setText("")
        self.preview_image_info.setText(f"{path.name} | 영상 썸네일")
        return True

    def _selected_image_source_path(self, table_name: str) -> str:
        if table_name == "preview":
            selected = self.preview_table.selectedItems()
            if not selected:
                return ''
            path, _kind = self._preview_detail_target(selected[0].row())
            return str(path) if path is not None else ''
        elif table_name == "results":
            row, _detail_kind = self._selected_results_row()
            if row is None:
                return ""
            path, _detail_kind = self._results_detail_target(row)
            return str(path) if path is not None else ""
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

    def _selected_results_row(self) -> tuple[int | None, str]:
        selected_items = self.results_table.selectedItems()
        if not selected_items:
            return None, "원본 파일"
        kind_map = {
            3: "원본 파일",
            4: "대상 파일",
            6: "모바일 출력 파일",
        }
        return selected_items[0].row(), kind_map.get(self._results_detail_column, "원본 파일")

    def _results_detail_target(self, row: int) -> tuple[Path | None, str]:
        if self._results_detail_column == 6:
            mobile_output_text = self._cell_text(self.results_table, row, 6)
            if mobile_output_text and mobile_output_text != "-":
                return Path(mobile_output_text), "모바일 출력 파일"
            self._results_detail_column = 4
        if self._results_detail_column == 4:
            target_text = self._cell_text(self.results_table, row, 4)
            if target_text and target_text != "-":
                return Path(target_text), "대상 파일"
            self._results_detail_column = 3
        source_text = self._cell_text(self.results_table, row, 3)
        if source_text and source_text != "-":
            return Path(source_text), "원본 파일"
        return None, "원본 파일"

    @staticmethod
    def _file_detail_fingerprint(path: Path) -> tuple[int, int] | None:
        try:
            if path.is_file():
                info = path.stat()
                return info.st_size, info.st_mtime_ns
        except OSError:
            pass
        return None

    def _metadata_entries_for_path(self, path: Path | None) -> list[tuple[str, str]]:
        if self._operation_active:
            return []
        if path is None:
            return []
        try:
            if not path.is_file():
                self._detail_metadata_cache.pop(str(path), None)
                return []
            info = path.stat()
        except OSError:
            return []
        fingerprint = (info.st_size, info.st_mtime_ns)
        cache_key = str(path)
        cached = self._detail_metadata_cache.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        entries = self.engine.describe_media_path(path)
        self._detail_metadata_cache[cache_key] = (fingerprint, entries)
        return entries

    def _set_preview_image_placeholder(self, text: str) -> None:
        self.preview_image_view.setPixmap(QPixmap())
        self.preview_image_view.setText(text)
        self.preview_image_info.setText(text)

    def _set_selection_detail_text(self, text: str) -> None:
        self.selection_detail.setPlainText(text)

    def _set_selection_metadata(self, entries: list[tuple[str, str]]) -> None:
        rows = entries or [("메타정보", "메타정보 없음")]
        self.selection_metadata_table.setRowCount(len(rows))
        for row, (label, value) in enumerate(rows):
            label_text = label or "-"
            value_text = value or "-"
            label_item = QTableWidgetItem(label_text)
            value_item = QTableWidgetItem(value_text)
            label_item.setToolTip(label_text)
            value_item.setToolTip(value_text)
            self.selection_metadata_table.setItem(row, 0, label_item)
            self.selection_metadata_table.setItem(row, 1, value_item)

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
        self._busy = busy
        self.model_selection_panel.setEnabled(not busy and self.last_execution_bundle is None and bool(self.last_preview_bundle and self.last_preview_bundle.preview_items))
        self.preview_table.setEnabled(not busy)
        for table in (self.results_table, self.error_table, self.delete_table, self.selection_metadata_table):
            table.setEnabled(not busy)
        self.tabs.tabBar().setEnabled(not busy)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers if self._job_started() else
                                           QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.preview_button.setEnabled(not busy)
        self.execute_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and bool(self.current_delete_candidates))
        self.settings_button.setEnabled(not busy)
        self.phone_transfer_button.setEnabled(not busy)
        for widget in (self.source_edit, self.target_edit, self.device_name_edit, self.mode_combo,
                       self.source_select_button, self.target_select_button):
            widget.setEnabled(not busy and not self._job_started())
        self._job_controls_busy(busy)
        self._poll_operation_control()
        QApplication.processEvents()
        if not busy:
            self._schedule_operation_autosave()

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
        if self._busy or not self._confirm_job_transition():
            event.ignore()
            return
        self._job_timer.stop()
        if self._global_settings.autosave_job_changes:
            self._autosave_job()
        self._save_current_inputs()
        self._job_timer.stop()
        super().closeEvent(event)
