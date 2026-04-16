from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from .models import MediaItem


FALLBACK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
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
        return parsed_at, sanitize_model_name(model) if model else None, label
    return None, None, "UNKNOWN"


def infer_video_model_from_photos(video_item: MediaItem, photo_items: list[MediaItem]) -> tuple[str | None, str]:
    if not video_item.captured_at:
        return None, "UNKNOWN"
    candidates: list[tuple[timedelta, MediaItem]] = []
    for photo in photo_items:
        if not photo.captured_at or not photo.model_name:
            continue
        delta = abs(photo.captured_at - video_item.captured_at)
        if delta <= timedelta(minutes=5):
            candidates.append((delta, photo))
    if not candidates:
        return None, "UNKNOWN"
    candidates.sort(key=lambda item: item[0])
    best_delta = candidates[0][0]
    best = [photo for delta, photo in candidates if delta == best_delta]
    unique_models = {photo.model_name for photo in best if photo.model_name}
    if len(unique_models) != 1:
        return None, "UNKNOWN"
    return unique_models.pop(), "영상 모델명 사진 추론"


def sanitize_model_name(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "", value.replace(" ", "_"))
    if not sanitized:
        return "UNKNOWN"
    return "UNKNOWN" if sanitized.lower() == "unknown" else sanitized


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
