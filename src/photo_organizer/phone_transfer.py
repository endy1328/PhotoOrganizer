"""Local output discovery and phone filename conflict policy, independent of Qt/WPD."""
from __future__ import annotations

import logging
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .models import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteEntry:
    id: str
    name: str
    is_folder: bool
    size: int | None = None


@dataclass(frozen=True)
class OutputFolder:
    path: Path
    files: tuple[Path, ...]
    size: int
    directories: tuple[Path, ...] = ()


@dataclass(frozen=True)
class TransferResult:
    source: Path
    status: str
    message: str = ''
    remote_id: str = ''


class TransferBackend(Protocol):
    def list_children(self, parent_id: str) -> list[RemoteEntry]: ...
    def create_folder(self, parent_id: str, name: str) -> RemoteEntry: ...
    def upload_new(self, parent_id: str, name: str, source: Path,
                   progress: Callable[[int], None], cancelled: Callable[[], bool]) -> RemoteEntry: ...
    def overwrite_file(self, parent_id: str, name: str, source: Path,
                       progress: Callable[[int], None], cancelled: Callable[[], bool],
                       existing_id: str) -> RemoteEntry: ...


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _temporary(name: str) -> bool:
    name = name.casefold()
    return name.startswith('.photoorganizer_') or name.endswith('.tmp') or '.tmp.' in name


def _check_ancestors(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if _is_link(ancestor):
            raise ValueError('원본 경로가 링크로 변경되었습니다. 목록을 다시 조회해 주세요.')


def _children(path: Path) -> list[Path]:
    return sorted(path.iterdir(), key=lambda p: p.name.casefold())


def scan_outputs(target: Path) -> list[OutputFolder]:
    """Snapshot actual output_* trees; never follow links, junctions or staging files."""
    target = Path(target)
    if not target.is_dir() or _is_link(target):
        raise ValueError('Target 경로가 유효한 일반 디렉토리가 아닙니다.')
    outputs: list[OutputFolder] = []
    names: set[str] = set()

    def collect(root: Path) -> OutputFolder:
        files: list[Path] = []
        directories: list[Path] = []

        def visit(directory: Path) -> None:
            for path in _children(directory):
                if _temporary(path.name) or _is_link(path):
                    continue
                if path.is_dir():
                    directories.append(path)
                    visit(path)
                elif path.is_file():
                    files.append(path)

        visit(root)
        return OutputFolder(root, tuple(files), sum(p.stat().st_size for p in files), tuple(directories))

    def find(directory: Path) -> None:
        for path in _children(directory):
            if _temporary(path.name) or _is_link(path) or not path.is_dir():
                continue
            if path.name.casefold().startswith('output_'):
                if path.name.casefold() in names:
                    raise ValueError(f'같은 이름의 출력 폴더가 여러 곳에 있습니다: {path.name}. 별도 Target을 선택해 주세요.')
                names.add(path.name.casefold())
                outputs.append(collect(path))
            else:
                find(path)

    find(target)
    return outputs


def _validate_video_limit(limit_video_bytes: int | None) -> None:
    if limit_video_bytes is not None and (type(limit_video_bytes) is not int or limit_video_bytes <= 0):
        raise ValueError('동영상 제외 기준 용량은 0보다 큰 정수 바이트 값이어야 합니다.')


def _size_exclusion(source: Path, size: int, limit_video_bytes: int | None) -> TransferResult | None:
    if limit_video_bytes is not None and source.suffix.casefold() in VIDEO_EXTENSIONS and size >= limit_video_bytes:
        return TransferResult(source, 'SIZE_EXCLUDED',
                              f'용량 제한으로 제외: {size / 1_000_000:.6f} MB / 기준 {limit_video_bytes / 1_000_000:g} MB 이상')
    return None


def plan_video_transfer(folders: list[OutputFolder], limit_video_bytes: int | None = None
                        ) -> tuple[list[OutputFolder], list[TransferResult]]:
    """Filter actual output sizes; enabled plans contain only directories with eligible files.

    MB in displayed reasons is decimal: 1 MB = 1,000,000 bytes.
    Disabled filtering preserves existing empty-directory copy behavior.
    """
    _validate_video_limit(limit_video_bytes)
    if limit_video_bytes is None:
        return list(folders), []
    eligible: list[OutputFolder] = []
    excluded: list[TransferResult] = []
    for folder in folders:
        files: list[Path] = []
        directories: set[Path] = set()
        total_size = 0
        for source in folder.files:
            source.relative_to(folder.path)
            _check_ancestors(source)
            if not source.is_file():
                raise ValueError('원본 파일이 없어졌습니다. 목록을 다시 조회해 주세요.')
            size = source.stat().st_size
            result = _size_exclusion(source, size, limit_video_bytes)
            if result:
                excluded.append(result)
                continue
            files.append(source)
            total_size += size
            parent = source.parent
            while parent != folder.path:
                directories.add(parent)
                parent = parent.parent
        if files:
            ordered = tuple(sorted(directories, key=lambda p: (len(p.parts), str(p).casefold())))
            eligible.append(OutputFolder(folder.path, tuple(files), total_size, ordered))
    return eligible, excluded


class _VideoSizeExcluded(Exception):
    def __init__(self, result: TransferResult):
        self.result = result


def transfer_outputs(backend: TransferBackend, parent_id: str, folders: list[OutputFolder],
                     progress: Callable[[dict], None] | None = None,
                     cancelled: Callable[[], bool] | None = None,
                     conflict_policy: str = 'overwrite',
                     limit_video_bytes: int | None = None) -> list[TransferResult]:
    """Copy files with explicit overwrite (default), skip or rename policy.

    Transport errors stop the queue; uncertain commits are not called successful.
    Progress bytes describe bytes actually submitted in this attempt.
    """
    if conflict_policy not in {'overwrite', 'skip', 'rename'}:
        raise ValueError('지원하지 않는 휴대폰 동일 이름 처리 설정입니다.')
    cancelled = cancelled or (lambda: False)
    progress = progress or (lambda update: None)
    folders, excluded = plan_video_transfer(folders, limit_video_bytes)
    results: list[TransferResult] = list(excluded)
    total_files = sum(len(folder.files) for folder in folders) + len(excluded)
    total_bytes = sum(folder.size for folder in folders)
    planned_sizes: dict[Path, int] = {}
    if limit_video_bytes is not None:
        for folder in folders:
            for source in folder.files:
                _check_ancestors(source)
                planned_sizes[source] = source.stat().st_size
        total_bytes = sum(planned_sizes.values())
    completed = len(excluded)
    written_bytes = 0
    stopped: tuple[str, str] | None = None

    def notify(source: Path) -> None:
        progress({'file': str(source), 'bytes': written_bytes, 'total_bytes': total_bytes,
                  'completed': completed, 'total_files': total_files})

    def ensure_folder(parent: str, name: str) -> str:
        matches = [entry for entry in backend.list_children(parent) if entry.name.casefold() == name.casefold()]
        if matches:
            if len(matches) != 1 or not matches[0].is_folder:
                raise ValueError(f'대상 폴더 이름 충돌: {name}')
            return matches[0].id
        created = backend.create_folder(parent, name)
        if not created.is_folder or created.name.casefold() != name.casefold() or not created.id:
            raise OSError(f'휴대폰 폴더 생성 결과를 확인하지 못했습니다: {name}')
        return created.id

    for result in excluded:
        logger.info('휴대폰 복사 %s: %s (%s)', result.status, result.source, result.message)
        notify(result.source)

    for folder in folders:
        folder_error: str | None = None
        parents: dict[Path, str] = {}
        if cancelled():
            stopped = ('CANCELLED', '사용자가 전송을 취소했습니다.')
        if stopped is None:
            try:
                _check_ancestors(folder.path)
                if not folder.path.is_dir():
                    raise ValueError('출력 폴더가 변경되었거나 링크입니다. 목록을 다시 조회해 주세요.')
                parents[folder.path] = ensure_folder(parent_id, folder.path.name)
                for directory in folder.directories:
                    if cancelled():
                        raise InterruptedError('사용자가 전송을 취소했습니다.')
                    directory.relative_to(folder.path)
                    _check_ancestors(directory)
                    if not directory.is_dir():
                        raise ValueError(f'출력 하위 폴더가 변경되었습니다: {directory.name}')
                    parents[directory] = ensure_folder(parents[directory.parent], directory.name)
            except InterruptedError as exc:
                stopped = ('CANCELLED', str(exc))
            except OSError as exc:
                stopped = ('FAILED', str(exc))
            except (ValueError, KeyError) as exc:
                folder_error = str(exc)

        for source in folder.files:
            current_bytes = 0
            if cancelled():
                stopped = ('CANCELLED', '사용자가 전송을 취소했습니다.')
            if stopped is not None:
                result = TransferResult(source, *stopped)
            elif folder_error:
                result = TransferResult(source, 'FAILED', folder_error)
            else:
                upload_started = False
                try:
                    source.relative_to(folder.path)
                    # Recheck every ancestor after snapshot; do not traverse a replaced junction.
                    _check_ancestors(source)
                    if not source.is_file():
                        raise ValueError('원본 파일이 없어졌습니다. 목록을 다시 조회해 주세요.')
                    before = source.stat()
                    exclusion = _size_exclusion(source, before.st_size, limit_video_bytes)
                    if exclusion:
                        raise _VideoSizeExcluded(exclusion)
                    parent = parents.get(source.parent)
                    if parent is None:
                        chain = source.parent.relative_to(folder.path).parts
                        parent = parents[folder.path]
                        for name in chain:
                            parent = ensure_folder(parent, name)
                        parents[source.parent] = parent
                    def advance(count: int) -> None:
                        nonlocal current_bytes, written_bytes
                        count = max(0, min(int(count), before.st_size))
                        written_bytes += max(0, count - current_bytes)
                        current_bytes = max(current_bytes, count)
                        notify(source)

                    entry = None
                    destination_name = source.name
                    replaced = False
                    skipped = False
                    for attempt in range(20):
                        if cancelled():
                            raise InterruptedError('사용자가 전송을 취소했습니다.')
                        children = backend.list_children(parent)
                        # Recheck after phone discovery, before skip/rename/overwrite or upload.
                        exclusion = _size_exclusion(source, source.stat().st_size, limit_video_bytes)
                        if exclusion:
                            raise _VideoSizeExcluded(exclusion)
                        matches = [e for e in children if e.name.casefold() == source.name.casefold()]
                        if len(matches) > 1 or any(e.is_folder for e in matches):
                            raise ValueError('같은 이름의 객체가 여러 개이거나 폴더와 충돌합니다.')
                        if matches and conflict_policy == 'skip':
                            result = TransferResult(source, 'SKIPPED', '같은 이름의 기존 파일을 유지했습니다(내용 일치 여부 미검증).')
                            skipped = True
                            break
                        destination_name = source.name
                        if matches and conflict_policy == 'rename':
                            names = {child.name.casefold() for child in children}
                            for number in range(1, 10000):
                                candidate = f'{source.stem}_copy{number:04d}{source.suffix}'
                                if candidate.casefold() not in names:
                                    destination_name = candidate
                                    break
                            else:
                                raise ValueError('새 이름 순번이 9999를 초과했습니다.')
                        upload_started = True
                        if matches and conflict_policy == 'overwrite':
                            replaced = True
                            entry = backend.overwrite_file(parent, source.name, source, advance, cancelled, matches[0].id)
                        else:
                            try:
                                entry = backend.upload_new(parent, destination_name, source, advance, cancelled)
                            except FileExistsError:
                                upload_started = False
                                continue  # Re-evaluate policy when a concurrent writer creates the name.
                        break
                    else:
                        raise ValueError('전송 중 이름 충돌이 반복되었습니다. 목록을 다시 조회해 주세요.')
                    if entry is None and not skipped:
                        raise OSError('전송된 파일의 완료 응답을 확인하지 못했습니다.')
                    if entry is not None:
                        after = source.stat()
                        verified = (entry.id and not entry.is_folder and entry.name == destination_name
                                    and entry.size == before.st_size and before.st_size == after.st_size
                                    and before.st_mtime_ns == after.st_mtime_ns)
                        success_message = '덮어쓰기 완료 및 파일 크기 확인' if replaced else (
                            f'새 이름으로 복사: {destination_name} (파일 크기 확인)' if destination_name != source.name
                            else '전송 완료 및 파일 크기 확인')
                        result = TransferResult(source, 'COPIED' if verified else 'UNVERIFIED',
                                                success_message if verified else '전송 후 이름/크기 또는 원본 상태를 확인하지 못했습니다.', entry.id)
                except _VideoSizeExcluded as exc:
                    result = exc.result
                    # Remove its planned contribution; a grown file must not subtract
                    # bytes belonging to other files from the remaining transfer total.
                    total_bytes -= planned_sizes.pop(source, 0)
                except FileExistsError as exc:
                    result = TransferResult(source, 'FAILED', f'교체 직전에 대상 이름이 변경되었습니다: {exc}')
                except InterruptedError as exc:
                    stopped = ('CANCELLED', str(exc))
                    result = TransferResult(source, *stopped)
                except OSError as exc:
                    stopped = ('FAILED', str(exc))
                    result = TransferResult(source, 'UNVERIFIED' if upload_started else 'FAILED',
                                            f'전송 완료 여부 미확인: {exc}' if upload_started else str(exc))
                except (ValueError, KeyError) as exc:
                    result = TransferResult(source, 'FAILED', str(exc))
            results.append(result)
            completed += 1
            logger.info('휴대폰 복사 %s: %s (%s)', result.status, source, result.message)
            notify(source)
        if not folder.files:
            if stopped:
                status, message = stopped
            elif folder_error:
                status, message = 'FAILED', folder_error
            else:
                status, message = 'COPIED', '빈 폴더 생성/확인'
            results.append(TransferResult(folder.path, status, message or ''))
    return results
