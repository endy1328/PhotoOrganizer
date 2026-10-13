"""Preview selection and asynchronous original-model editing controls."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QEventLoop, QThread, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                              QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                              QVBoxLayout)


class MetadataIoWorker(QThread):
    def __init__(self, function, args, kwargs, parent):
        super().__init__(parent)
        self.function, self.args = function, args
        self.kwargs = kwargs
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.function(*self.args, **self.kwargs)
        except Exception as exc:
            self.error = exc


class OriginalModelDialog(QDialog):
    def __init__(self, parent, row, info, models):
        super().__init__(parent)
        self.setWindowTitle('원본 메타정보 수정')
        self.resize(580, 310)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        path = QLabel(row.source_path)
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow('원본 파일', path)
        current = QLabel(str(info.get('model') or '(모델명 태그 없음)'))
        current.setWordWrap(True)
        form.addRow('원본 모델명', current)
        preview = QLabel(f'{row.model_name} / {row.model_source}')
        preview.setWordWrap(True)
        form.addRow('미리보기 모델', preview)
        if row.output_model_name and row.output_model_name != row.model_name:
            form.addRow('출력 별칭', QLabel(row.output_model_name))
        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems(sorted(set(models)))
        self.model_input.setCurrentText(str(info.get('model') or ''))
        form.addRow('기록할 모델명', self.model_input)
        layout.addLayout(form)
        note = QLabel('원본 파일의 모델명 태그를 수정합니다. 촬영 일시와 다른 메타정보는 유지합니다. '
                      '변경 전 파일을 같은 폴더의 메타정보 보관 폴더에 백업합니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        if info.get('backup_path'):
            backup = QLabel('최근 백업: ' + info['backup_path'])
            backup.setWordWrap(True)
            layout.addWidget(backup)
        records = info.get('records') or []
        pending = [record for record in records if record.get('state') not in ('COMMITTED', 'RESTORED')]
        if pending:
            recovery = QLabel('중간에 종료된 수정 기록이 있습니다. 현재 원본과 백업의 상태를 확인했습니다. '
                              '원본 백업 복원 메뉴에서 복원할 수 있습니다.')
            recovery.setWordWrap(True)
            layout.addWidget(recovery)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        self.save_button.setText('원본에 저장')
        self.save_button.setEnabled(bool(info.get('supported')))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        from ..fallback import canonical_model_key
        model = self.model_input.currentText().strip()
        if not canonical_model_key(model) or any(c in model for c in '\r\n\x00'):
            QMessageBox.warning(self, '모델명 확인', '파일명에 사용할 영문 또는 숫자가 포함된 실제 모델명을 입력해주세요. 예: Galaxy_Z_Fold6')
            return
        super().accept()


class OriginalMetadataMixin:
    def _build_original_metadata_controls(self, layout):
        self._original_metadata_worker = None
        row = QHBoxLayout()
        self.metadata_edit_button = QPushButton('원본 메타정보 수정')
        self.metadata_restore_button = QPushButton('원본 백업 복원')
        row.addWidget(self.metadata_edit_button)
        row.addWidget(self.metadata_restore_button)
        row.addStretch()
        layout.addLayout(row)
        self.metadata_edit_button.clicked.connect(self._open_original_metadata)
        self.metadata_restore_button.clicked.connect(self._restore_original_metadata)
        self.preview_table.itemSelectionChanged.connect(self._update_original_metadata_controls)
        self.preview_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_table.customContextMenuRequested.connect(self._preview_actions_menu)
        self._update_original_metadata_controls()

    def _original_metadata_selected_item(self):
        bundle = self.last_preview_bundle
        indexes = self.preview_table.selectionModel().selectedRows()
        if bundle is None or len(indexes) != 1:
            return None
        row = indexes[0].row()
        return bundle.preview_items[row] if 0 <= row < len(bundle.preview_items) else None

    def _preview_change_allowed(self):
        return (not self._busy and not self._job_started() and
                self.last_execution_bundle is None and self.last_preview_bundle is not None)

    def _update_original_metadata_controls(self):
        if not hasattr(self, 'metadata_edit_button'):
            return
        item = self._original_metadata_selected_item()
        enabled = self._preview_change_allowed() and item is not None and self.tabs.currentWidget() is self.preview_tab
        self.metadata_edit_button.setEnabled(enabled)
        self.metadata_restore_button.setEnabled(enabled)

    def _refresh_file_checks(self):
        if self.last_preview_bundle is None or self.preview_table.columnCount() < 10:
            return
        self.preview_table.blockSignals(True)
        for row, item in enumerate(self.last_preview_bundle.preview_items):
            cell = self.preview_table.item(row, 9)
            if cell is not None:
                flags = cell.flags() & ~Qt.ItemIsUserCheckable
                if self._preview_change_allowed():
                    flags |= Qt.ItemIsUserCheckable
                cell.setFlags(flags)
                cell.setCheckState(Qt.Checked if item.file_selected else Qt.Unchecked)
        self.preview_table.blockSignals(False)
        self._update_original_metadata_controls()

    def _selection_request_is_current(self):
        current = self._request_from_inputs(preview_only=True)
        if self.last_preview_signature != self._request_signature(current):
            QMessageBox.warning(self, '미리보기 필요', '입력이나 설정이 변경되었습니다. 먼저 미리보기를 다시 만들어주세요.')
            return False
        return True

    def _handle_file_check(self, cell):
        if not self._preview_change_allowed():
            self._refresh_file_checks()
            return
        self._set_preview_files([cell.data(Qt.UserRole)], cell.checkState() == Qt.Checked)

    def _set_preview_files(self, identifiers, selected):
        if not self._preview_change_allowed():
            return
        if not self._selection_request_is_current():
            self._refresh_file_checks()
            return
        try:
            bundle = self.last_preview_bundle
            self.engine.set_selected_files(bundle, set(identifiers), selected)
            self.model_selection_panel.refresh(bundle.preview_items, bundle.selected_models)
            self._fill_preview_table(bundle.preview_items)
            self._set_status('파일 선택 적용: ' + self.model_selection_panel.summary_label.text())
            self._job_mark_changed()
        except (ValueError, OSError) as exc:
            self._refresh_file_checks()
            QMessageBox.warning(self, '파일 선택 실패', str(exc))

    def _preview_actions_menu(self, point):
        cell = self.preview_table.itemAt(point)
        if cell is None:
            return
        if not cell.isSelected():
            self.preview_table.selectRow(cell.row())
        menu = QMenu(self)
        identifiers = [self.last_preview_bundle.preview_items[i.row()].item_id
                       for i in self.preview_table.selectionModel().selectedRows()] if self.last_preview_bundle else []
        for text, selected in (('선택 파일 제외', False), ('선택 파일 다시 포함', True)):
            action = menu.addAction(text)
            action.setEnabled(self._preview_change_allowed())
            action.triggered.connect(lambda checked=False, s=selected: self._set_preview_files(identifiers, s))
        menu.addSeparator()
        edit = menu.addAction('원본 메타정보 수정')
        edit.setEnabled(self._preview_change_allowed() and len(identifiers) == 1)
        edit.triggered.connect(self._open_original_metadata)
        restore = menu.addAction('원본 백업 복원')
        restore.setEnabled(edit.isEnabled())
        restore.triggered.connect(self._restore_original_metadata)
        menu.exec(self.preview_table.viewport().mapToGlobal(point))

    def _metadata_io(self, function, *args, **kwargs):
        worker = MetadataIoWorker(function, args, kwargs, self)
        loop = QEventLoop(self)
        worker.finished.connect(loop.quit, Qt.QueuedConnection)
        self._original_metadata_worker = worker
        try:
            worker.start()
            loop.exec()
            worker.wait()
            if worker.error is not None:
                raise worker.error
            return worker.result
        finally:
            self._original_metadata_worker = None
            worker.deleteLater()
            loop.deleteLater()

    def _metadata_inspect(self, path):
        from ..metadata_writer import ModelMetadataWriter
        writer = ModelMetadataWriter(self.engine.base_dir)
        if not writer.supports(path):
            raise ValueError('이 형식은 원본 모델명 기록이 지원되지 않거나 ExifTool을 찾을 수 없습니다.')
        self._job_timer.stop()
        self._set_busy(True)
        self._set_status('원본 메타정보 확인 중: ' + path.name)
        try:
            info = self._metadata_io(writer.inspect, path)
            return writer, info
        finally:
            self._set_busy(False)

    def _open_original_metadata(self):
        if not self._preview_change_allowed() or not self._selection_request_is_current():
            return
        item = self._original_metadata_selected_item()
        if item is None:
            return
        path = Path(item.source_path)
        try:
            writer, info = self._metadata_inspect(path)
        except Exception as exc:
            QMessageBox.warning(self, '원본 메타정보 확인 실패', str(exc))
            return
        models = [m.model_name for m in self.last_preview_bundle.media_items
                  if m.model_name and m.model_name != 'UNKNOWN' and '추론' not in m.model_source]
        dialog = OriginalModelDialog(self, item, info, models)
        if dialog.exec() == QDialog.Accepted:
            self._apply_original_metadata(writer, path, dialog.model_input.currentText().strip(),
                                          expected_fingerprint=info['fingerprint'])

    def _restore_original_metadata(self):
        if not self._preview_change_allowed() or not self._selection_request_is_current():
            return
        item = self._original_metadata_selected_item()
        if item is None:
            return
        path = Path(item.source_path)
        try:
            writer, info = self._metadata_inspect(path)
            if not info.get('backup_path'):
                raise ValueError('이 파일의 메타정보 수정 백업이 없습니다.')
        except Exception as exc:
            QMessageBox.warning(self, '원본 백업 확인', str(exc))
            return
        answer = QMessageBox.question(self, '원본 백업 복원',
                                      f'원본 파일을 변경 전 백업으로 복원합니다.\n{path}\n백업: {info["backup_path"]}',
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._apply_original_metadata(writer, path, restore=True, expected_fingerprint=info['fingerprint'])

    def _apply_original_metadata(self, writer, path, model=None, *, restore=False, expected_fingerprint=None):
        if not self._preview_change_allowed():
            return
        request = self._request_from_inputs(preview_only=True)
        self._job_timer.stop()
        self._set_busy(True)
        self._set_status(('원본 백업 복원 중: ' if restore else '원본 모델명 저장 중: ') + path.name)
        result = None
        try:
            # Publish a durable invalidation before any original bytes can change.
            # This safety checkpoint is required even when autosave is disabled.
            self._job_state.metadata_refresh_required = True
            self.last_preview_signature = None
            self._job_mark_changed()
            self._metadata_plan_checkpoint()
            options = {'expected_fingerprint': expected_fingerprint} if expected_fingerprint is not None else {}
            result = (self._metadata_io(writer.restore, path, **options) if restore else
                      self._metadata_io(writer.write_model, path, model, **options))
            self._set_status('원본 메타정보 재읽기·미리보기 갱신 중: ' + path.name)
            bundle = self._metadata_io(self.engine.refresh_preview_after_metadata,
                                       deepcopy(self.last_preview_bundle), request, str(path))
            self.last_preview_bundle = bundle
            self.last_preview_signature = self._request_signature(request)
            self._preview_metadata_bundle = None
            self._video_thumbnail_cache.clear()
            self._detail_metadata_cache.clear()
            self.model_selection_panel.set_items(bundle.preview_items, bundle.selected_models)
            self._fill_preview_table(bundle.preview_items)
            self._fill_error_table(bundle.error_items)
            for row, item in enumerate(bundle.preview_items):
                if item.source_path == str(path):
                    self.preview_table.selectRow(row)
                    break
            self._job_preview_completed()
            self._metadata_plan_checkpoint()
            self._set_status('원본 백업 복원 완료' if restore else '원본 모델명 수정 완료')
            self._update_selection_detail('preview')
            QMessageBox.information(self, '원본 메타정보',
                                    ('복원 완료' if restore else '모델명 기록 및 미리보기 갱신 완료') +
                                    '\n백업: ' + str(result.get('backup_path', '')))
        except Exception as exc:
            # A tool or journal exception may arrive after publication. Persist
            # invalidation even if no success result reached the caller.
            self.last_preview_signature = None
            self._preview_metadata_bundle = None
            self._detail_metadata_cache.clear()
            self._video_thumbnail_cache.clear()
            if self._job_state is not None:
                self._job_state.metadata_refresh_required = True
            self._job_mark_changed()
            if result is not None:
                message = f'원본 작업은 완료했지만 미리보기 갱신에 실패했습니다. 다시 미리보기해주세요.\n백업: {result.get("backup_path", "")}\n{exc}'
            else:
                message = f'{exc}\n현재 원본 상태 확인을 위해 다시 미리보기해주세요.'
            self._set_status('원본 메타정보 확인 필요')
            QMessageBox.warning(self, '원본 메타정보', message)
        finally:
            self._set_busy(False)

    def _metadata_plan_checkpoint(self):
        from ..job_store import save_job
        self._write_recent_job()
        if self._job_path is not None and Path(self._job_path) != self._recent_job_path():
            save_job(self._snapshot_job(), self._job_path)
