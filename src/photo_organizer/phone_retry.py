"""Read-only selection of unchanged, definitely unfinished phone transfer files."""
from __future__ import annotations

import stat
from pathlib import Path
from typing import Iterable, Mapping

from .phone_transfer import OutputFolder, TransferResult, _check_ancestors


def _fingerprint(source: Path) -> tuple[int, int]:
    try:
        _check_ancestors(source)
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('일반 파일이 아닙니다.')
        return info.st_size, info.st_mtime_ns
    except (OSError, ValueError) as exc:
        raise ValueError(f'원본 상태를 확인하지 못했습니다. 목록을 다시 조회해주세요: {source}') from exc


def capture_retry_snapshot(folders: Iterable[OutputFolder]) -> dict[Path, tuple[int, int]]:
    """Capture only original file size/mtime, without trusting remote completion."""
    snapshot: dict[Path, tuple[int, int]] = {}
    for folder in folders:
        for source in folder.files:
            source.relative_to(folder.path)
            snapshot[source] = _fingerprint(source)
    return snapshot


def retry_folders(folders: Iterable[OutputFolder], results: Iterable[TransferResult],
                  snapshot: Mapping[Path, tuple[int, int]]) -> list[OutputFolder]:
    """Retry FAILED/CANCELLED only. Unknown commits and empty-folder results are excluded.

    Caller must separately preserve/revalidate the device and destination context.
    Every selected file is checked against the first attempt's fixed snapshot.
    Any changed/missing file rejects the entire retry selection before submission.
    """
    statuses: dict[Path, set[str]] = {}
    for result in results:
        statuses.setdefault(result.source, set()).add(result.status)
    eligible = {source for source, values in statuses.items()
                if values and values <= {'FAILED', 'CANCELLED'}}
    planned: list[OutputFolder] = []
    for folder in folders:
        files: list[Path] = []
        directories: set[Path] = set()
        size = 0
        for source in folder.files:
            if source not in eligible:
                continue
            source.relative_to(folder.path)
            current = _fingerprint(source)
            if source not in snapshot or current != snapshot[source]:
                raise ValueError(f'원본 파일이 변경되었거나 최초 상태가 없습니다. 목록을 다시 조회해주세요: {source}')
            files.append(source)
            size += current[0]
            parent = source.parent
            while parent != folder.path:
                directories.add(parent)
                parent = parent.parent
        if files:
            ordered = tuple(sorted(directories, key=lambda path: (len(path.parts), str(path).casefold())))
            planned.append(OutputFolder(folder.path, tuple(files), size, ordered, getattr(folder, 'relative_parts', ())))
    return planned
