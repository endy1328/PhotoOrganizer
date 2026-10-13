"""Name-only phone bookmarks; resolve fresh session IDs without creating folders."""
import json
import os
from pathlib import Path
import tempfile


def _name(value):
    return (type(value) is str and 0 < len(value) <= 255 and bool(value.strip())
            and not any(character in value for character in ('/', '\\', '\0')))


def _components(values):
    if type(values) is not list or len(values) > 64 or not all(_name(value) for value in values):
        raise ValueError('휴대폰 경로 구성요소가 올바르지 않습니다.')
    return list(values)


def _bookmarks(values):
    if type(values) is not list or len(values) > 100:
        raise ValueError('휴대폰 즐겨찾기는 최대 100개까지 저장할 수 있습니다.')
    result = []
    for value in values:
        if (type(value) is not dict or set(value) != {'label', 'device', 'components'}
                or not _name(value['label']) or not _name(value['device'])):
            raise ValueError('휴대폰 즐겨찾기 형식이 올바르지 않습니다.')
        result.append({'label': value['label'], 'device': value['device'],
                       'components': _components(value['components'])})
    return result


class PhoneLocationStore:
    def __init__(self, path):
        self.path = Path(path) if path is not None else None

    def load(self):
        if self.path is None:
            return []
        try:
            with self.path.open('rb') as handle:
                payload = handle.read(65537)
            if len(payload) > 65536:
                return []
            data = json.loads(payload)
            if (type(data) is not dict or set(data) != {'version', 'bookmarks'}
                    or type(data['version']) is not int or data['version'] != 1):
                return []
            return _bookmarks(data['bookmarks'])
        except (OSError, ValueError, TypeError, RecursionError):
            return []

    def save(self, bookmarks):
        data = {'version': 1, 'bookmarks': _bookmarks(bookmarks)}
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(payload) > 65536:
            raise ValueError('휴대폰 즐겨찾기 파일은 64 KiB를 넘을 수 없습니다.')
        if self.path is None:
            return
        staging = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.phone_locations_',
                                             suffix='.tmp', delete=False) as handle:
                staging = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, self.path)
        finally:
            if staging is not None:
                staging.unlink(missing_ok=True)


def resolve_location(backend, components):
    names = _components(components)
    parent_id, stack = 'DEVICE', []
    children = list(backend.list_children(parent_id))
    for name in names:
        matches = [entry for entry in children if entry.is_folder and entry.name.casefold() == name.casefold()]
        if not matches:
            raise ValueError(f'휴대폰 폴더를 찾을 수 없습니다: {name}')
        if len(matches) != 1:
            raise ValueError(f'같은 이름의 휴대폰 폴더가 여러 개 있습니다: {name}')
        entry = matches[0]
        parent_id = entry.id
        stack.append((entry.id, entry.name))
        children = list(backend.list_children(parent_id))
    return stack, children
