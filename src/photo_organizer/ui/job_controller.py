"""Qt job lifecycle; serialization and file checks live outside the UI."""
from __future__ import annotations

from copy import copy, deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QDialog

from ..job_store import JobState, load_job, save_job
from ..job_validation import capture_file_states, validate_preview_files, validate_delete_candidate


PHASE_LABELS = {
    'DRAFT': '새 작업', 'PREVIEW_READY': '미리보기 완료',
    'EXECUTING': '실행 완료 여부 미확인', 'EXECUTION_FINISHED': '실행 완료',
    'EXECUTION_PARTIAL': '일부 처리 / 결과 없는 항목 있음',
}


class JobControllerMixin:
    def _init_job_controller(self):
        self._global_settings = deepcopy(self.settings)
        self._job_state = None
        self._job_path = None
        self._job_dirty = False
        self._job_loaded = False
        self._job_restoring = False
        self._journal_available = False
        self._journal_block_reason = ''
        self._job_timer = QTimer(self)
        self._job_timer.setSingleShot(True)
        self._job_timer.setInterval(500)
        self._job_timer.timeout.connect(lambda: self._autosave_job())

    def _build_job_controls(self, layout):
        row = QHBoxLayout()
        for attribute, label, callback in (
            ('job_new_button', '새 작업', self._new_job),
            ('job_open_button', '작업 열기', self._choose_open_job),
            ('job_save_button', '작업 저장', self._save_job),
            ('job_save_as_button', '다른 이름으로 저장', lambda: self._save_job(save_as=True)),
        ):
            button = QPushButton(label)
            setattr(self, attribute, button)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.job_status_label = QLabel('새 작업')
        row.addWidget(self.job_status_label, 1)
        layout.addLayout(row)

    def _job_started(self):
        return bool(self._job_state and self._job_state.execution_started)

    def _job_update_label(self):
        name = self._job_path.name if self._job_path else '이름 없는 작업'
        phase = self._job_state.phase if self._job_state else 'DRAFT'
        uncertain = any(record['state'] in {'IN_PROGRESS', 'UNCERTAIN'}
                        for stages in getattr(self._job_state, 'ledger', {}).values() for record in stages.values())
        phase_label = '확인 필요 단계 있음' if uncertain else PHASE_LABELS[phase]
        self.job_status_label.setText(f'{name} — {phase_label}' + (' *' if self._job_dirty else '')
                                      + (' / ' + self._journal_block_reason if self._journal_block_reason else ''))

    def _job_controls_busy(self, busy):
        for name in ('job_new_button', 'job_open_button', 'job_save_button', 'job_save_as_button'):
            getattr(self, name).setEnabled(not busy)
        started = self._job_started()
        self.preview_button.setEnabled(not busy and not started)
        self.execute_button.setEnabled(not busy and not started)
        self.model_selection_panel.setEnabled(not busy and not started and self.last_execution_bundle is None and bool(self.last_preview_bundle))
        self._update_resume_buttons(busy)

    def _job_mark_changed(self):
        if self._job_restoring or self._job_state is None:
            return
        self._job_dirty = True
        self._job_update_label()
        if self._global_settings.autosave_job_changes and not self._busy:
            self._job_timer.start()

    def _snapshot_job(self):
        if self._job_state is None:
            self._job_state = JobState()
        self._job_state.settings = deepcopy(self._current_settings())
        self._job_state.preview_bundle = self.last_preview_bundle
        self._job_state.execution_bundle = self.last_execution_bundle
        self._job_state.active_tab = self.tabs.currentIndex()
        return self._job_state

    def _recent_job_path(self):
        base = self.engine.base_dir
        if not isinstance(base, Path):
            raise OSError('작업 복구 저장 경로를 확인할 수 없습니다.')
        return base / 'sessions' / 'last_session.pojob.json'

    def _write_recent_job(self):
        path = self._recent_job_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_job(self._snapshot_job(), path)

    def _autosave_job(self):
        if self._busy or self._operation_active or self._job_restoring or self._job_state is None:
            return
        try:
            if self._job_started():
                self._refresh_journal()
            self._write_recent_job()
        except (ValueError, OSError) as exc:
            self.job_status_label.setText(self.job_status_label.text() + f' / 자동 복구 저장 실패: {exc}')

    def _job_preview_completed(self):
        previous = self._job_state
        self._job_state = JobState(phase='PREVIEW_READY', settings=deepcopy(self._current_settings()),
                                  preview_bundle=self.last_preview_bundle)
        if previous is not None:
            self._job_state.job_id = previous.job_id
            self._job_state.revision = previous.revision
        self._job_state.source_fingerprints = capture_file_states(
            [item.source_path for item in self.last_preview_bundle.preview_items])
        from ..resume_models import ensure_plan
        ensure_plan(self._job_state, force=True)
        self._journal_available = False
        self._journal_block_reason = ''
        self._job_mark_changed()
        if self._global_settings.autosave_job_changes:
            self._autosave_job()

    def _job_execution_checkpoint(self):
        self._job_timer.stop()
        old = copy(self._job_state)
        registered = False
        if self._job_state is None:
            self._job_preview_completed()
        try:
            from ..engine import OrganizerEngine
            if isinstance(self.engine, OrganizerEngine):
                from ..resume_models import ensure_plan, initial_ledger
                from ..execution_journal import ExecutionJournal
                ensure_plan(self._snapshot_job())
                if not self._job_state.ledger:
                    self._job_state.ledger = initial_ledger(self._job_state)
                self._job_state.execution_id = self._job_state.execution_id or str(uuid4())
                ExecutionJournal(self.engine.base_dir).register(self._job_state)
                registered = True
                self._journal_available = True
            else:
                self._job_state.phase = 'EXECUTING'
                self._job_state.execution_started = True
            self._write_recent_job()
        except (ValueError, OSError) as exc:
            if not registered:
                self._job_state = old
            else:
                self._job_dirty = True
            self._job_update_label()
            self._set_busy(False)
            QMessageBox.warning(self, '실행 시작 불가', f'실행 시작 기록을 저장하지 못했습니다. 파일 처리를 시작하지 않습니다.\n{exc}')
            return False
        self._job_dirty = True
        self._job_update_label()
        return True

    def _job_execution_completed(self):
        job = self._snapshot_job()
        if getattr(job, 'ledger', None) and getattr(job, 'execution_id', ''):
            from ..resume_models import bundle_from_ledger
            self.last_execution_bundle = bundle_from_ledger(job)
            self._job_dirty = True
            self._job_update_label()
            try:
                self._write_recent_job()
            except (ValueError, OSError) as exc:
                self.job_status_label.setText(self.job_status_label.text() + f' / 실행 결과 복구 저장 실패: {exc}')
            return
        result_sources = {item.source_path for item in self.last_execution_bundle.execution_results}
        missing = [item for item in self.last_preview_bundle.preview_items
                   if item.included and item.source_path not in result_sources]
        job.phase = 'EXECUTION_PARTIAL' if missing else 'EXECUTION_FINISHED'
        paths = []
        for result in self.last_execution_bundle.execution_results:
            if result.target_path:
                paths.append(result.target_path)
            if result.mobile_output_path:
                paths.append(result.mobile_output_path)
        job.result_fingerprints = capture_file_states(paths)
        self._job_dirty = True
        self._job_update_label()
        try:
            self._write_recent_job()
        except (ValueError, OSError) as exc:
            self.job_status_label.setText(self.job_status_label.text() + f' / 실행 결과 복구 저장 실패: {exc}')

    def _confirm_job_transition(self):
        if not self._job_dirty:
            return True
        answer = QMessageBox.question(self, '작업 저장', '현재 작업에 저장하지 않은 변경이 있습니다. 저장할까요?',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                      QMessageBox.Save)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self._save_job()
        return answer == QMessageBox.Discard

    def _save_job(self, checked=False, *, save_as=False):
        if self._busy or self._operation_active:
            return False
        self.job_save_button.setFocus()
        path = self._job_path
        if path is None or save_as:
            filename, _ = QFileDialog.getSaveFileName(self, '작업 저장', str(path or Path.cwd() / '새 작업.pojob.json'),
                                                      'PhotoOrganizer 작업 (*.pojob.json)')
            if not filename:
                return False
            path = Path(filename)
            if not path.name.lower().endswith('.pojob.json'):
                path = path.with_name(path.name + '.pojob.json')
        old = copy(self._job_state)
        try:
            if self._job_started():
                self._refresh_journal()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '작업 저장 실패', str(exc))
            return False
        job = self._snapshot_job()
        if save_as:
            job.job_id = str(uuid4())
            job.revision = 0
        try:
            save_job(job, path)
        except (ValueError, OSError) as exc:
            self._job_state = old
            QMessageBox.warning(self, '작업 저장 실패', str(exc))
            return False
        self._job_path = path
        self._job_dirty = False
        self._job_loaded = True
        self._job_update_label()
        return True

    def _choose_open_job(self):
        if self._busy or not self._confirm_job_transition():
            return
        filename, _ = QFileDialog.getOpenFileName(self, '작업 열기', str(Path.cwd()), 'PhotoOrganizer 작업 (*.pojob.json)')
        if filename:
            self._open_job_path(Path(filename))

    def _open_job_path(self, path, *, recent=False):
        if self._busy:
            return False
        try:
            job = load_job(path)
            saved_progress = (job.execution_id, job.checkpoint, job.phase)
            journal_available = self._reconcile_job(job)
            progress_updated = saved_progress != (job.execution_id, job.checkpoint, job.phase)
            issues = validate_preview_files(job) if job.phase == 'PREVIEW_READY' else []
        except (OSError, ValueError) as exc:
            if recent:
                self._set_status(f'최근 작업 복원 실패: {exc}')
            else:
                QMessageBox.warning(self, '작업 열기 실패', str(exc))
            return False
        self._job_timer.stop()
        self._job_restoring = True
        try:
            job.settings.restore_last_job = self._global_settings.restore_last_job
            job.settings.autosave_job_changes = self._global_settings.autosave_job_changes
            self.settings = deepcopy(job.settings)
            self._job_state = job
            self._journal_available = journal_available
            self._journal_block_reason = ('실행 저널이 없는 작업은 조회 전용입니다.' if job.execution_started and not journal_available else '')
            self._job_path = None if recent else path
            self._job_loaded = True
            self._job_dirty = recent or progress_updated
            self.last_preview_bundle = job.preview_bundle
            self._preview_detail_column = 0
            self.last_execution_bundle = job.execution_bundle
            self._load_settings()
            self.last_preview_signature = self._request_signature(self._request_from_inputs(preview_only=True)) if job.preview_bundle else None
            self._video_thumbnail_cache.clear()
            self._detail_metadata_cache.clear()
            preview = job.preview_bundle
            execution = job.execution_bundle
            items = preview.preview_items if preview else []
            self.model_selection_panel.set_items(items)
            self.model_selection_panel.refresh(items)
            self._fill_preview_table(items)
            self._fill_results_table(execution.execution_results if execution else [])
            self._fill_error_table(execution.error_items if execution else preview.error_items if preview else [])
            self.current_delete_candidates = execution.delete_review_items if execution else []
            for item in self.current_delete_candidates:
                item.selected = False
            self._fill_delete_table(self.current_delete_candidates)
            self.tabs.setCurrentIndex(job.active_tab)
            self._job_update_label()
            self._set_busy(False)
            self._set_status('이전 작업 복원 — ' + PHASE_LABELS[job.phase] + (f' / 재검증 문제 {len(issues)}건: ' + '; '.join(map(str, issues[:3])) if issues else ''))
            self._job_show_current_results()
            self._update_selection_detail('preview' if job.active_tab == 0 else 'results')
        finally:
            self._job_restoring = False
        return True

    def _job_show_current_results(self):
        job = self._job_state
        if not job or not job.execution_started:
            return
        current = capture_file_states(job.result_fingerprints)
        changed = 0
        missing = 0
        for path, baseline in job.result_fingerprints.items():
            actual = current[path]
            if baseline.get('exists') and not actual.get('exists'):
                missing += 1
            elif actual != baseline:
                changed += 1
        self._set_status(self.status_label.text() + f' / 현재 결과 파일: 누락 {missing}건, 변경 {changed}건 (과거 실행 결과와 별도)')
        if job.execution_bundle:
            for row, result in enumerate(job.execution_bundle.execution_results):
                for column, path in ((4, result.target_path), (6, result.mobile_output_path)):
                    cell = self.results_table.item(row, column)
                    if cell is None or not path:
                        continue
                    baseline = job.result_fingerprints.get(path)
                    actual = current.get(path)
                    state = ('기준값 없음' if baseline is None else '없음' if not actual.get('exists')
                             else '실행 완료 시점과 동일' if baseline == actual else '변경됨')
                    cell.setToolTip(path + '\n현재 파일 상태: ' + state + '\n표의 성공·오류는 과거 실행 기록입니다.')

    def _reconcile_job(self, job):
        from ..engine import OrganizerEngine
        if not isinstance(self.engine, OrganizerEngine) or job.preview_bundle is None:
            return False
        if getattr(job, 'legacy_unverified', False):
            return False
        from ..resume_models import ensure_plan, bundle_from_ledger
        from ..execution_journal import ExecutionJournal
        ensure_plan(job, legacy=getattr(job, 'schema_version', 2) == 1)
        found = ExecutionJournal(self.engine.base_dir).restore(job)
        if found and job.execution_started:
            bundle_from_ledger(job)
        return found

    def _refresh_journal(self):
        if self._operation_active:
            return False
        if self._job_state is None:
            return False
        saved_progress = (self._job_state.execution_id, self._job_state.checkpoint, self._job_state.phase)
        available = self._reconcile_job(self._job_state)
        self._journal_available = available
        if available:
            if saved_progress != (self._job_state.execution_id, self._job_state.checkpoint, self._job_state.phase):
                self._job_dirty = True
            self.last_preview_bundle = self._job_state.preview_bundle
            self.last_execution_bundle = self._job_state.execution_bundle
        return available

    def _update_resume_buttons(self, busy=False):
        job = self._job_state
        for mode, name in (('continue', 'resume_button'), ('retry', 'retry_button')):
            button = getattr(self, name, None)
            if button is None:
                continue
            eligible = bool(not busy and job and job.execution_started and self._journal_available
                            and not getattr(job, 'legacy_unverified', False))
            if eligible:
                try:
                    from ..resume_validation import build_resume_plan
                    eligible = any(action.action == 'RUN' and action.allowed for action in build_resume_plan(job, mode))
                except (ValueError, OSError):
                    eligible = False
            button.setEnabled(eligible)

    def _recovered_counts(self):
        counts = {'성공': 0, '오류': 0, '미처리': 0, '확인 필요': 0}
        job = self._job_state
        for stages in getattr(job, 'ledger', {}).values():
            states = [record['state'] for record in stages.values()]
            label = ('확인 필요' if any(state in {'IN_PROGRESS', 'UNCERTAIN'} for state in states)
                     else '오류' if 'FAILED' in states else '미처리' if 'PENDING' in states else '성공')
            counts[label] += 1
        return ' / '.join(f'{label} {count}건' for label, count in counts.items())

    def _display_recovered_results(self):
        job = self._job_state
        bundle = job.execution_bundle
        if bundle is None:
            return
        self.last_preview_bundle = job.preview_bundle
        self.last_execution_bundle = bundle
        self.model_selection_panel.refresh(bundle.preview_items)
        self._fill_preview_table(bundle.preview_items)
        self._fill_results_table(bundle.execution_results)
        self._fill_error_table(bundle.error_items)
        self.current_delete_candidates = bundle.delete_review_items
        for item in self.current_delete_candidates:
            item.selected = False
        self._fill_delete_table(self.current_delete_candidates)
        self._job_update_label()
        self._set_status(self._recovered_counts())
        self._set_idle_progress(self._recovered_counts())
        self._job_show_current_results()

    def _handle_resume(self, mode):
        if self._busy or not self._job_started():
            return
        try:
            if not self._refresh_journal():
                self._journal_block_reason = '실행 저널이 없는 작업은 조회 전용입니다.'
                self._job_update_label()
                self._update_resume_buttons()
                QMessageBox.information(self, '작업 조회 전용', self._journal_block_reason)
                return
            self._display_recovered_results()
            from ..resume_validation import build_resume_plan
            from .resume_dialog import ResumePlanDialog
            actions = build_resume_plan(self._job_state, mode)
            dialog = ResumePlanDialog(self, actions, mode=mode)
            if dialog.exec() != QDialog.Accepted:
                return
            if not any(action.action == 'RUN' and action.allowed for action in actions):
                return
            self._job_timer.stop()
            self._job_state.phase = 'EXECUTING'
            self._write_recent_job()
        except (ValueError, OSError) as exc:
            self._journal_available = False
            self._update_resume_buttons()
            QMessageBox.warning(self, '복구 계획 확인 실패', str(exc))
            return
        self._set_busy(True)
        try:
            self.last_execution_bundle = self._run_engine_operation(self.engine.resume, self._job_state, mode=mode)
            self._job_state.execution_bundle = self.last_execution_bundle
            self._job_execution_completed()
            self._display_recovered_results()
            if self._operation_stopped:
                self._set_status('사용자 요청으로 중단 — ' + self._recovered_counts())
                self._set_idle_progress('사용자 요청으로 중단 — ' + self._recovered_counts())
        except Exception as exc:
            try:
                self._refresh_journal()
                self._display_recovered_results()
            except (ValueError, OSError):
                self._journal_available = False
            self._show_operation_error('복구 실행 중단 — 완료 기록을 확인해주세요', exc)
        finally:
            self._set_busy(False)
            self._update_selection_detail('results')

    def _restore_recent_job(self):
        if not self._global_settings.restore_last_job or not isinstance(self.engine.base_dir, Path):
            return
        path = self._recent_job_path()
        if path.is_file():
            self._open_job_path(path, recent=True)

    def _new_job(self):
        if self._busy or not self._confirm_job_transition():
            return
        self._job_timer.stop()
        self._job_restoring = True
        try:
            source, target = self.source_edit.text(), self.target_edit.text()
            self.settings = deepcopy(self._global_settings)
            self.settings.source_path, self.settings.target_path = source, target
            self._job_state = JobState(settings=deepcopy(self.settings))
            self._journal_available = False
            self._journal_block_reason = ''
            self._job_path = None
            self._job_loaded = True
            self._job_dirty = False
            self.last_preview_bundle = self.last_execution_bundle = None
            self._preview_detail_column = 0
            self.last_preview_signature = None
            self.current_delete_candidates = []
            self._load_settings()
            self.model_selection_panel.set_items([])
            for table in (self.preview_table, self.results_table, self.error_table, self.delete_table):
                table.setRowCount(0)
            self._video_thumbnail_cache.clear()
            self._detail_metadata_cache.clear()
            self.tabs.setCurrentIndex(0)
            self._job_update_label()
            self._set_busy(False)
            self._set_status('새 작업 — 미리보기를 실행해주세요.')
        finally:
            self._job_restoring = False
        self._job_mark_changed()

    def _job_validate_before_execute(self, request):
        if self._job_state and self.last_preview_bundle and not self._job_started():
            try:
                self._refresh_journal()
                if self._job_started():
                    self._display_recovered_results()
                    self._job_controls_busy(False)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, '실행 저널 확인 실패', str(exc))
                return False
        if self._job_started():
            QMessageBox.information(self, '실행 완료 작업', '실행을 시작한 작업은 다시 실행할 수 없습니다. 새 작업에서 미리보기를 만들어주세요.')
            return False
        if self._job_loaded and self.last_preview_bundle is not None:
            if self.last_preview_signature != self._request_signature(request):
                QMessageBox.warning(self, '미리보기 필요', '저장된 작업의 설정이 변경되었습니다. 미리보기를 다시 만들어주세요.')
                return False
            issues = validate_preview_files(self._snapshot_job())
            if issues:
                QMessageBox.warning(self, '작업 재검증 실패', '\n'.join(map(str, issues[:20])) + '\n미리보기를 다시 만들어주세요.')
                return False
        return True

    def _job_validate_delete(self, chosen):
        if self._job_state is None:
            return True
        problems = [problem for item in chosen for problem in validate_delete_candidate(self._job_state, item)]
        if problems:
            QMessageBox.warning(self, '삭제 재검증 실패', '\n'.join(map(str, problems[:20])))
            return False
        return True
