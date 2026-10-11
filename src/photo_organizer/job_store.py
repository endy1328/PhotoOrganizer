"""Bounded, explicitly validated job snapshots; no media operations on load."""
from __future__ import annotations

import json
import os
import tempfile
import copy
import hashlib
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from . import __version__
from .model_mapping import validate_model_mappings
from .models import (AppSettings, DeleteReviewItem, ErrorItem, ExecutionBundle,
                     ExecutionResult, LogEvent, MediaItem, PreviewBundle, PreviewItem)
from .video_output import VIDEO_QUALITY_PRESETS

MAX_JOB_BYTES = 128 * 1024 * 1024
MAX_PREVIEW_ITEMS = 100000
PHASES = {'DRAFT', 'PREVIEW_READY', 'EXECUTING', 'EXECUTION_FINISHED', 'EXECUTION_PARTIAL'}
GLOBAL_SETTINGS = {'restore_last_job', 'autosave_job_changes'}


@dataclass(slots=True)
class JobState:
    job_id: str = field(default_factory=lambda: str(uuid4()))
    revision: int = 0
    phase: str = 'DRAFT'
    settings: AppSettings = field(default_factory=AppSettings)
    preview_bundle: PreviewBundle | None = None
    execution_bundle: ExecutionBundle | None = None
    active_tab: int = 0
    source_fingerprints: dict[str, dict] = field(default_factory=dict)
    result_fingerprints: dict[str, dict] = field(default_factory=dict)
    execution_started: bool = False
    saved_at_utc: str = ''
    app_version: str = __version__
    schema_version: int = 2
    plan_id: str = ''
    plan_signature: str = ''
    execution_id: str = ''
    checkpoint: int = 0
    ledger: dict = field(default_factory=dict)
    legacy_unverified: bool = False


def _fail(message: str) -> None:
    raise ValueError(f'작업 파일이 올바르지 않습니다: {message}')


def _object(value: Any, name: str) -> dict:
    if type(value) is not dict or any(type(k) is not str for k in value):
        _fail(name)
    return value


def _string(value: Any, name: str) -> str:
    if type(value) is not str or '\x00' in value:
        _fail(name)
    return value


def _list(value: Any, name: str) -> list:
    if type(value) is not list or len(value) > MAX_PREVIEW_ITEMS:
        _fail(name)
    return value


def _record(cls, value):
    data = _object(value, cls.__name__)
    known = {f.name: f for f in fields(cls)}
    if set(data) - set(known):
        _fail(f'{cls.__name__} 알 수 없는 필드')
    kwargs = {}
    for name, f in known.items():
        if name not in data:
            if f.default is MISSING and f.default_factory is MISSING:
                _fail(f'{cls.__name__}.{name} 누락')
            continue
        v = data[name]
        if name == 'metadata_entries':
            pairs = _list(v, name)
            if any(type(pair) not in (list, tuple) or len(pair) != 2 for pair in pairs):
                _fail(name)
            v = [(_string(pair[0], name), _string(pair[1], name)) for pair in pairs]
        elif name == 'warnings':
            v = [_string(x, name) for x in _list(v, name)]
        elif name in {'selected', 'included', 'filename_edited', 'mobile_output_enabled'}:
            if type(v) is not bool:
                _fail(name)
        else:
            v = _string(v, name)
        kwargs[name] = v
    obj = cls(**kwargs)
    if isinstance(obj, PreviewItem):
        if obj.media_type not in {'photo', 'video'} or obj.write_mode not in {'NEW', 'OVERWRITE', 'CONFLICT'} or obj.status not in {'READY', 'ERROR', 'EXCLUDED', 'SUCCESS', 'CONFLICT'}:
            _fail('미리보기 enum')
        if not obj.item_id:
            _fail('item_id')
    if isinstance(obj, ExecutionResult):
        if obj.status not in {'SUCCESS', 'ERROR', 'SKIPPED'} or obj.action not in {'copy', 'move', 'delete', 'COPY', 'MOVE', 'DELETE'} or obj.write_mode not in {'NEW', 'OVERWRITE', 'CONFLICT', 'DELETE'}:
            _fail('실행 결과 enum')
        if obj.mobile_output_status not in {'', 'SUCCESS', 'ERROR', 'SKIPPED', 'SIZE_EXCLUDED'}:
            _fail('출력 결과 enum')
    if isinstance(obj, DeleteReviewItem):
        obj.selected = False
    if isinstance(obj, LogEvent) and obj.level not in {'INFO', 'WARNING', 'ERROR', 'DEBUG', 'CRITICAL'}:
        _fail('로그 수준')
    return obj


def _settings(value):
    data = _object(value, 'settings')
    required = {'source_path', 'target_path', 'operation_mode'}
    if not required <= set(data):
        _fail('필수 작업 설정 누락')
    default = AppSettings()
    known = {f.name for f in fields(default)}
    if set(data) - known - GLOBAL_SETTINGS:
        _fail('알 수 없는 작업 설정')
    kwargs = {'video_encoder': 'cpu', 'conversion_speed': 'balanced', 'photo_workers': 1}
    for name, v in data.items():
        if name in GLOBAL_SETTINGS:
            continue
        expected = getattr(default, name)
        if type(v) is not type(expected):
            _fail(f'설정 {name} 타입')
        if type(v) is str:
            _string(v, name)
        kwargs[name] = v
    obj = AppSettings(**kwargs)
    if obj.video_encoder not in {'auto', 'cpu', 'gpu'} or obj.conversion_speed not in {'quality', 'balanced', 'fast'} or obj.photo_workers not in {1, 2, 4}:
        _fail('성능 설정 값')
    if obj.operation_mode not in {'copy', 'move'} or obj.phone_conflict_policy not in {'overwrite', 'skip', 'rename'} or obj.mobile_output_video_quality not in VIDEO_QUALITY_PRESETS or obj.model_mapping_scope not in {'filename_and_folders', 'filename_only'}:
        _fail('작업 설정 enum')
    bounds = {'mobile_output_max_width': (1, 100000), 'mobile_output_video_max_width': (0, 100000), 'mobile_output_jpeg_quality': (1, 100), 'video_model_window_minutes': (0, 1440), 'phone_video_limit_mb': (1, 1000000), 'mobile_output_limit_mb': (1, 1000000)}
    for name, (minimum, maximum) in bounds.items():
        if not minimum <= getattr(obj, name) <= maximum:
            _fail(f'설정 {name} 범위')
    obj.model_name_mappings = validate_model_mappings(obj.model_name_mappings)
    return obj


def _media(value):
    data = _object(value, 'media item')
    required = {'source_path', 'media_type', 'extension'}
    if not required <= set(data) or set(data) - {f.name for f in fields(MediaItem)}:
        _fail('media item 필드')
    if data.get('metadata', {}) != {}:
        _fail('raw metadata 저장 금지')
    kwargs = dict(data)
    kwargs['source_path'] = Path(_string(data['source_path'], 'source_path'))
    for name in ('media_type', 'extension', 'datetime_source', 'model_source'):
        if name in kwargs:
            kwargs[name] = _string(kwargs[name], name)
    if kwargs['media_type'] not in {'photo', 'video'}:
        _fail('media type')
    if kwargs.get('model_name') is not None:
        _string(kwargs['model_name'], 'model_name')
    if kwargs.get('captured_at') is not None:
        try:
            kwargs['captured_at'] = datetime.fromisoformat(_string(kwargs['captured_at'], 'captured_at'))
        except (ValueError, TypeError):
            _fail('captured_at')
    kwargs['warnings'] = [_string(x, 'warnings') for x in _list(kwargs.get('warnings', []), 'warnings')]
    kwargs['metadata'] = {}
    return MediaItem(**kwargs)


def _bundle(value, execution=False):
    if value is None:
        return None
    data = _object(value, 'bundle')
    cls = ExecutionBundle if execution else PreviewBundle
    if set(data) - {f.name for f in fields(cls)} or 'preview_items' not in data:
        _fail('bundle 필드')
    mappings = {'preview_items': PreviewItem, 'error_items': ErrorItem, 'log_events': LogEvent, 'execution_results': ExecutionResult, 'delete_review_items': DeleteReviewItem}
    kwargs = {}
    for name, v in data.items():
        if name in mappings:
            kwargs[name] = [_record(mappings[name], row) for row in _list(v, name)]
        elif name == 'media_items':
            kwargs[name] = [_media(row) for row in _list(v, name)]
        elif name == 'selection_applied':
            if type(v) is not bool:
                _fail(name)
            kwargs[name] = v
        elif name == 'model_name_mappings':
            kwargs[name] = validate_model_mappings(v)
        elif name == 'model_mapping_scope':
            if v not in {'filename_and_folders', 'filename_only'}:
                _fail(name)
            kwargs[name] = v
    bundle = cls(**kwargs)
    ids = [p.item_id for p in bundle.preview_items]
    if len(ids) != len(set(ids)):
        _fail('중복 item_id')
    return bundle


def _fingerprints(value, name):
    data = _object(value, name)
    if len(data) > MAX_PREVIEW_ITEMS * 2:
        _fail(name)
    for path, fp in data.items():
        _string(path, name)
        fp = _object(fp, name)
        for key, v in fp.items():
            if key in {'exists', 'is_file'}:
                if type(v) is not bool:
                    _fail(name)
            elif key in {'size', 'mtime_ns'}:
                if v is not None and (type(v) is not int or v < 0):
                    _fail(name)
            elif key == 'error':
                _string(v, name)
            else:
                _fail(f'{name} 알 수 없는 필드 {key}')
    return data


def _decode(value):
    data = _object(value, 'job')
    required = {'format', 'schema_version', 'app_version', 'job_id', 'revision', 'saved_at_utc', 'phase', 'settings', 'preview_bundle', 'execution_bundle', 'execution_started'}
    if not required <= set(data) or set(data) - ({f.name for f in fields(JobState)} | {'format', 'schema_version'}):
        _fail('작업 필드')
    schema = data['schema_version']
    if data['format'] != 'PhotoOrganizerJob' or type(schema) is not int or schema not in (1, 2):
        _fail('지원하지 않는 작업 형식/스키마')
    if schema == 1 and set(data) & {'plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'}:
        _fail('스키마1에 스키마2 실행 필드가 있습니다.')
    if schema == 2:
        if not {'plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'} <= set(data):
            _fail('스키마2 필수 실행 필드 누락')
        if type(data['checkpoint']) is not int or data['checkpoint'] < 0 or type(data['legacy_unverified']) is not bool:
            _fail('checkpoint/legacy_unverified')
        for name in ('plan_id', 'execution_id'):
            identity = _string(data[name], name)
            if identity:
                try:
                    UUID(identity)
                except ValueError:
                    _fail(name)
        _string(data['plan_signature'], 'plan_signature')
        _object(data['ledger'], 'ledger')
    try:
        UUID(_string(data['job_id'], 'job_id'))
    except (ValueError, AttributeError):
        _fail('job_id')
    if type(data['revision']) is not int or data['revision'] < 0 or type(data['execution_started']) is not bool:
        _fail('revision/execution_started')
    if type(data.get('active_tab', 0)) is not int or not 0 <= data.get('active_tab', 0) <= 3:
        _fail('active_tab')
    if type(data['phase']) is not str or data['phase'] not in PHASES:
        _fail('phase')
    job = JobState(job_id=data['job_id'], revision=data['revision'], phase=data['phase'], settings=_settings(data['settings']), preview_bundle=_bundle(data['preview_bundle']), execution_bundle=_bundle(data['execution_bundle'], True), active_tab=data.get('active_tab', 0), execution_started=data['execution_started'], saved_at_utc=_string(data['saved_at_utc'], 'saved_at_utc'), app_version=_string(data['app_version'], 'app_version'), source_fingerprints=_fingerprints(data.get('source_fingerprints', {}), 'source_fingerprints'), result_fingerprints=_fingerprints(data.get('result_fingerprints', {}), 'result_fingerprints'))
    if schema == 2:
        for name in ('plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'):
            setattr(job, name, data[name])
        if job.checkpoint and (not job.execution_id or not job.execution_started):
            _fail('실행 ID 없이 실행 체크포인트가 있습니다.')
        if job.execution_id and (not job.execution_started or not job.plan_id or not job.plan_signature):
            _fail('실행 식별자와 단계 기록이 모순됩니다.')
        if job.execution_started and not job.execution_id and not job.legacy_unverified:
            _fail('실행한 작업에 단계별 실행 근거 또는 기존 미검증 표시가 없습니다.')
        if job.legacy_unverified and (not job.execution_started or job.ledger or job.execution_id or job.checkpoint):
            _fail('기존 미검증 실행에 새 실행 근거가 있습니다.')
        if not job.execution_started and job.ledger:
            for stages in job.ledger.values():
                if type(stages) is not dict or any(type(record) is not dict or record.get('state') not in {'PENDING', 'NOT_REQUIRED'} for record in stages.values()):
                    _fail('실행 시작 없이 처리된 단계 기록이 있습니다.')
    if job.saved_at_utc:
        try:
            stamp = datetime.fromisoformat(job.saved_at_utc)
            if stamp.tzinfo is None:
                _fail('saved_at_utc 시간대 누락')
        except ValueError:
            _fail('saved_at_utc')
    if job.phase == 'DRAFT':
        if (job.preview_bundle is not None or job.execution_bundle is not None or job.execution_started
                or job.ledger or job.plan_id or job.plan_signature or job.execution_id or job.checkpoint or job.legacy_unverified):
            _fail('DRAFT 단계 모순')
    elif job.phase == 'PREVIEW_READY':
        if job.preview_bundle is None or job.execution_bundle is not None or job.execution_started:
            _fail('미리보기 단계 모순')
    else:
        if job.preview_bundle is None or not job.execution_started:
            _fail('실행 단계 모순')
        if job.phase != 'EXECUTING' and job.execution_bundle is None:
            _fail('실행 결과 누락')
        if schema == 1 and job.phase == 'EXECUTING' and job.execution_bundle is not None:
            _fail('실행 중 결과 모순')
        if job.execution_bundle is not None:
            if job.execution_bundle.preview_items != job.preview_bundle.preview_items:
                _fail('실행 결과 미리보기 모순')
            included = {p.source_path for p in job.preview_bundle.preview_items if p.included}
            result_paths = [r.source_path for r in job.execution_bundle.execution_results]
            if len(set(result_paths)) != len(result_paths) or not set(result_paths) <= included:
                _fail('실행 결과 대상 모순')
            complete = included == set(result_paths)
            if job.phase != 'EXECUTING' and (job.phase == 'EXECUTION_FINISHED') != complete:
                _fail('실행 완료 단계 모순')
    _validate_paths(job)
    from .resume_models import ensure_plan, validate_ledger, canonical_plan, bundle_from_ledger
    if schema == 1:
        if job.execution_started:
            job.legacy_unverified = True
        elif job.phase == 'PREVIEW_READY':
            ensure_plan(job, legacy=True)
    else:
        if bool(job.plan_id) != bool(job.plan_signature):
            _fail('계획 식별자와 서명이 모순됩니다.')
        if job.plan_signature:
            expected_signature = hashlib.sha256(canonical_plan(job).encode('utf-8')).hexdigest()
            if job.plan_signature != expected_signature:
                _fail('작업 계획 서명이 저장된 계획과 다릅니다.')
        if job.phase == 'PREVIEW_READY' and not job.plan_id:
            _fail('미리보기의 계획 식별자가 없습니다.')
        validate_ledger(job)
        if job.execution_id and job.phase in {'EXECUTION_FINISHED', 'EXECUTION_PARTIAL'}:
            reconstructed = copy.copy(job)
            expected_bundle = bundle_from_ledger(reconstructed)
            if (reconstructed.phase != job.phase or expected_bundle.execution_results != job.execution_bundle.execution_results
                    or reconstructed.result_fingerprints != job.result_fingerprints):
                _fail('실행 결과 또는 완료 파일 기준값이 단계 기록과 다릅니다.')
            expected_reviews = {(r.item_id, r.delete_path, r.reason) for r in expected_bundle.delete_review_items}
            actual_reviews = {(r.item_id, r.delete_path, r.reason) for r in job.execution_bundle.delete_review_items}
            if expected_reviews != actual_reviews:
                _fail('삭제 후보가 단계별 완료 기록과 다릅니다.')
    return job


def _validate_paths(job):
    from .job_validation import validate_job_paths
    validate_job_paths(job)


def _encode(job):
    def primitive(value):
        if isinstance(value, MediaItem):
            return {f.name: primitive(getattr(value, f.name)) for f in fields(value) if f.name != 'metadata'}
        if is_dataclass(value):
            return {f.name: primitive(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if type(value) in (list, tuple):
            return [primitive(x) for x in value]
        if type(value) is dict:
            return {k: primitive(v) for k, v in value.items()}
        return value
    data = primitive(job)
    data['settings'] = {k: v for k, v in data['settings'].items() if k not in GLOBAL_SETTINGS}
    data.update(format='PhotoOrganizerJob', schema_version=2)
    return data


def save_job(job: JobState, path: Path) -> None:
    """Only a successful atomic replacement updates revision and save time."""
    path = Path(path)
    if job.preview_bundle is not None and not job.execution_started:
        from .resume_models import ensure_plan
        ensure_plan(job)
    data = _encode(job)
    if job.execution_started and not job.execution_id and not job.ledger and job.checkpoint == 0:
        # Existing in-memory results from the pre-journal engine may be exported,
        # but cannot acquire new execution evidence merely by being saved.
        data['legacy_unverified'] = True
    data['revision'] = job.revision + 1
    data['saved_at_utc'] = datetime.now(timezone.utc).isoformat()
    # Use the same validator for saving and opening untrusted snapshots.
    _decode(data)
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    if len(content) > MAX_JOB_BYTES:
        _fail('파일 크기 제한 초과')
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.pojob-', suffix='.tmp', delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    job.revision = data['revision']
    job.saved_at_utc = data['saved_at_utc']
    job.legacy_unverified = data['legacy_unverified']


def load_job(path: Path) -> JobState:
    with Path(path).open('rb') as handle:
        content = handle.read(MAX_JOB_BYTES + 1)
    if len(content) > MAX_JOB_BYTES:
        _fail('파일 크기 제한 초과')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail('중복 JSON 키')
            result[key] = value
        return result
    try:
        data = json.loads(content.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=lambda _: _fail('비표준 JSON 숫자'))
        return _decode(data)
    except (UnicodeError, json.JSONDecodeError, RecursionError, TypeError) as exc:
        raise ValueError('작업 파일을 읽을 수 없습니다.') from exc
