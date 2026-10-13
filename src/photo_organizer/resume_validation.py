"""Build a read-only stage plan; existence alone never establishes completion."""
from dataclasses import dataclass
from copy import copy
from pathlib import Path

from .job_validation import capture_file_states, validate_job_paths, _has_link_component, _unchanged
from .resume_models import STAGES, OUTPUT_TERMINAL, validate_ledger


@dataclass(frozen=True, slots=True)
class ResumeAction:
    item_id: str
    stage: str
    action: str
    reason: str
    allowed: bool = False


def build_resume_plan(job, mode='continue', *, items=None):
    if mode not in {'initial', 'continue', 'retry'}:
        raise ValueError('지원하지 않는 복구 방식입니다.')
    if getattr(job, 'metadata_refresh_required', False):
        raise ValueError('원본 메타정보 변경 후 새 미리보기가 필요합니다. 실행할 수 없습니다.')
    if items is not None:
        # The engine validates the complete immutable plan once under its execution lock.
        # Recheck just the current item's paths and three stage records before each mutation.
        narrowed = copy(job)
        narrowed.preview_bundle = copy(job.preview_bundle)
        narrowed.preview_bundle.preview_items = list(items)
        narrowed.preview_bundle.media_items = []
        narrowed.preview_bundle.error_items = []
        narrowed.execution_bundle = None
        narrowed.ledger = {item.item_id: job.ledger[item.item_id] for item in items}
        job = narrowed
    validate_job_paths(job)
    validate_ledger(job)
    actions = []
    for item in job.preview_bundle.preview_items:
        if not item.included:
            continue
        records = job.ledger.get(item.item_id)
        if not records or job.legacy_unverified:
            actions.extend(ResumeAction(item.item_id, stage, 'BLOCK', '재개에 필요한 단계 기록이 없습니다.') for stage in STAGES)
            continue
        predecessors_ok = True
        predecessors_can_finish = True
        for stage in STAGES:
            record = records[stage]
            state = record['state']
            path = item.target_path if stage == 'main' else item.mobile_output_path if stage == 'output' else item.source_path
            reason = ''
            terminal = state == 'DONE' or state == 'NOT_REQUIRED' or (stage == 'output' and state in {'SKIPPED', 'SIZE_EXCLUDED'})
            if not predecessors_can_finish:
                reason = '선행 단계가 완료되지 않았거나 현재 파일 확인이 필요합니다.'
            elif state in {'IN_PROGRESS', 'UNCERTAIN'}:
                reason = '완료 여부를 확인할 수 없습니다. 기존 파일을 보존합니다.'
            else:
                try:
                    if path and _has_link_component(Path(path)):
                        reason = '연결 경로 또는 재분석 지점은 처리할 수 없습니다.'
                    elif state == 'DONE':
                        if stage == 'source_remove':
                            if Path(path).exists():
                                reason = '제거 완료한 원본 경로에 파일이 다시 존재합니다.'
                        elif not _unchanged(path, {str(Path(path)): record['fingerprint']}):
                            reason = '완료한 파일이 변경·누락되었습니다. 자동 재생성하지 않습니다.'
                    elif not terminal:
                        if stage == 'main':
                            if item.write_mode == 'CONFLICT':
                                reason = '미리보기에서 파일명 충돌이 확인되었습니다.'
                            elif not _unchanged(item.source_path, job.source_fingerprints):
                                reason = '원본이 변경·누락되었거나 확인 기준값이 없습니다.'
                            elif Path(path).exists() and not (mode == 'initial' and item.write_mode == 'OVERWRITE' and not item.filename_edited):
                                reason = '대상 파일이 이미 존재합니다. 복구에서 덮어쓰지 않습니다.'
                        elif stage == 'output':
                            if Path(path).exists() and not (mode == 'initial' and item.write_mode == 'OVERWRITE' and not item.filename_edited):
                                reason = 'output 파일이 이미 존재합니다. 복구에서 덮어쓰지 않습니다.'
                        elif not _unchanged(path, job.source_fingerprints):
                            reason = '원본이 변경·누락되었습니다. 자동 제거하지 않습니다.'
                except OSError as exc:
                    reason = f'파일 상태 확인 실패: {exc}'
            if reason:
                actions.append(ResumeAction(item.item_id, stage, 'BLOCK', reason))
                predecessors_ok = False
                predecessors_can_finish = False
            elif terminal:
                actions.append(ResumeAction(item.item_id, stage, 'KEEP', '완료 유지' if state == 'DONE' else '정책에 따른 정상 종료'))
            else:
                eligible = state == ('FAILED' if mode == 'retry' else 'PENDING')
                if not predecessors_ok and state == 'PENDING':
                    actions.append(ResumeAction(item.item_id, stage, 'WAIT', '선행 단계 완료 후 실행'))
                elif eligible and predecessors_ok:
                    actions.append(ResumeAction(item.item_id, stage, 'RUN',
                                                '실패 단계 재시도' if state == 'FAILED' else '미처리 단계 실행', True))
                else:
                    actions.append(ResumeAction(item.item_id, stage, 'BLOCK',
                                                '실패 항목 재시도가 필요합니다.' if state == 'FAILED' else '미처리 항목 계속 실행이 필요합니다.'))
                    predecessors_can_finish = False
                predecessors_ok = False
    return actions
