"""Execute only durable, verified stages of an immutable saved job."""
from __future__ import annotations

import os
import shutil
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
from threading import Event, RLock
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .execution_journal import ExecutionJournal
from .execution_lock import ExecutionLock
from .file_times import set_capture_file_times
from .job_validation import capture_file_states, _has_link_component, _unchanged
from .models import OrganizeRequest
from .resume_models import ensure_plan, initial_ledger, bundle_from_ledger
from .resume_validation import build_resume_plan


class JournalCommitError(RuntimeError):
    """Stop all subsequent media mutations after an uncertain journal write."""


class _JournalCoordinator:
    """Serialize durable records and final mutations, including fatal failures."""
    def __init__(self, journal):
        self.journal = journal
        self.lock = RLock()
        self.failure = None

    def update(self, job, item_id, stage, record):
        with self.lock:
            if self.failure is not None and record['state'] == 'IN_PROGRESS':
                raise JournalCommitError('저널 오류 이후 새 파일 변경을 시작할 수 없습니다.')
            try:
                self.journal.update(job, item_id, stage, record)
            except Exception as exc:
                self.failure = self.failure or exc
                raise

    @contextmanager
    def publication(self):
        with self.lock:
            if self.failure is not None:
                raise JournalCommitError('저널 오류 이후 최종 게시 또는 원본 제거를 중단합니다.')
            yield


def _request(job):
    names = {f.name for f in fields(OrganizeRequest)} - {'source_path', 'target_path', 'preview_only'}
    return OrganizeRequest(Path(job.settings.source_path), Path(job.settings.target_path),
                           preview_only=False, **{name: getattr(job.settings, name) for name in names})


def _fingerprint(path):
    return capture_file_states([path])[str(Path(path))]


def _record(state, attempt='', fingerprint=None, message='', temporary=''):
    return {'state': state, 'attempt_id': attempt, 'fingerprint': fingerprint or {},
            'message': message, 'temp_path': temporary}


def _with_encoder_report(message, item, stage, converter_called=False):
    if converter_called and stage == 'output' and item.media_type == 'video':
        from .video_output import get_last_video_encoder_report
        report = get_last_video_encoder_report()
        if report and report not in message:
            return '; '.join(part for part in (message, report) if part)
    return message


def _save(journal, job, item, stage, record, changed=False):
    try:
        journal.update(job, item.item_id, stage, record)
    except Exception as exc:
        if changed:
            uncertain = dict(record, state='UNCERTAIN', message='파일 변경 후 완료 기록 실패: ' + str(exc))
            try:
                journal.update(job, item.item_id, stage, uncertain)
            except Exception:
                # Preserve the last committed IN_PROGRESS prefix. It is already
                # non-retryable; inventing an uncommitted state would break restore.
                pass
        raise JournalCommitError('실행 기록을 저장하지 못했습니다. 다음 파일 변경을 중단합니다.') from exc


def _publish(staged, target, overwrite=False):
    """Windows rename never replaces NEW; other platforms use exclusive link."""
    if overwrite:
        os.replace(staged, target)
    elif os.name == 'nt':
        os.rename(staged, target)
    else:
        os.link(staged, target)
        staged.unlink()


def _assert_regular(path):
    if _has_link_component(path) or not path.is_file():
        raise ValueError(f'일반 파일을 확인할 수 없습니다: {path}')


def _assert_baseline(path, baselines):
    _assert_regular(path)
    if not _unchanged(str(path), baselines):
        raise ValueError(f'파일이 변경되었거나 확인 기록이 없습니다: {path}')


def _cleanup_owned(temporary, created):
    if created and temporary is not None:
        # ffmpeg's inner temporary filename inherits this unique attempt token.
        paths = (temporary, temporary.with_name(temporary.stem + '.tmp' + temporary.suffix))
        for path in paths:
            if not _has_link_component(path):
                path.unlink(missing_ok=True)


def _run_stage(engine, journal, job, item, stage, request, mode):
    from .engine import MobileOutputSizeExcluded
    attempt = str(uuid4())
    target = Path(item.target_path if stage == 'main' else item.mobile_output_path) if stage != 'source_remove' else Path(item.source_path)
    staging_parent = target.parent.parent if stage == 'output' else target.parent
    temporary = (staging_parent / f'.photoorganizer_{job.execution_id}_{attempt}{target.suffix}') if stage != 'source_remove' else None
    temporary_created = False
    converter_called = False
    publish_started = False
    changed = False
    existing = _fingerprint(target)
    overwrite = mode == 'initial' and not item.filename_edited and item.write_mode == 'OVERWRITE'
    _save(journal, job, item, stage, _record('IN_PROGRESS', attempt, temporary=str(temporary or '')))
    try:
        if stage == 'source_remove':
            source = Path(item.source_path)
            _assert_baseline(source, job.source_fingerprints)
            main = job.ledger[item.item_id]['main']
            _assert_baseline(Path(item.target_path), {item.target_path: main['fingerprint']})
            if job.ledger[item.item_id]['output']['state'] == 'DONE':
                _assert_baseline(Path(item.mobile_output_path), {item.mobile_output_path: job.ledger[item.item_id]['output']['fingerprint']})
            with journal.publication():
                # Another worker may have held the gate while an external writer
                # changed these files. Recheck after waiting, immediately before unlink.
                _assert_baseline(source, job.source_fingerprints)
                _assert_baseline(Path(item.target_path), {item.target_path: main['fingerprint']})
                if job.ledger[item.item_id]['output']['state'] == 'DONE':
                    _assert_baseline(Path(item.mobile_output_path), {item.mobile_output_path: job.ledger[item.item_id]['output']['fingerprint']})
                publish_started = True
                source.unlink()
                changed = True
                _save(journal, job, item, stage, _record('DONE', attempt, _fingerprint(source)), changed=True)
            return True
        if _has_link_component(target):
            raise ValueError(f'연결 경로는 처리할 수 없습니다: {target}')
        staging_parent.mkdir(parents=True, exist_ok=True)
        if stage == 'main':
            source = Path(item.source_path)
            _assert_baseline(source, job.source_fingerprints)
            with source.open('rb') as reader, temporary.open('xb') as writer:
                temporary_created = True
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            shutil.copystat(source, temporary)
            _assert_baseline(source, job.source_fingerprints)
            if temporary.stat().st_size != job.source_fingerprints[str(source)]['size']:
                raise OSError('임시 정리 파일의 크기가 원본과 다릅니다.')
        else:
            source = Path(item.target_path)
            _assert_baseline(source, {item.target_path: job.ledger[item.item_id]['main']['fingerprint']})
            # The unique path is recorded before conversion; no prior attempt is reused.
            if temporary.exists() or temporary.with_name(temporary.stem + '.tmp' + temporary.suffix).exists():
                raise FileExistsError('이 시도의 임시 파일 경로가 이미 존재합니다.')
            temporary_created = True
            try:
                if item.media_type == 'video':
                    from .video_output import clear_video_encoder_report
                    clear_video_encoder_report()
                converter_called = True
                status = engine._create_mobile_output(source, temporary, item.media_type, request)
            except MobileOutputSizeExcluded as exc:
                _cleanup_owned(temporary, temporary_created)
                _save(journal, job, item, stage, _record('SIZE_EXCLUDED', attempt, message=_with_encoder_report(str(exc), item, stage, converter_called)))
                return True
            if status == 'SKIPPED':
                _cleanup_owned(temporary, temporary_created)
                _save(journal, job, item, stage, _record('SKIPPED', attempt, message=_with_encoder_report('출력 생성 정책에 따라 제외', item, stage, converter_called)))
                return True
            if status != 'SUCCESS':
                raise OSError('알 수 없는 모바일 출력 결과입니다: ' + str(status))
            _assert_regular(temporary)
            set_capture_file_times(temporary, datetime.fromisoformat(item.captured_at))
            with temporary.open('r+b') as handle:
                os.fsync(handle.fileno())
            _assert_baseline(source, {item.target_path: job.ledger[item.item_id]['main']['fingerprint']})
        _assert_regular(temporary)
        _assert_baseline(source, job.source_fingerprints if stage == 'main' else
                         {item.target_path: job.ledger[item.item_id]['main']['fingerprint']})
        if _has_link_component(target):
            raise ValueError(f'연결 경로는 게시할 수 없습니다: {target}')
        if overwrite:
            if _fingerprint(target) != existing:
                raise FileExistsError('게시 전 기존 대상 파일이 변경되었습니다.')
        elif target.exists():
            raise FileExistsError('최종 대상 파일이 이미 존재합니다.')
        # A second durable intent marks the exact non-atomic publication boundary.
        with journal.publication():
            _save(journal, job, item, stage, _record('IN_PROGRESS', attempt, _fingerprint(temporary),
                                                   message='최종 파일 게시 시작', temporary=str(temporary)))
            target.parent.mkdir(parents=True, exist_ok=True)
            _assert_baseline(source, job.source_fingerprints if stage == 'main' else
                             {item.target_path: job.ledger[item.item_id]['main']['fingerprint']})
            if _has_link_component(target):
                raise ValueError(f'최종 게시 경로에 연결 경로가 생겼습니다: {target}')
            if overwrite and _fingerprint(target) != existing:
                raise FileExistsError('최종 게시 직전 기존 대상 파일이 변경되었습니다.')
            if not overwrite and target.exists():
                raise FileExistsError('최종 게시 직전 대상 파일이 생성되었습니다.')
            publish_started = True
            _publish(temporary, target, overwrite)
            changed = True
            _assert_regular(target)
            message = _with_encoder_report('', item, stage, converter_called)
            _save(journal, job, item, stage, _record('DONE', attempt, _fingerprint(target), message), changed=True)
        return True
    except JournalCommitError:
        if temporary_created and not publish_started:
            try:
                _cleanup_owned(temporary, temporary_created)
                _save(journal, job, item, stage, _record('FAILED', attempt, message='저널 오류로 최종 게시 전에 중단'))
            except (OSError, JournalCommitError):
                pass
        raise
    except Exception as exc:
        state = 'UNCERTAIN' if publish_started else 'FAILED'
        if not publish_started:
            try:
                _cleanup_owned(temporary, temporary_created)
            except OSError:
                state = 'UNCERTAIN'
        _save(journal, job, item, stage, _record(state, attempt, message=_with_encoder_report(str(exc), item, stage, converter_called), temporary=str(temporary or '')), changed=changed)
        return False


def _run_item(engine, journal, job, item, request, mode, control, halt_new):
    # No submitted-but-not-started task may begin after pause, stop or fatal failure.
    with journal.lock:
        if halt_new.is_set() or (control is not None and (control.pause_requested or control.stop_requested)):
            return False, False
        if journal.failure is not None:
            raise JournalCommitError('저널 오류 이후 새 파일 처리를 중단합니다.')
    with (control.file_activity(item.item_id, item.source_path, 'copy') if control is not None else nullcontext()):
        for stage in ('main', 'output', 'source_remove'):
            with journal.lock:
                current_mode = mode if job.ledger[item.item_id][stage]['state'] == 'FAILED' else ('initial' if mode == 'initial' else 'continue')
                actions = build_resume_plan(job, current_mode, items=[item])
                action = next((a for a in actions if a.item_id == item.item_id and a.stage == stage), None)
                if action is None or not action.allowed or action.action != 'RUN':
                    if (mode == 'initial' and action is not None and action.action == 'BLOCK'
                            and job.ledger[item.item_id][stage]['state'] == 'PENDING'):
                        _save(journal, job, item, stage, _record('FAILED', str(uuid4()), message=action.reason))
                        if stage == 'output':
                            halt_new.set()
                        return True, stage == 'output'
                    continue
            if control is not None:
                control.update_file_activity(item.item_id, {'main': 'copy', 'output': 'output', 'source_remove': 'source_remove'}[stage])
            if not _run_stage(engine, journal, job, item, stage, request, mode):
                if stage == 'output':
                    halt_new.set()
                return True, stage == 'output'
        return True, False


def _assert_unique_destinations(items):
    destinations = set()
    for item in items:
        for value in (item.target_path, item.mobile_output_path):
            if not value:
                continue
            key = str(Path(value)).casefold()
            if key in destinations:
                raise ValueError('처리 항목 사이에 같은 최종 파일 경로가 있습니다. 미리보기를 다시 확인해주세요.')
            destinations.add(key)


def execute_job(engine, job, mode='initial', progress_callback=None, control=None):
    if mode not in {'initial', 'continue', 'retry'}:
        raise ValueError('지원하지 않는 복구 모드입니다.')
    with ExecutionLock():
        journal = ExecutionJournal(engine.base_dir)
        if mode == 'initial':
            ensure_plan(job)
            if not job.ledger:
                job.ledger = initial_ledger(job)
            journal.register(job)
            # Mandatory fallback for non-UI callers; failure precedes media changes.
            from .job_store import save_job
            save_job(job, Path(engine.base_dir) / 'sessions' / 'last_session.pojob.json')
        elif not journal.restore(job):
            raise ValueError('이 실행의 로컬 저널을 찾을 수 없어 복구 실행할 수 없습니다.')
        plan = build_resume_plan(job, mode)
        selected = {action.item_id for action in plan if action.allowed and action.action == 'RUN'}
        request = _request(job)
        engine._validate_mobile_output_limit(request)
        items = [p for p in job.preview_bundle.preview_items if p.included and (mode == 'initial' or p.item_id in selected)]
        _assert_unique_destinations([p for p in job.preview_bundle.preview_items if p.included])
        if items and mode != 'initial':
            # A restored result remains historical display data while new stages
            # run. Persist the new attempt boundary before the first mutation.
            job.phase = 'EXECUTING'
            from .job_store import save_job
            save_job(job, Path(engine.base_dir) / 'sessions' / 'last_session.pojob.json')
        journal = _JournalCoordinator(journal)
        workers = getattr(request, 'photo_workers', 1)
        if workers not in {1, 2, 4}:
            raise ValueError('사진 동시 처리 수는 1, 2, 4 중 하나여야 합니다.')
        remaining, completed = deque(items), 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='PhotoOrganizerPhoto') as pool:
            while remaining:
                if control is not None and not control.checkpoint():
                    break
                batch = [remaining.popleft()]
                if batch[0].media_type == 'photo':
                    while remaining and len(batch) < workers and remaining[0].media_type == 'photo':
                        batch.append(remaining.popleft())
                halt_new = Event()
                skipped, output_failed, fatal = [], False, None
                futures = {pool.submit(_run_item, engine, journal, job, item, request, mode, control, halt_new): item for item in batch}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        started, failed = future.result()
                    except BaseException as exc:
                        halt_new.set()
                        fatal = fatal or exc
                        if control is not None:
                            control.report_file_result(item.item_id, item.source_path, 'UNCERTAIN', str(exc))
                        continue
                    if not started:
                        skipped.append(item)
                    else:
                        completed += 1
                        output_failed = output_failed or failed
                        if control is not None:
                            records = tuple(job.ledger[item.item_id].values())
                            states = {record['state'] for record in records}
                            status = ('UNCERTAIN' if states & {'UNCERTAIN', 'IN_PROGRESS'} else
                                      'ERROR' if 'FAILED' in states else
                                      'INCOMPLETE' if 'PENDING' in states else 'SUCCESS')
                            message = '; '.join(record.get('message', '') for record in records
                                                if record.get('message') and record['state'] not in {'DONE', 'NOT_APPLICABLE'})
                            control.report_file_result(item.item_id, item.source_path, status, message)
                        # Progress is emitted only by the coordinator, never a photo worker.
                        engine._report_progress(progress_callback, '복구 단계 실행 중', completed, len(items))
                if fatal is not None:
                    raise fatal
                # Keep unstarted submissions in their original planned order after pause.
                skipped_ids = {item.item_id for item in skipped}
                for item in reversed(batch):
                    if item.item_id in skipped_ids:
                        remaining.appendleft(item)
                if output_failed:
                    break
        result = bundle_from_ledger(job)
        # Logging errors must not reclassify already durable media successes.
        try:
            engine.logger.write_session_log(result.log_events)
        except OSError:
            pass
        return result
