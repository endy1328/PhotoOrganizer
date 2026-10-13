"""Primitive execution records and immutable plans, independent of Qt and SQLite."""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from .models import AppSettings, ExecutionBundle, ExecutionResult, ErrorItem, DeleteReviewItem, LogEvent

STAGES = ('main', 'output', 'source_remove')
STATES = {'PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', 'UNCERTAIN', 'NOT_REQUIRED', 'SKIPPED', 'SIZE_EXCLUDED'}
OUTPUT_TERMINAL = {'DONE', 'NOT_REQUIRED', 'SKIPPED', 'SIZE_EXCLUDED'}
RECORD_FIELDS = {'state', 'attempt_id', 'fingerprint', 'message', 'temp_path'}
LEGACY_NAMESPACE = UUID('c353c69b-8316-4a4e-94c5-0d9daaa1ea37')
NON_PROCESSING = {'restore_last_job', 'autosave_job_changes', 'phone_conflict_policy',
                  'phone_video_limit_enabled', 'phone_video_limit_mb'}
PLAN_ITEM_FIELDS = ('item_id', 'source_path', 'target_directory', 'target_path', 'new_filename',
                    'write_mode', 'captured_at', 'media_type', 'model_name', 'output_model_name',
                    'folder_model_name', 'included', 'filename_edited', 'mobile_output_enabled', 'mobile_output_path')


def stage_record(state='PENDING', *, attempt_id='', fingerprint=None, message='', temp_path=''):
    return {'state': state, 'attempt_id': attempt_id or (str(uuid4()) if state not in {'PENDING', 'NOT_REQUIRED'} else ''),
            'fingerprint': dict(fingerprint or {}), 'message': message, 'temp_path': str(temp_path)}


def processing_settings(settings):
    """One projection for signatures and journal checks, including old jobs."""
    excluded = set(NON_PROCESSING)
    if not settings.mixed_media_workers:
        excluded.add('mixed_media_workers')
    if settings.video_workers == 1:
        excluded.add('video_workers')
    if (settings.video_encoder, settings.conversion_speed, settings.photo_workers) == ('cpu', 'balanced', 1):
        excluded.update({'video_encoder', 'conversion_speed', 'photo_workers'})
    return {f.name: getattr(settings, f.name) for f in fields(AppSettings) if f.name not in excluded}


def plan_manifest(job):
    manifest = {'settings': processing_settings(job.settings),
            'items': [{name: getattr(item, name, '') for name in PLAN_ITEM_FIELDS} for item in
                      (job.preview_bundle.preview_items if job.preview_bundle else [])],
            'source_fingerprints': job.source_fingerprints}
    # Preserve byte-for-byte old signatures until an individual choice differs
    # from the old default. Then freeze both filter layers, even hidden choices.
    bundle = job.preview_bundle
    if bundle is not None and any(not item.file_selected for item in bundle.preview_items):
        manifest['file_selection'] = {
            'selected_models': sorted(bundle.selected_models) if bundle.selected_models is not None else
                               sorted({item.model_name for item in bundle.preview_items if item.included}),
            'files': {item.item_id: item.file_selected for item in bundle.preview_items},
        }
    return manifest


def canonical_plan(job):
    return json.dumps(plan_manifest(job), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def ensure_plan(job, *, legacy=False, force=False, allow_stale_for_storage=False):
    # This persisted display state is intentionally outside the immutable media
    # plan signature. Only snapshot storage may preserve such a blocked plan.
    if getattr(job, 'metadata_refresh_required', False):
        if job.execution_started or not allow_stale_for_storage:
            raise ValueError('원본 메타정보 변경 후 새 미리보기가 필요합니다. 실행할 수 없습니다.')
    if not job.preview_bundle:
        return
    canonical = canonical_plan(job)
    signature = hashlib.sha256(canonical.encode('utf-8')).hexdigest()  # Plan identity, never media hashing.
    if job.execution_started:
        if job.plan_signature and job.plan_signature != signature:
            raise ValueError('실행을 시작한 작업의 처리 계획을 변경할 수 없습니다.')
        return
    if force or not job.plan_id or job.plan_signature != signature:
        job.plan_id = str(uuid5(LEGACY_NAMESPACE, canonical)) if legacy else str(uuid4())
        job.plan_signature = signature
        job.execution_id = ''
        job.checkpoint = 0
        job.ledger = {}


def initial_ledger(job):
    return {item.item_id: {'main': stage_record(),
                          'output': stage_record('PENDING' if item.mobile_output_enabled else 'NOT_REQUIRED'),
                          'source_remove': stage_record('PENDING' if job.settings.operation_mode == 'move' else 'NOT_REQUIRED')}
            for item in job.preview_bundle.preview_items if item.included}


def validate_ledger(job):
    if type(job.ledger) is not dict:
        raise ValueError('단계 기록 형식이 올바르지 않습니다.')
    if not job.ledger:
        if job.execution_id:
            raise ValueError('실행 ID에 단계 기록이 없습니다.')
        return
    if job.preview_bundle is None:
        raise ValueError('미리보기 없이 단계 기록을 사용할 수 없습니다.')
    items = {item.item_id: item for item in job.preview_bundle.preview_items if item.included}
    if set(job.ledger) != set(items):
        raise ValueError('단계 기록과 포함 항목이 다릅니다.')
    for item_id, records in job.ledger.items():
        if type(records) is not dict or set(records) != set(STAGES):
            raise ValueError('단계 기록이 누락되었거나 알 수 없는 단계입니다.')
        item = items[item_id]
        for stage, record in records.items():
            if type(record) is not dict or set(record) != RECORD_FIELDS:
                raise ValueError('단계 기록 필드가 올바르지 않습니다.')
            state = record['state']
            if type(state) is not str or state not in STATES:
                raise ValueError('알 수 없는 단계 상태입니다.')
            for key in ('attempt_id', 'message', 'temp_path'):
                if type(record[key]) is not str or '\x00' in record[key]:
                    raise ValueError('단계 기록 문자열이 올바르지 않습니다.')
            if state not in {'PENDING', 'NOT_REQUIRED'} and not record['attempt_id']:
                raise ValueError('실행 단계에 시도 ID가 없습니다.')
            if record['attempt_id']:
                UUID(record['attempt_id'])
            fp = record['fingerprint']
            if type(fp) is not dict or set(fp) - {'exists', 'is_file', 'size', 'mtime_ns'}:
                raise ValueError('단계 파일 기준값이 올바르지 않습니다.')
            if fp and (set(fp) != {'exists', 'is_file', 'size', 'mtime_ns'} or
                       any(type(fp[k]) is not bool for k in ('exists', 'is_file')) or
                       any(fp[k] is not None and (type(fp[k]) is not int or fp[k] < 0) for k in ('size', 'mtime_ns'))):
                raise ValueError('단계 파일 기준값 형식이 올바르지 않습니다.')
            if state == 'DONE' and (not fp or (stage != 'source_remove' and not (fp['exists'] and fp['is_file'] and
                                    type(fp['size']) is int and type(fp['mtime_ns']) is int)) or
                                    (stage == 'source_remove' and fp['exists'])):
                raise ValueError('완료된 단계의 파일 확인 기준값이 없습니다.')
            if stage != 'output' and state in {'SKIPPED', 'SIZE_EXCLUDED'}:
                raise ValueError('출력 정책 상태를 다른 단계에 사용할 수 없습니다.')
            if stage == 'main' and state == 'NOT_REQUIRED':
                raise ValueError('일반 정리 단계는 필수입니다.')
            if stage == 'output' and (state == 'NOT_REQUIRED') != (not item.mobile_output_enabled):
                raise ValueError('출력 설정과 단계 기록이 다릅니다.')
            if stage == 'source_remove' and (state == 'NOT_REQUIRED') != (job.settings.operation_mode == 'copy'):
                raise ValueError('처리 모드와 원본 제거 단계가 다릅니다.')
            if record['temp_path']:
                temporary = Path(record['temp_path'])
                if (not temporary.is_absolute() or '..' in temporary.parts or
                    not temporary.is_relative_to(Path(job.settings.target_path)) or not temporary.name.startswith('.photoorganizer_')):
                    raise ValueError('단계 임시 경로가 처리 범위를 벗어났습니다.')
        if records['output']['state'] in OUTPUT_TERMINAL - {'NOT_REQUIRED'} and records['main']['state'] != 'DONE':
            raise ValueError('일반 정리 완료 없이 출력이 완료되었습니다.')
        if records['source_remove']['state'] == 'DONE' and (records['main']['state'] != 'DONE' or records['output']['state'] not in OUTPUT_TERMINAL):
            raise ValueError('일반 정리·출력 완료 없이 원본이 제거되었습니다.')


def bundle_from_ledger(job):
    """Rebuild current results from evidence, keeping baseline timestamps frozen."""
    results, reviews, errors, fingerprints = [], [], [], {}
    for item in job.preview_bundle.preview_items:
        if not item.included or item.item_id not in job.ledger:
            continue
        records = job.ledger[item.item_id]
        main, output, removal = (records[stage] for stage in STAGES)
        if main['state'] == 'DONE':
            fingerprints[item.target_path] = dict(main['fingerprint'])
        if output['state'] == 'DONE':
            fingerprints[item.mobile_output_path] = dict(output['fingerprint'])
        successful = main['state'] == 'DONE' and output['state'] in OUTPUT_TERMINAL and removal['state'] in {'DONE', 'NOT_REQUIRED'}
        trouble = [f'{stage}: {record["message"] or record["state"]}' for stage, record in records.items()
                   if record['state'] in {'FAILED', 'UNCERTAIN', 'IN_PROGRESS'}]
        if not successful and not trouble:
            continue
        status = 'SUCCESS' if successful else 'ERROR'
        message = '; '.join(trouble) if trouble else '단계별 처리 완료'
        output_status = {'DONE': 'SUCCESS', 'FAILED': 'ERROR', 'UNCERTAIN': 'ERROR', 'IN_PROGRESS': 'ERROR',
                         'SKIPPED': 'SKIPPED', 'SIZE_EXCLUDED': 'SIZE_EXCLUDED'}.get(output['state'], '')
        results.append(ExecutionResult(source_path=item.source_path, target_path=item.target_path, status=status,
                                       action=job.settings.operation_mode, write_mode=item.write_mode, message=message,
                                       mobile_output_path=item.mobile_output_path, mobile_output_status=output_status,
                                       mobile_output_message=output['message']))
        if successful and job.settings.operation_mode == 'copy':
            reviews.append(DeleteReviewItem(item_id=item.item_id, delete_path=item.source_path, reason='복사 완료 후 원본 정리 후보', selected=False))
        if trouble:
            errors.append(ErrorItem(item.source_path, message, item.media_type))
    logs = [LogEvent('INFO' if r.status == 'SUCCESS' else 'ERROR',
                    r.message + (f'; {r.mobile_output_message}' if r.mobile_output_message else ''),
                    r.source_path, r.target_path) for r in results]
    bundle = ExecutionBundle(preview_items=job.preview_bundle.preview_items, execution_results=results,
                             error_items=list(job.preview_bundle.error_items) + errors, delete_review_items=reviews, log_events=logs)
    job.result_fingerprints = fingerprints
    job.execution_bundle = bundle
    if job.execution_started:
        included = sum(item.included for item in job.preview_bundle.preview_items)
        job.phase = 'EXECUTION_FINISHED' if len(results) == included else 'EXECUTION_PARTIAL'
    return bundle
