"""Read-only review of validated recovery actions."""
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget,
                              QTableWidgetItem, QAbstractItemView, QHeaderView,
                              QDialogButtonBox)


class ResumePlanDialog(QDialog):
    def __init__(self, parent, actions, *, mode):
        super().__init__(parent)
        self.setWindowTitle('실패 항목 재시도 계획' if mode == 'retry' else '이어서 실행 계획')
        self.resize(850, 460)
        layout = QVBoxLayout(self)
        counts = {key: sum(action.action == key for action in actions) for key in ('RUN', 'WAIT', 'KEEP', 'BLOCK')}
        self.summary_label = QLabel(f"실행 가능 {counts['RUN']}단계 / 선행 완료 후 실행 {counts['WAIT']}단계 / 완료 유지 {counts['KEEP']}단계 / 확인 필요 {counts['BLOCK']}단계")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        note = QLabel('완료된 파일은 유지합니다. 확인이 필요한 단계는 실행하지 않습니다. 실행 직전에 파일 상태를 다시 검사합니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(actions), 4)
        self.table.setHorizontalHeaderLabels(['항목', '단계', '처리 계획', '근거'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(2, 155)
        labels = {'main': '기본 정리', 'output': '모바일 출력', 'source_remove': '이동 마무리'}
        decisions = {'RUN': '실행', 'WAIT': '선행 완료 후 실행', 'KEEP': '완료 유지', 'BLOCK': '확인 필요'}
        bundle = getattr(parent, 'last_preview_bundle', None)
        items = {item.item_id: item for item in bundle.preview_items} if bundle else {}
        for row, action in enumerate(actions):
            item = items.get(action.item_id)
            display_name = Path(item.source_path).name if item else action.item_id
            for col, value in enumerate((display_name, labels.get(action.stage, action.stage),
                                         decisions[action.action], action.reason)):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(f'원본: {item.source_path}\n대상: {item.target_path}' if item and col == 0 else str(value))
                self.table.setItem(row, col, cell)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText('취소')
        self.run_button = buttons.addButton('가능한 항목 실행', QDialogButtonBox.AcceptRole)
        self.run_button.setEnabled(any(action.action == 'RUN' and action.allowed for action in actions))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
