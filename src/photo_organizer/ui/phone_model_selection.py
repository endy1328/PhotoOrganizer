"""Phone-copy model choices identified from output folder names, without I/O."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QCheckBox, QPushButton, QScrollArea, QSizePolicy)
from .model_selection import FlowLayout


class PhoneModelSelection(QWidget):
    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.checkboxes = {}
        self._choices = {}
        self._counts = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel('복사할 모델'))
        self.summary_label = QLabel('선택 폴더 0 / 전체 0')
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.summary_label, 1)
        self.all_button = QPushButton('전체 선택')
        self.none_button = QPushButton('전체 해제')
        row.addWidget(self.all_button)
        row.addWidget(self.none_button)
        layout.addLayout(row)
        self.flow_container = QWidget()
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.flow_container.setSizePolicy(policy)
        self.flow_layout = FlowLayout(self.flow_container)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setMinimumSize(0, 0)
        self.scroll_area.setMaximumHeight(100)
        self.scroll_area.setWidget(self.flow_container)
        layout.addWidget(self.scroll_area)
        self.all_button.clicked.connect(lambda: self._select_all(True))
        self.none_button.clicked.connect(lambda: self._select_all(False))
        self.setEnabled(False)

    @staticmethod
    def model_for_folder(folder):
        path = Path(getattr(folder, 'path', folder))
        match = re.fullmatch(r'output_(\d{8})_(.+)', path.name, flags=re.IGNORECASE)
        if match is None or not match[2].strip():
            return '미분류'
        try:
            datetime.strptime(match[1], '%Y%m%d')
        except ValueError:
            return '미분류'
        return match[2]

    def set_folders(self, folders):
        self._choices.update({model: box.isChecked() for model, box in self.checkboxes.items()})
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.blockSignals(True)
                widget.hide()
                widget.deleteLater()
        self.checkboxes.clear()
        self._counts = Counter(self.model_for_folder(folder) for folder in folders)
        for model in sorted(self._counts, key=lambda name: (name == '미분류', name == 'UNKNOWN', name.casefold())):
            box = QCheckBox(f'{model} (폴더 {self._counts[model]}개)')
            box.setToolTip(box.text())
            box.setChecked(self._choices.get(model, True))
            box.toggled.connect(self._changed)
            self.checkboxes[model] = box
            self.flow_layout.addWidget(box)
        self.setEnabled(bool(self.checkboxes))
        self._changed()

    def selected_models(self):
        return {model for model, box in self.checkboxes.items() if box.isChecked()}

    def _select_all(self, selected):
        for box in self.checkboxes.values():
            previous = box.blockSignals(True)
            box.setChecked(selected)
            box.blockSignals(previous)
        self._changed()

    def _changed(self):
        selected = self.selected_models()
        self._choices.update({model: box.isChecked() for model, box in self.checkboxes.items()})
        count = sum(self._counts[model] for model in selected)
        text = f'선택 폴더 {count} / 전체 {sum(self._counts.values())}'
        self.summary_label.setText(text)
        self.summary_label.setToolTip(text)
        self.selection_changed.emit(selected)
