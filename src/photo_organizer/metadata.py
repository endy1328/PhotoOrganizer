from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .fallback import parse_filename_fallback, sanitize_model_name
from .models import PHOTO_EXTENSIONS, MediaItem

try:
    import exifread  # type: ignore
except Exception:
    exifread = None

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None

try:
    import piexif  # type: ignore
except Exception:
    piexif = None

try:
    from pymediainfo import MediaInfo  # type: ignore
except Exception:
    MediaInfo = None


class MetadataExtractor:
    def extract(self, path: Path) -> MediaItem:
        media_type = "photo" if path.suffix.lower() in PHOTO_EXTENSIONS else "video"
        item = MediaItem(source_path=path, media_type=media_type, extension=path.suffix.lower())
        if media_type == "photo":
            self._extract_photo_metadata(item)
        else:
            self._extract_video_metadata(item)
        self._apply_filename_fallback(item)
        return item

    def _extract_photo_metadata(self, item: MediaItem) -> None:
        if exifread is not None:
            try:
                with item.source_path.open("rb") as stream:
                    tags = exifread.process_file(stream, details=False)
                self._apply_photo_tags(item, tags)
            except Exception as exc:
                item.warnings.append(f"사진 메타 추출 실패(exifread): {exc}")
        if (item.captured_at is None or not item.model_name) and Image is not None:
            try:
                with Image.open(item.source_path) as image:
                    exif = image.getexif() or {}
                self._apply_pillow_exif(item, exif)
            except Exception as exc:
                item.warnings.append(f"사진 메타 추출 실패(Pillow): {exc}")

    def _extract_video_metadata(self, item: MediaItem) -> None:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(item.source_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            self._apply_ffprobe_metadata(item, json.loads(result.stdout))
        except Exception as exc:
            item.warnings.append(f"영상 메타 추출 실패(ffprobe): {exc}")
        if (item.captured_at is None or not item.model_name) and MediaInfo is not None:
            try:
                self._apply_mediainfo(item, MediaInfo.parse(str(item.source_path)).to_data())
            except Exception as exc:
                item.warnings.append(f"영상 메타 추출 실패(pymediainfo): {exc}")

    def _apply_filename_fallback(self, item: MediaItem) -> None:
        fallback_at, fallback_model, fallback_source = parse_filename_fallback(item.source_path.name)
        if item.captured_at is None and fallback_at is not None:
            item.captured_at = fallback_at
            item.datetime_source = "파일명 fallback"
        if not item.model_name and fallback_model:
            item.model_name = fallback_model
            item.model_source = "파일명 fallback"
        if fallback_source != "UNKNOWN":
            item.metadata["filename_pattern"] = fallback_source

    def _apply_photo_tags(self, item: MediaItem, tags: dict[str, Any]) -> None:
        self._record_source_metadata(item, "exifread", tags)
        for tag_name in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
            value = tags.get(tag_name)
            parsed = _parse_exif_datetime(str(value)) if value else None
            if parsed:
                item.captured_at = parsed
                item.datetime_source = "사진 메타"
                break
        model = tags.get("Image Model")
        if model:
            item.model_name = sanitize_model_name(str(model))
            item.model_source = "사진 메타"

    def _apply_pillow_exif(self, item: MediaItem, exif: Any) -> None:
        if not exif or piexif is None:
            return
        try:
            exif_dict = piexif.load(exif.tobytes())
        except Exception:
            return
        self._record_source_metadata(item, "pillow", exif_dict)
        candidates = [
            exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal),
            exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeDigitized),
            exif_dict.get("0th", {}).get(piexif.ImageIFD.DateTime),
        ]
        for raw in candidates:
            if not raw:
                continue
            value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            parsed = _parse_exif_datetime(value)
            if parsed:
                item.captured_at = parsed
                item.datetime_source = "사진 메타"
                break
        raw_model = exif_dict.get("0th", {}).get(piexif.ImageIFD.Model)
        if raw_model:
            text = raw_model.decode("utf-8") if isinstance(raw_model, bytes) else str(raw_model)
            item.model_name = sanitize_model_name(text)
            item.model_source = "사진 메타"

    def _apply_ffprobe_metadata(self, item: MediaItem, data: dict[str, Any]) -> None:
        tags: dict[str, Any] = data.get("format", {}).get("tags", {}) or {}
        for stream in data.get("streams", []):
            tags = {**stream.get("tags", {}), **tags}
        self._record_source_metadata(item, "ffprobe", tags)
        for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
            parsed = _parse_video_datetime(tags.get(key))
            if parsed:
                item.captured_at = parsed
                item.datetime_source = "영상 메타"
                break
        model = tags.get("com.apple.quicktime.model") or tags.get("model")
        if model and "unknown" not in str(model).lower():
            item.model_name = sanitize_model_name(str(model))
            item.model_source = "영상 메타"

    def _apply_mediainfo(self, item: MediaItem, data: dict[str, Any]) -> None:
        snapshot: list[dict[str, Any]] = []
        for track in data.get("tracks", []):
            snapshot.append(
                {
                    "track_type": track.get("@type") or track.get("track_type") or "",
                    "encoded_date": track.get("encoded_date"),
                    "tagged_date": track.get("tagged_date"),
                    "recorded_date": track.get("recorded_date"),
                    "model": track.get("model"),
                }
            )
            parsed = _parse_video_datetime(
                track.get("encoded_date") or track.get("tagged_date") or track.get("recorded_date")
            )
            if parsed and item.captured_at is None:
                item.captured_at = parsed
                item.datetime_source = "영상 메타"
            model = track.get("model")
            if model and not item.model_name:
                item.model_name = sanitize_model_name(str(model))
                item.model_source = "영상 메타"
        self._record_source_metadata(item, "mediainfo", snapshot)

    def _record_source_metadata(self, item: MediaItem, source: str, value: Any) -> None:
        metadata = item.metadata.setdefault("source_metadata", {})
        metadata[source] = _freeze_metadata_value(value)


def _parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _parse_video_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = str(value).replace("UTC ", "").replace("Z", "+00:00").strip()
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _freeze_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _freeze_metadata_value(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_freeze_metadata_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_freeze_metadata_value(item) for item in value), key=repr)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
