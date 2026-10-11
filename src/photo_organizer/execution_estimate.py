"""Advisory timing ranges from existing plan data; never reads/probes media files.

Initial rates are assumptions, not hardware benchmarks or guaranteed deadlines.
Callers pass active elapsed time excluding pauses, and only record complete runs.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import tempfile

_QUALITIES = {'very_high', 'high_plus', 'high', 'balanced', 'compact', 'small'}


def _setting_int(settings, name, default, minimum=1, maximum=100000):
    value = getattr(settings, name, default)
    return value if type(value) is int and minimum <= value <= maximum else default


def _valid_profile(profile):
    if type(profile) is not str or len(profile) > 128:
        return False
    fields = profile.split('|')
    if len(fields) != 8:
        return False
    encoder, speed, workers, output, quality, video_width, photo_width, jpeg_quality = fields
    return (encoder in {'cpu', 'gpu', 'auto'} and speed in {'quality', 'balanced', 'fast'}
            and workers in {'1', '2', '4'} and output in {'0', '1'} and quality in _QUALITIES
            and all(value.isascii() and value.isdigit() for value in (video_width, photo_width, jpeg_quality))
            and 0 <= int(video_width) <= 100000 and 1 <= int(photo_width) <= 100000
            and 1 <= int(jpeg_quality) <= 100)


@dataclass(frozen=True)
class ItemEstimate:
    item_id: str
    media_type: str
    seconds: float


@dataclass(frozen=True)
class ExecutionEstimate:
    total_seconds: float
    lower_seconds: float
    upper_seconds: float
    basis: str
    item_estimates: tuple[ItemEstimate, ...]
    photo_count: int
    video_count: int
    missing_data_count: int
    profile: str
    raw_seconds: float
    notes: tuple[str, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.item_estimates)


@dataclass(frozen=True)
class RemainingEstimate:
    total_seconds: float
    lower_seconds: float
    upper_seconds: float
    basis: str
    completed_count: int
    remaining_count: int
    paused: bool = False


def _number(value, *, maximum=1e15):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= maximum else None


def _duration(value):
    if isinstance(value, str) and ':' in value:
        parts = value.split(':')
        if len(parts) != 3:
            return None
        numbers = [_number(part, maximum=31536000) for part in parts]
        if any(number is None for number in numbers) or numbers[1] >= 60 or numbers[2] >= 60:
            return None
        value = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    number = _number(value, maximum=31536000)
    return number if number is not None and number > 0 else None


def _display_size(value):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*', str(value))
    if match is None:
        return None
    return _number(float(match[1]) * (1024 ** ('B', 'KB', 'MB', 'GB', 'TB').index(match[2])))


def _unfinished(stages, stage):
    record = stages.get(stage, {})
    state = record.get('state') if isinstance(record, dict) else None
    return state not in {'DONE', 'NOT_REQUIRED', 'SKIPPED', 'SIZE_EXCLUDED', 'UNCERTAIN'}


def estimate_execution(preview_bundle, settings, *, source_fingerprints=None, ledger=None,
                       history=None, item_ids=None) -> ExecutionEstimate:
    fingerprints, ledger = source_fingerprints or {}, ledger or {}
    encoder = getattr(settings, 'video_encoder', 'cpu')
    encoder = encoder if encoder in {'cpu', 'gpu', 'auto'} else 'cpu'
    speed = getattr(settings, 'conversion_speed', 'balanced')
    speed = speed if speed in {'quality', 'balanced', 'fast'} else 'balanced'
    workers = getattr(settings, 'photo_workers', 1)
    workers = workers if type(workers) is int and workers in {1, 2, 4} else 1
    output_enabled = bool(getattr(settings, 'mobile_output_enabled', False))
    quality = getattr(settings, 'mobile_output_video_quality', 'balanced')
    quality = quality if isinstance(quality, str) and quality in _QUALITIES else 'balanced'
    video_width = _setting_int(settings, 'mobile_output_video_max_width', 1280, 0)
    photo_width = _setting_int(settings, 'mobile_output_max_width', 3000)
    jpeg_quality = _setting_int(settings, 'mobile_output_jpeg_quality', 75, 1, 100)
    profile = f'{encoder}|{speed}|{workers}|{int(output_enabled)}|{quality}|{video_width}|{photo_width}|{jpeg_quality}'
    raw_media = getattr(preview_bundle, 'media_items', [])
    media = {str(item.source_path): item for item in raw_media} if isinstance(raw_media, (list, tuple)) else {}
    estimates, missing = [], 0
    rows = getattr(preview_bundle, 'preview_items', [])
    for item in rows if isinstance(rows, (list, tuple)) else []:
        source_path = str(getattr(item, 'source_path', ''))
        item_id = str(getattr(item, 'item_id', source_path))
        media_type = getattr(item, 'media_type', 'photo')
        if not getattr(item, 'included', True) or (item_ids is not None and item_id not in item_ids):
            continue
        stages = ledger.get(item_id, {})
        stages = stages if isinstance(stages, dict) else {}
        main = _unfinished(stages, 'main')
        output = output_enabled and getattr(item, 'mobile_output_enabled', False) and _unfinished(stages, 'output')
        remove = getattr(settings, 'operation_mode', 'copy') == 'move' and _unfinished(stages, 'source_remove')
        if not (main or output or remove):
            continue
        raw_entries = getattr(item, 'metadata_entries', [])
        entries = {entry[0]: entry[1] for entry in raw_entries if isinstance(entry, (list, tuple)) and
                   len(entry) == 2 and isinstance(entry[0], str)} if isinstance(raw_entries, (list, tuple)) else {}
        fingerprint = fingerprints.get(source_path, {})
        size = _number(fingerprint.get('size')) if isinstance(fingerprint, dict) else None
        if size is None:
            size = _display_size(entries.get('파일 크기', ''))
        if size is None:
            missing += 1
            size = 5000000 if media_type == 'photo' else 100000000
        seconds = (0.05 + size / 100000000) if main else 0
        if output and media_type == 'photo':
            photo_factor = max(0.25, min(4, (photo_width / 3000) ** 1.2)) * (0.8 + jpeg_quality / 375)
            seconds += {'quality': 0.65, 'balanced': 0.4, 'fast': 0.25}[speed] * photo_factor / workers
        elif output and media_type == 'video':
            metadata = getattr(media.get(source_path), 'metadata', {})
            info = metadata.get('media_info', {}) if isinstance(metadata, dict) else {}
            duration = _duration(info.get('duration_seconds')) if isinstance(info, dict) else None
            width = _number(info.get('width'), maximum=100000) if isinstance(info, dict) else None
            height = _number(info.get('height'), maximum=100000) if isinstance(info, dict) else None
            if not width or not height:
                resolution = re.fullmatch(r'\s*(\d+)\s*[x×]\s*(\d+)\s*', str(entries.get('원본 크기', '')))
                if resolution:
                    width, height = _number(resolution[1], maximum=100000), _number(resolution[2], maximum=100000)
            if not width or not height:
                missing += 1
                pixel_factor = 1
            else:
                scale = min(1, video_width / width) if video_width else 1
                source_ratio = width * height / (1920 * 1080)
                output_ratio = source_ratio * scale * scale
                pixel_factor = max(0.25, min(8, 0.35 * source_ratio ** 0.5 + 0.65 * output_ratio ** 0.65))
            if duration is None:
                duration = _duration(entries.get('Duration'))
            if duration is None:
                missing += 1
                duration = max(60, size / 8000000)
            rate = ({'quality': 8, 'balanced': 12, 'fast': 16} if encoder == 'gpu'
                    else {'quality': 2, 'balanced': 4, 'fast': 6})[speed]
            quality_factor = {'very_high': 1.2, 'high_plus': 1.1, 'high': 1.05, 'balanced': 1, 'compact': 0.95, 'small': 0.9}[quality]
            seconds += 0.3 + duration / rate * pixel_factor * quality_factor
        if remove:
            seconds += 0.05
        estimates.append(ItemEstimate(item_id, media_type, seconds))
    raw_seconds = sum(item.seconds for item in estimates)
    factor = history.factor(profile) if history is not None else 1
    observed = history.has_samples(profile) if history is not None else False
    total = raw_seconds * factor
    lower, upper = ((0.65, 1.75) if observed else (0.25, 4.0) if missing else (0.4, 3.0))
    notes = ('저장 장치·영상 장면·해상도·다른 작업에 따라 실제 시간은 범위를 벗어날 수 있습니다.',)
    if encoder == 'auto':
        notes += ('자동 인코더는 추가 GPU 검사 없이 CPU 기준으로 추정합니다.',)
    return ExecutionEstimate(total, total * lower, total * upper,
                             '처리 이력 보정' if observed else '초기 추정', tuple(estimates),
                             sum(item.media_type == 'photo' for item in estimates),
                             sum(item.media_type == 'video' for item in estimates), missing,
                             profile, raw_seconds, notes)


def remaining_estimate(estimate, elapsed_seconds, completed_item_ids=(), *, paused=False):
    completed = set(completed_item_ids)
    done = [item for item in estimate.item_estimates if item.item_id in completed]
    remaining = [item for item in estimate.item_estimates if item.item_id not in completed]
    if not remaining:
        return RemainingEstimate(0, 0, 0, '완료', len(done), 0, paused)
    factor = estimate.total_seconds / estimate.raw_seconds if estimate.raw_seconds else 1
    elapsed = _number(elapsed_seconds)
    if not done:
        elapsed = elapsed or 0
        total = max(0, estimate.total_seconds - elapsed)
        return RemainingEstimate(total, max(0, estimate.lower_seconds - elapsed),
                                 max(0, estimate.upper_seconds - elapsed),
                                 '초기 예상 초과' if elapsed >= estimate.total_seconds else estimate.basis,
                                 0, len(remaining), paused)
    done_weight = sum(item.seconds for item in done)
    observed = bool(done and elapsed is not None and elapsed > 0 and done_weight > 0)
    if observed:
        measured_factor = max(0.1, min(10, elapsed / done_weight))
        blend = min(1, len(done) / 3)
        factor = factor * (1 - blend) + measured_factor * blend
    total = sum(item.seconds for item in remaining) * factor
    lower = estimate.lower_seconds / estimate.total_seconds if estimate.total_seconds else 0.4
    upper = estimate.upper_seconds / estimate.total_seconds if estimate.total_seconds else 3
    return RemainingEstimate(total, total * lower, total * upper,
                             '실제 처리 속도 보정' if observed else estimate.basis,
                             len(done), len(remaining), paused)


class EstimateHistory:
    """Display-only aggregate timing factors; contains no media paths or job IDs."""
    def __init__(self, profiles=None):
        self._profiles = profiles or {}

    def factor(self, profile):
        return self._profiles.get(profile, {}).get('factor', 1)

    def has_samples(self, profile):
        return self._profiles.get(profile, {}).get('samples', 0) > 0

    def record(self, estimate, elapsed_seconds, *, completed=True):
        elapsed = _number(elapsed_seconds)
        if not completed or elapsed is None or elapsed <= 0 or estimate.raw_seconds <= 0:
            return False
        factor = max(0.1, min(10, elapsed / estimate.raw_seconds))
        previous = self._profiles.get(estimate.profile)
        if previous is None and len(self._profiles) >= 128:
            self._profiles.pop(next(iter(self._profiles)))
        if previous:
            weight = min(previous['samples'], 4)
            factor = (previous['factor'] * weight + factor) / (weight + 1)
        self._profiles[estimate.profile] = {'factor': factor, 'samples': min(1000000, (previous or {}).get('samples', 0) + 1)}
        return True

    @classmethod
    def load(cls, path):
        try:
            with Path(path).open('rb') as handle:
                payload = handle.read(65537)
            if len(payload) > 65536:
                return cls()
            data = json.loads(payload)
            if type(data) is not dict or set(data) != {'version', 'profiles'} or type(data['version']) is not int or data['version'] != 2:
                return cls()
            profiles = data['profiles']
            if type(profiles) is not dict or len(profiles) > 128:
                return cls()
            for profile, value in profiles.items():
                if not _valid_profile(profile):
                    return cls()
                if type(value) is not dict or set(value) != {'factor', 'samples'}:
                    return cls()
                if type(value['factor']) not in {int, float}:
                    return cls()
                factor = _number(value['factor'])
                if factor is None or not 0.1 <= factor <= 10 or type(value['samples']) is not int or not 1 <= value['samples'] <= 1000000:
                    return cls()
            return cls(profiles)
        except (OSError, ValueError, TypeError, RecursionError):
            return cls()

    def save(self, path):
        path, staging = Path(path), None
        try:
            payload = json.dumps({'version': 2, 'profiles': self._profiles}, allow_nan=False).encode('utf-8')
            if len(payload) > 65536:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.estimate_history_', suffix='.tmp', delete=False) as handle:
                staging = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass
