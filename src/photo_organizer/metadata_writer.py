"""Explicit, backed-up original model edits. Recovery never overwrites a file."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from .process_utils import hidden_process_kwargs

STORAGE_NAME = '.photo_organizer_metadata'
OWNER = {'owner': 'PhotoOrganizer metadata', 'version': 1}
SUPPORTED = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.m4v'}


def discover_exiftool():
    roots = [Path(sys._MEIPASS)] if getattr(sys, '_MEIPASS', None) else []
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        tool = root / 'tools' / 'exiftool' / 'exiftool.exe'
        if tool.is_file():
            return tool
    tool = shutil.which('exiftool') or shutil.which('exiftool.exe')
    return Path(tool) if tool else None


def _run_exiftool(arguments, *, timeout=60):
    tool = discover_exiftool()
    if tool is None:
        raise ValueError('동봉된 ExifTool을 찾을 수 없습니다.')
    # Windows Perl argv can round-trip through the system ANSI code page. Feed
    # UTF-8 arguments via ExifTool's argument stream to preserve Unicode values.
    if any('\n' in argument or '\r' in argument for argument in arguments):
        raise ValueError('줄바꿈이 포함된 경로/태그는 지원하지 않습니다.')
    options = hidden_process_kwargs()
    options.pop('stdin', None)
    return subprocess.run([str(tool), '-config', '', '-charset', 'filename=UTF8', '-@', '-'],
                          input=('\n'.join(arguments) + '\n').encode('utf-8'), capture_output=True,
                          check=True, timeout=timeout, **options)


def read_exiftool_model(path):
    """Supplement native readers, without interpreting a filename as metadata."""
    tool = discover_exiftool()
    if tool is None or Path(path).suffix.lower() not in SUPPORTED or not Path(path).is_file():
        return None
    result = _run_exiftool(['-j', '-G1', '-a', '-s', '-Model', '-CameraModelName',
                           '-DeviceModelName', str(Path(path).absolute())], timeout=15)
    tags = json.loads(result.stdout.decode('utf-8-sig'))[0]
    values = [str(value).strip() for key, value in tags.items()
              if key.split(':')[-1] in ('Model', 'CameraModelName', 'DeviceModelName') and str(value).strip()]
    distinct = set(values)
    if len(distinct) > 1:
        raise ValueError('원본에 서로 다른 모델 태그가 있습니다.')
    return values[0] if values else None


def _read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('메타정보 기록이 너무 큽니다.')
    return json.loads(raw)


def is_metadata_storage(path):
    path = Path(path)
    for directory in (path, *path.parents):
        if directory.name == STORAGE_NAME:
            try:
                for component in (directory, *directory.parents):
                    info = component.lstat()
                    if getattr(info, 'st_file_attributes', 0) & 0x400 or component.is_symlink():
                        return False
                marker = directory / 'owner.json'
                info = marker.lstat()
                return (not marker.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400
                        and info.st_nlink == 1 and _read_json(marker) == OWNER)
            except (OSError, ValueError, TypeError):
                return False
    return False


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path):
    _, stat = _safe_source(path)
    return {'sha256': _hash(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'device': stat.st_dev, 'inode': stat.st_ino}


def _apply_times(path, record):
    os.utime(path, ns=(record['atime_ns'], record['mtime_ns']))
    if os.name != 'nt' or record.get('birthtime_ns') is None:
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    ticks = record['birthtime_ns'] // 100 + 116444736000000000
    creation = wintypes.FILETIME(ticks & 0xffffffff, ticks >> 32)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = kernel.SetFileTime
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                         ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    function.restype = wintypes.BOOL
    with Path(path).open('r+b') as stream:
        if not function(msvcrt.get_osfhandle(stream.fileno()), ctypes.byref(creation), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        stream.flush()
        os.fsync(stream.fileno())


def _safe_source(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        info = component.lstat()
        if component.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('링크 또는 연결된 경로의 원본은 수정할 수 없습니다.')
    stat = path.stat()
    if not path.is_file() or stat.st_nlink != 1 or is_metadata_storage(path):
        raise ValueError('일반 원본 파일만 수정할 수 있습니다. 하드 링크는 지원하지 않습니다.')
    return path, stat


def _atomic_json(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.journal_', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_verified(source, destination, expected):
    with Path(source).open('rb') as reader, Path(destination).open('xb') as writer:
        shutil.copyfileobj(reader, writer, 1048576)
        writer.flush()
        os.fsync(writer.fileno())
    if _hash(destination) != expected:
        raise ValueError('복사본의 내용 지문이 원본과 다릅니다.')


@contextmanager
def _source_lock(storage, path):
    lock_path = storage / (hashlib.sha256(str(path).casefold().encode()).hexdigest() + '.lock')
    with lock_path.open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('다른 원본 메타정보 수정이 진행 중입니다.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class ModelMetadataWriter:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def supports(self, path):
        return Path(path).suffix.lower() in SUPPORTED and discover_exiftool() is not None

    def _tags(self, path):
        tool = discover_exiftool()
        if tool is None:
            raise ValueError('동봉된 ExifTool을 찾을 수 없습니다.')
        result = _run_exiftool(['-j', '-G1', '-a', '-s', '-struct', str(path)])
        values = json.loads(result.stdout.decode('utf-8-sig'))
        if len(values) != 1:
            raise ValueError('원본 메타정보를 확인할 수 없습니다.')
        return values[0]

    def inspect(self, path):
        path, _ = _safe_source(path)
        fingerprint = _fingerprint(path)
        tags = self._tags(path)
        models = {key: value for key, value in tags.items()
                  if key.split(':')[-1] in ('Model', 'CameraModelName', 'DeviceModelName')}
        records = self.recovery_records(path)
        if _fingerprint(path) != fingerprint:
            raise ValueError('조회 중 원본이 변경되었습니다. 다시 조회하세요.')
        return {'source_path': str(path), 'model': next(iter(models.values()), ''),
                'model_tags': models, 'supported': self.supports(path),
                'fingerprint': fingerprint,
                'backup_path': records[-1]['backup_path'] if records else '', 'records': records}

    def _storage(self, path):
        storage = path.parent / STORAGE_NAME
        try:
            storage.mkdir()
        except FileExistsError:
            if not is_metadata_storage(storage):
                raise ValueError('기존 메타정보 보관 폴더의 소유 표식을 확인할 수 없습니다.')
        if not (storage / 'owner.json').exists():
            _atomic_json(storage / 'owner.json', OWNER)
        return storage

    def _preserved(self, path, tags):
        # Semantic capture/GPS/orientation tags must remain identical. Layout offsets
        # and ExifTool-generated file properties may legitimately change after writing.
        names = ('DateTimeOriginal', 'CreateDate', 'ModifyDate', 'TrackCreateDate', 'TrackModifyDate',
                 'MediaCreateDate', 'MediaModifyDate', 'Orientation', 'GPS', 'ImageWidth', 'ImageHeight',
                 'Rotation', 'Duration', 'VideoFrameRate', 'AudioSampleRate', 'AudioChannels')
        semantic = {key: value for key, value in tags.items()
                    if key.split(':')[-1] in names or key.split(':')[-1].startswith('GPS')}
        if path.suffix.lower() in ('.jpg', '.jpeg', '.png'):
            from PIL import Image
            with Image.open(path) as image:
                image.load()
                essence = (image.size, image.mode, hashlib.sha256(image.tobytes()).hexdigest())
        else:
            # Spool hashes rather than retaining a packet JSON array for large videos.
            with tempfile.TemporaryFile() as packet_file:
                subprocess.run(['ffprobe', '-v', 'error', '-show_packets', '-show_streams',
                                '-show_data_hash', 'sha256', '-show_entries',
                                'packet=stream_index,data_hash,pts,dts,duration:'
                                'stream=index,codec_name,codec_type,profile,width,height,sample_rate,channels,channel_layout,extradata_hash',
                                '-of', 'compact=p=1', str(path)], stdout=packet_file, stderr=subprocess.PIPE,
                               check=True, timeout=120, **hidden_process_kwargs())
                packet_file.seek(0)
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: packet_file.read(1048576), b''):
                    size += len(chunk)
                    digest.update(chunk)
                if not size:
                    raise ValueError('영상/음성 데이터 보존을 확인할 수 없습니다.')
                essence = digest.hexdigest()
        return semantic, essence

    def write_model(self, path, model, *, expected_fingerprint=None):
        if (type(model) is not str or not model.strip() or len(model) > 255 or
                model.strip().casefold() == 'unknown' or any(ord(c) < 32 for c in model)):
            raise ValueError('실제 촬영 기기의 모델명을 1~255자로 입력하세요.')
        model = model.strip()
        path, stat = _safe_source(path)
        if expected_fingerprint is not None and _fingerprint(path) != expected_fingerprint:
            raise ValueError('확인창을 연 뒤 원본이 변경되었습니다. 다시 조회하세요.')
        if not self.supports(path):
            raise ValueError('왕복 기록이 검증되지 않은 형식이거나 ExifTool이 없습니다.')
        storage = self._storage(path)
        with _source_lock(storage, path):
            if expected_fingerprint is not None and _fingerprint(path) != expected_fingerprint:
                raise ValueError('확인창을 연 뒤 원본이 변경되었습니다. 다시 조회하세요.')
            before = _hash(path)
            if shutil.disk_usage(storage).free < stat.st_size * 2 + 16 * 1048576:
                raise ValueError('백업과 임시본을 위한 저장 공간이 부족합니다.')
            tags = self._tags(path)
            preserved = self._preserved(path, tags)
            identifier = str(uuid.uuid4())
            backup = storage / (identifier + '.bak')
            stage = storage / (identifier + path.suffix.lower())
            journal = storage / (identifier + '.json')
            record = {'transaction_id': identifier, 'created_ns': time.time_ns(), 'source_path': str(path), 'backup_path': str(backup),
                      'stage_path': str(stage), 'before_hash': before, 'after_hash': '',
                      'model': model, 'previous_model': next((v for k, v in tags.items() if k.endswith(':Model')), ''),
                      'atime_ns': stat.st_atime_ns, 'mtime_ns': stat.st_mtime_ns, 'state': 'BACKING_UP'}
            record['birthtime_ns'] = getattr(stat, 'st_birthtime_ns', stat.st_ctime_ns) if os.name == 'nt' else None
            _atomic_json(journal, record)
            _copy_verified(path, backup, before)
            _copy_verified(path, stage, before)
            command = ['-overwrite_original']
            if path.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                command.append('-EXIF:Model=' + model)
                if 'XMP-tiff:Model' in tags:
                    command.append('-XMP-tiff:Model=' + model)
            else:
                command.extend(['-Keys:Model=' + model, '-UserData:Model=' + model])
            _run_exiftool(command + [str(stage)], timeout=120)
            updated = self._tags(stage)
            model_values = [str(value).strip() for key, value in updated.items()
                            if key.split(':')[-1] in ('Model', 'CameraModelName', 'DeviceModelName')]
            if not model_values or any(value != model for value in model_values):
                raise ValueError('다른 위치의 모델 태그 충돌을 안전하게 해소하지 못해 원본을 유지합니다.')
            if self._preserved(stage, updated) != preserved:
                raise ValueError('촬영 정보 또는 미디어 내용이 변경되어 원본을 유지합니다.')
            from .metadata import MetadataExtractor
            from .fallback import sanitize_model_name
            reread = MetadataExtractor().extract(stage)
            display_key = 'photo_model' if reread.media_type == 'photo' else 'video_model'
            if (reread.model_name != sanitize_model_name(model) or
                    reread.metadata.get('display_metadata', {}).get(display_key) != model):
                raise ValueError('앱에서 새 모델명을 다시 읽지 못해 원본을 유지합니다.')
            with stage.open('r+b') as stream:
                os.fsync(stream.fileno())
            shutil.copystat(path, stage, follow_symlinks=False)
            _apply_times(stage, record)
            record.update(after_hash=_hash(stage), state='PREPARED')
            _atomic_json(journal, record)
            _, latest = _safe_source(path)
            if ((latest.st_dev, latest.st_ino, latest.st_size, latest.st_mtime_ns) !=
                    (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) or
                    _hash(path) != before or _hash(backup) != before):
                raise ValueError('원본 또는 백업이 외부에서 변경되어 교체하지 않습니다.')
            os.replace(stage, path)
            if _hash(path) != record['after_hash']:
                raise ValueError('교체 후 내용이 달라 기록과 백업을 보존합니다.')
            _apply_times(path, record)
            record['state'] = 'COMMITTED'
            _atomic_json(journal, record)
            return record

    def recovery_records(self, path=None):
        if path is not None:
            source = Path(path).absolute()
            stores = [source.parent / STORAGE_NAME]
        elif self.base_dir is not None:
            source = None
            stores = list(self.base_dir.rglob(STORAGE_NAME))
        else:
            return []
        records = []
        for storage in stores:
            if not is_metadata_storage(storage):
                continue
            for journal in storage.glob('*.json'):
                if journal.name == 'owner.json':
                    continue
                try:
                    record = _read_json(journal)
                    identifier = str(uuid.UUID(record['transaction_id']))
                    original = Path(record['source_path'])
                    backup = storage / (identifier + '.bak')
                    if (journal.stem != identifier or original.parent.absolute() != storage.parent.absolute() or
                            record['backup_path'] != str(backup) or (source is not None and original != source)):
                        continue
                    current = _hash(original) if original.is_file() else None
                    status = ('unchanged' if current == record['before_hash'] else
                              'modified' if current == record['after_hash'] else 'external_change')
                    backup_valid = (backup.is_file() and not backup.is_symlink() and
                                    backup.stat().st_nlink == 1 and _hash(backup) == record['before_hash'])
                    effective = ('COMMITTED' if status == 'modified' and record['state'] == 'PREPARED' else
                                 'RESTORED' if status == 'unchanged' and record['state'] == 'RESTORE_PREPARED' else
                                 record['state'])
                    record = dict(record, recovery_status=status, effective_state=effective,
                                  backup_valid=backup_valid,
                                  can_restore=backup_valid and status == 'modified' and
                                  record['state'] in ('PREPARED', 'COMMITTED', 'RESTORE_PREPARED'))
                    records.append(record)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        return sorted(records, key=lambda r: r.get('created_ns', 0) if type(r.get('created_ns', 0)) is int else 0)

    def restore(self, path, *, expected_fingerprint=None):
        path, _ = _safe_source(path)
        if expected_fingerprint is not None and _fingerprint(path) != expected_fingerprint:
            raise ValueError('확인창을 연 뒤 원본이 변경되었습니다. 다시 조회하세요.')
        records = [r for r in self.recovery_records(path)
                   if r['state'] in ('COMMITTED', 'PREPARED', 'RESTORE_PREPARED') and
                   r['recovery_status'] == 'modified']
        if not records:
            raise ValueError('외부 변경 없이 복원할 수 있는 수정 기록이 없습니다.')
        record = records[-1]
        if not record['can_restore']:
            raise ValueError('가장 최근 수정의 백업이 변경되어 복원하지 않습니다.')
        storage = path.parent / STORAGE_NAME
        with _source_lock(storage, path):
            if expected_fingerprint is not None and _fingerprint(path) != expected_fingerprint:
                raise ValueError('확인창을 연 뒤 원본이 변경되었습니다. 다시 조회하세요.')
            backup = Path(record['backup_path'])
            if _hash(backup) != record['before_hash'] or _hash(path) != record['after_hash']:
                raise ValueError('원본 또는 백업 내용이 변경되어 복원하지 않습니다.')
            stage = storage / (str(uuid.uuid4()) + path.suffix.lower())
            _copy_verified(backup, stage, record['before_hash'])
            shutil.copystat(path, stage, follow_symlinks=False)
            _apply_times(stage, record)
            record['state'] = 'RESTORE_PREPARED'
            journal = storage / (record['transaction_id'] + '.json')
            _atomic_json(journal, record)
            _safe_source(path)
            if _hash(path) != record['after_hash'] or _hash(backup) != record['before_hash']:
                raise ValueError('복원 직전에 외부 변경이 발견되어 원본을 유지합니다.')
            os.replace(stage, path)
            if _hash(path) != record['before_hash']:
                raise ValueError('복원 후 내용이 달라 기록과 백업을 보존합니다.')
            _apply_times(path, record)
            record['state'] = 'RESTORED'
            _atomic_json(journal, record)
            return record
