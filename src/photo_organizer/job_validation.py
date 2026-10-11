"""Read-only checks for saved jobs; timestamps detect changes, never capture dates."""
from __future__ import annotations

import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

from .fallback import sanitize_model_name
from .model_mapping import resolve_output_model_name, normalize_model_mapping_scope, validate_model_mappings, model_mapping_signature
from .models import VIDEO_EXTENSIONS, SUPPORTED_EXTENSIONS


def _path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or path == Path(path.anchor):
        raise ValueError(f'절대 경로 또는 파일 경로가 올바르지 않습니다: {value}')
    if any(':' in part or re.search(r'[<>"|?*\x00-\x1f]', part) or part.endswith((' ', '.'))
           for part in path.parts[1:]):
        raise ValueError(f'사용할 수 없는 경로입니다: {value}')
    return path


def _key(path: str | Path) -> str:
    return str(Path(path)).casefold()


def _under(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _filename(name: str, extension: str) -> None:
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'{p}{d}' for p in ('COM', 'LPT') for d in '123456789¹²³')}
    if (not name or name in {'.', '..'} or name.endswith((' ', '.'))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or len(name.encode('utf-16-le')) // 2 > 255
            or name.split('.', 1)[0].rstrip(' .').upper() in reserved
            or Path(name).suffix.casefold() != extension.casefold()):
        raise ValueError(f'저장된 새 파일명이 올바르지 않습니다: {name}')


def _has_link_component(path: Path) -> bool:
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
            return True
    return False


def capture_file_states(paths: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    states = {}
    for value in paths:
        path = Path(value)
        state = {'exists': False, 'size': None, 'mtime_ns': None, 'is_file': False}
        try:
            if not _has_link_component(path):
                info = path.lstat()
                state = {'exists': True, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                         'is_file': stat.S_ISREG(info.st_mode)}
        except OSError:
            pass
        states[str(path)] = state
    return states


def _previews(job):
    bundle = getattr(job, 'preview_bundle', None)
    if bundle is not None:
        return bundle.preview_items
    execution = getattr(job, 'execution_bundle', None)
    return execution.preview_items if execution is not None else []


def validate_job_paths(job) -> None:
    """Check loaded path relationships lexically; do not touch media files."""
    settings = job.settings
    items = _previews(job)
    phase = getattr(job, 'phase', 'DRAFT')
    if getattr(phase, 'value', phase) == 'DRAFT' and not items and not getattr(job, 'execution_bundle', None):
        return
    source_root, target_root = _path(settings.source_path), _path(settings.target_path)
    if source_root == target_root:
        raise ValueError('Source와 Target 경로가 같습니다.')
    mappings = validate_model_mappings(settings.model_name_mappings)
    scope = normalize_model_mapping_scope(settings.model_mapping_scope)
    ids, sources = set(), set()
    by_source = {}
    for item in items:
        source, target, directory = _path(item.source_path), _path(item.target_path), _path(item.target_directory)
        if not item.item_id or item.item_id in ids or _key(source) in sources:
            raise ValueError('중복된 작업 항목입니다.')
        ids.add(item.item_id)
        sources.add(_key(source))
        by_source[_key(source)] = item
        if not _under(source, source_root) or source == target_root or _under(source, target_root):
            raise ValueError(f'Source 범위를 벗어난 파일입니다: {source}')
        extension = source.suffix.casefold()
        if extension not in SUPPORTED_EXTENSIONS or item.media_type != ('video' if extension in VIDEO_EXTENSIONS else 'photo'):
            raise ValueError('원본 파일 형식이 올바르지 않습니다.')
        captured = datetime.fromisoformat(item.captured_at)
        raw = sanitize_model_name(item.model_name)
        output = resolve_output_model_name(raw, mappings)
        folder = output if scope == 'filename_and_folders' else raw
        expected = target_root / f'{captured:%Y}년' / f'{captured:%Y}년 {captured:%m}월' / f'{captured:%Y%m%d}' / f'{captured:%Y%m%d}_{folder}'
        if directory != expected or target != directory / item.new_filename:
            raise ValueError('저장된 분류 폴더 또는 대상 경로가 작업 설정과 다릅니다.')
        if item.output_model_name and item.output_model_name != output or item.folder_model_name and item.folder_model_name != folder:
            raise ValueError('저장된 모델명 매핑 결과가 설정과 다릅니다.')
        _filename(item.new_filename, source.suffix)
        if item.mobile_output_enabled:
            suffix = Path(item.new_filename).suffix
            mobile_name = (Path(item.new_filename).stem + '.mp4' if extension in VIDEO_EXTENSIONS else
                           Path(item.new_filename).stem + ('.JPG' if suffix[1:].isupper() else '.jpg') if extension == '.heic' else item.new_filename)
            expected_mobile = directory / f'output_{directory.name}' / mobile_name
            if _path(item.mobile_output_path) != expected_mobile:
                raise ValueError('저장된 모바일 출력 경로가 올바르지 않습니다.')
        elif item.mobile_output_path:
            raise ValueError('비활성 모바일 출력에 경로가 있습니다.')
    bundle = getattr(job, 'preview_bundle', None)
    if bundle:
        if model_mapping_signature(bundle.model_name_mappings, bundle.model_mapping_scope) != model_mapping_signature(mappings, scope):
            raise ValueError('저장된 미리보기와 작업의 모델명 매핑 설정이 다릅니다.')
        media_sources = set()
        for media in bundle.media_items:
            source = _path(media.source_path)
            if not _under(source, source_root) or source == target_root or _under(source, target_root):
                raise ValueError('저장된 메타데이터 원본 경로가 Source 범위를 벗어났습니다.')
            if _key(source) in media_sources:
                raise ValueError('중복된 메타데이터 원본입니다.')
            media_sources.add(_key(source))
            preview = by_source.get(_key(source))
            if preview and (media.extension.casefold() != source.suffix.casefold() or media.media_type != preview.media_type
                            or media.captured_at != datetime.fromisoformat(preview.captured_at)):
                raise ValueError('미리보기와 메타데이터 파일 정보가 다릅니다.')
        for error in bundle.error_items:
            source = _path(error.source_path)
            if not _under(source, source_root) or source == target_root or _under(source, target_root):
                raise ValueError('오류 파일의 원본 경로가 Source 범위를 벗어났습니다.')
    execution = getattr(job, 'execution_bundle', None)
    if execution:
        result_sources = set()
        for result in execution.execution_results:
            if _key(result.source_path) in result_sources:
                raise ValueError('중복된 실행 결과입니다.')
            result_sources.add(_key(result.source_path))
            item = by_source.get(_key(result.source_path))
            if item is None or _path(result.target_path) != Path(item.target_path):
                raise ValueError('실행 결과 경로가 미리보기와 다릅니다.')
            if result.mobile_output_path and result.mobile_output_path != item.mobile_output_path:
                raise ValueError('실행 결과 모바일 경로가 미리보기와 다릅니다.')
        for review in execution.delete_review_items:
            item = by_source.get(_key(review.delete_path))
            if item is None or review.item_id != item.item_id:
                raise ValueError('삭제 후보가 미리보기 원본과 다릅니다.')


def _unchanged(path: str, baselines: dict) -> bool:
    baseline = baselines.get(str(Path(path)))
    current = capture_file_states([path])[str(Path(path))]
    return bool(baseline and baseline.get('exists') and baseline.get('is_file')
                and all(current[field] == baseline.get(field) for field in ('exists', 'is_file', 'size', 'mtime_ns')))


def validate_preview_files(job) -> list[str]:
    problems = []
    try:
        validate_job_paths(job)
    except (ValueError, TypeError, OSError) as exc:
        return [str(exc)]
    for item in _previews(job):
        if not item.included:
            continue
        try:
            paths = [item.source_path, item.target_path] + ([item.mobile_output_path] if item.mobile_output_path else [])
            if any(_has_link_component(Path(path)) for path in paths):
                problems.append(f'연결 경로 또는 재분석 지점은 처리할 수 없습니다: {item.source_path}')
                continue
            if not _unchanged(item.source_path, getattr(job, 'source_fingerprints', {})):
                problems.append(f'원본이 변경·누락되었거나 확인 기록이 없습니다: {item.source_path}')
            for path in paths[1:]:
                if Path(path).exists():
                    problems.append(f'대상 파일 또는 디렉토리가 이미 존재합니다: {path}')
        except OSError as exc:
            problems.append(f'파일 상태를 확인할 수 없습니다: {item.source_path}: {exc}')
    return problems


def validate_delete_candidate(job, item) -> list[str]:
    """A restored checkbox is never authorization; validate successful copy evidence."""
    try:
        validate_job_paths(job)
        preview = next((entry for entry in _previews(job) if entry.item_id == item.item_id and entry.source_path == item.delete_path), None)
        execution = getattr(job, 'execution_bundle', None)
        if preview is None or execution is None:
            return ['원본 삭제 후보의 작업 기록이 없습니다.']
        matches = [result for result in execution.execution_results if result.source_path == preview.source_path
                   and result.target_path == preview.target_path and result.status == 'SUCCESS' and result.action == 'copy']
        if len(matches) != 1 or not preview.included:
            return ['성공한 복사 작업의 원본만 삭제할 수 있습니다.']
        for path, baseline in ((preview.source_path, getattr(job, 'source_fingerprints', {})),
                               (preview.target_path, getattr(job, 'result_fingerprints', {}))):
            if _has_link_component(Path(path)) or not _unchanged(path, baseline):
                return [f'원본 또는 복사 결과가 변경·누락되었거나 확인 기록이 없습니다: {path}']
        return []
    except (ValueError, TypeError, OSError) as exc:
        return [str(exc)]
