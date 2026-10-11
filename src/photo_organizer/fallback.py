from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from .models import MediaItem


FALLBACK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # DJI's recording counter and trailing D are not a camera model.
    (re.compile(r"^DJI_(?P<date>\d{8})(?P<time>\d{6})_\d{4}_D$", re.IGNORECASE),
     "DJI_YYYYMMDDHHMMSS_SEQ_D"),
    (re.compile(r"IMG[_-]?(?P<date>\d{8})[_-]?(?P<time>\d{6})(?:\d+)?", re.IGNORECASE), "IMG_YYYYMMDD_HHMMSS"),
    (
        re.compile(
            r"(?P<date>\d{8})[_-]?(?P<time>\d{6})(?:\d+)?[_-](?P<model>[A-Za-z0-9][A-Za-z0-9_-]*)",
            re.IGNORECASE,
        ),
        "YYYYMMDD_HHMMSS_MODEL",
    ),
    (re.compile(r"(?P<date>\d{8})[_-]?(?P<time>\d{6})(?:\d+)?", re.IGNORECASE), "YYYYMMDD_HHMMSS"),
    (
        re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})[ _](?P<time>\d{2}\.\d{2}\.\d{2})", re.IGNORECASE),
        "YYYY-MM-DD HH.MM.SS",
    ),
    (re.compile(r"(?P<date>\d{8})", re.IGNORECASE), "YYYYMMDD"),
]


def parse_filename_fallback(filename: str) -> tuple[datetime | None, str | None, str]:
    stem = Path(filename).stem
    for pattern, label in FALLBACK_PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        groups = match.groupdict()
        parsed_at = _parse_date_time(groups.get("date"), groups.get("time"))
        model = groups.get("model")
        return parsed_at, sanitize_model_name(_strip_seq_suffix(model)) if model else None, label
    return None, None, "UNKNOWN"


def infer_video_model_from_photos(
    video_item: MediaItem, photo_items: list[MediaItem], window_minutes: int = 5
) -> tuple[str | None, str]:
    return infer_video_model_from_media(video_item, photo_items, window_minutes)


def infer_video_model_from_media(
    video_item: MediaItem, media_items: list[MediaItem], window_minutes: int = 5
) -> tuple[str | None, str]:
    candidate = find_video_model_candidate(video_item, media_items, window_minutes)
    if candidate is None:
        return None, "UNKNOWN"
    source = "영상" if candidate.media_type == "video" else "사진"
    return candidate.model_name, f"영상 모델명 {source} 추론"


def find_video_model_candidate(
    video_item: MediaItem, media_items: list[MediaItem], window_minutes: int = 5
) -> MediaItem | None:
    candidates = [(delta, item) for delta, item in _video_photo_candidates(video_item, media_items) if delta <= timedelta(minutes=window_minutes)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    best_delta = candidates[0][0]
    best = [photo for delta, photo in candidates if delta == best_delta]
    unique_keys = {canonical_model_key(photo.model_name) for photo in best if canonical_model_key(photo.model_name)}
    if len(unique_keys) != 1:
        return None
    return best[0]


def _video_photo_candidates(video_item: MediaItem, photo_items: list[MediaItem]) -> list[tuple[timedelta, MediaItem]]:
    if not video_item.captured_at:
        return []
    return [
        (abs(photo.captured_at - video_item.captured_at), photo)
        for photo in photo_items
        if photo.captured_at and canonical_model_key(photo.model_name)
    ]


def explain_video_model_failure(video_item: MediaItem, photo_items: list[MediaItem], window_minutes: int = 5) -> str:
    if not video_item.captured_at:
        return "영상 촬영 일시 없음"
    candidates = _video_photo_candidates(video_item, photo_items)
    label = "사진/영상"
    if not candidates:
        return f"같은 폴더에 촬영 일시와 모델명이 있는 {label} 없음"
    nearest = min(delta for delta, _ in candidates)
    if nearest > timedelta(minutes=window_minutes):
        return f"같은 폴더에 ±{window_minutes}분 이내 {label} 없음; 가장 가까운 {label}과 {nearest.total_seconds():g}초 차이"
    return f"가장 가까운 {label} 후보의 모델명이 서로 다름"


def _nearest_surrounding_photos(video_item: MediaItem, media_items: list[MediaItem]) -> list[MediaItem]:
    if video_item.captured_at is None:
        return []
    photos = [
        item for item in media_items
        if item.media_type == "photo"
        and item.source_path.parent == video_item.source_path.parent
        and item.captured_at is not None
        and canonical_model_key(item.model_name)
    ]
    before = [item for item in photos if item.captured_at <= video_item.captured_at]
    after = [item for item in photos if item.captured_at >= video_item.captured_at]
    nearest: list[MediaItem] = []
    if before:
        nearest_time = max(item.captured_at for item in before)
        nearest.extend(item for item in before if item.captured_at == nearest_time)
    if after:
        nearest_time = min(item.captured_at for item in after)
        nearest.extend(item for item in after if item.captured_at == nearest_time)
    return nearest


def find_video_model_candidate_unbounded_photos(video_item: MediaItem, media_items: list[MediaItem]) -> MediaItem | None:
    """Use the nearest known photos on each side only when their models agree."""
    nearest = _nearest_surrounding_photos(video_item, media_items)
    if not nearest or len({canonical_model_key(item.model_name) for item in nearest}) != 1:
        return None
    return min(nearest, key=lambda item: abs(item.captured_at - video_item.captured_at))


def explain_unbounded_photo_failure(video_item: MediaItem, media_items: list[MediaItem]) -> str:
    if video_item.captured_at is None:
        return "영상 촬영 일시 없음"
    if not _nearest_surrounding_photos(video_item, media_items):
        return "같은 폴더에 촬영 일시와 모델명이 있는 사진 없음"
    return "앞뒤 가장 가까운 사진 후보의 모델명이 서로 다름"


def sanitize_model_name(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "", value.replace(" ", "_"))
    if not sanitized:
        return "UNKNOWN"
    return "UNKNOWN" if sanitized.lower() == "unknown" else sanitized


def canonical_model_key(value: str | None) -> str:
    sanitized = sanitize_model_name(value)
    if sanitized == "UNKNOWN":
        return ""
    return re.sub(r"[^a-z0-9]+", "", sanitized.lower())


def _strip_seq_suffix(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"[_-]\d{4}$", "", value)


def _parse_date_time(date_text: str | None, time_text: str | None) -> datetime | None:
    if not date_text:
        return None
    try:
        if "-" in date_text and time_text:
            return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H.%M.%S")
        if time_text:
            return datetime.strptime(f"{date_text}{time_text}", "%Y%m%d%H%M%S")
        return datetime.strptime(date_text, "%Y%m%d")
    except ValueError:
        return None
