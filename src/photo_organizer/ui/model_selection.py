from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class FlowLayout(QLayout):
    """Lay out model controls horizontally, wrapping to the available width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return QSize(0, size.height())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y = rect.x(), rect.y()
        row_height = 0
        for item in self.items:
            size = item.sizeHint()
            size.setWidth(min(size.width(), max(1, rect.width())))
            if row_height and x + size.width() > rect.x() + rect.width():
                x = rect.x()
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y - rect.y() + row_height


class ModelSelectionPanel(QWidget):
    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.checkboxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.toggle_button = QToolButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.setAccessibleName("처리할 모델 펼치기/접기")
        self.toggle_button.setToolTip("처리할 모델 선택 펼치기/접기")
        header.addWidget(self.toggle_button)
        self.title_label = QLabel("처리할 모델")
        header.addWidget(self.title_label)
        layout.addLayout(header)
        self.flow_container = QWidget()
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.flow_container.setSizePolicy(policy)
        self.flow_layout = FlowLayout(self.flow_container)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setMinimumWidth(0)
        self.scroll_area.setMinimumHeight(0)
        self.scroll_area.setMaximumHeight(110)
        self.scroll_area.setWidget(self.flow_container)
        self.scroll_area.hide()
        self.toggle_button.toggled.connect(self._set_expanded)
        layout.addWidget(self.scroll_area)
        self.summary_label = QLabel("처리 0건 / 제외 0건")
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self.summary_label, 1)
        self.setEnabled(False)

    def set_items(self, items) -> None:
        while self.flow_layout.count():
            child = self.flow_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        self.checkboxes.clear()
        counts: dict[str, dict[str, int]] = {}
        for item in items:
            counts.setdefault(item.model_name, {"photo": 0, "video": 0})[item.media_type] += 1
        for model in sorted(counts, key=lambda name: (name == "UNKNOWN", name.casefold())):
            count = counts[model]
            alias = next((getattr(item, "output_model_name", "") or model for item in items if item.model_name == model), model)
            name = f"{model} → {alias}" if alias != model else model
            box = QCheckBox(f"{name} (사진 {count['photo']} / 영상 {count['video']})")
            box.setToolTip(box.text())
            box.setChecked(any(getattr(item, "included", True) for item in items if item.model_name == model))
            box.toggled.connect(self._changed)
            self.flow_layout.addWidget(box)
            self.checkboxes[model] = box
        self.refresh(items)

    def _set_expanded(self, expanded: bool) -> None:
        self.scroll_area.setVisible(expanded)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def selected_models(self) -> set[str]:
        return {model for model, box in self.checkboxes.items() if box.isChecked()}

    def refresh(self, items) -> None:
        selected = {item.model_name for item in items if getattr(item, "included", True)}
        for model, box in self.checkboxes.items():
            box.blockSignals(True)
            box.setChecked(model in selected)
            box.blockSignals(False)
        included = [item for item in items if getattr(item, "included", True)]
        photos = sum(item.media_type == "photo" for item in included)
        videos = sum(item.media_type == "video" for item in included)
        self.summary_label.setText(f"처리 {len(included)}건 (사진 {photos} / 영상 {videos}) / 제외 {len(items) - len(included)}건")
        self.summary_label.setToolTip(self.summary_label.text())

    def _changed(self) -> None:
        self.selection_changed.emit(self.selected_models())
