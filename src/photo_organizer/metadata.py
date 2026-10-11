from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .fallback import parse_filename_fallback, sanitize_model_name
from .models import PHOTO_EXTENSIONS, MediaItem
from .process_utils import hidden_process_kwargs

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
        item = MediaItem(source_path=path, media_type=media_type, extension=path.suffix)
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
                    self._set_media_info(item, "width", image.width)
                    self._set_media_info(item, "height", image.height)
                    if image.format:
                        self._set_media_info(item, "container_format", str(image.format))
                    exif = image.getexif() or {}
                self._apply_pillow_exif(item, exif)
            except Exception as exc:
                item.warnings.append(f"사진 메타 추출 실패(Pillow): {exc}")

    def _extract_video_metadata(self, item: MediaItem) -> None:
        tools: dict[str, dict[str, str]] = {}
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(item.source_path),
                ],
                capture_output=True,
                check=True,
                timeout=60,
                **hidden_process_kwargs(),
            )
            output = result.stdout
            if not output or not output.strip():
                raise ValueError("ffprobe JSON 출력이 없습니다. 실행 파일과 실행 환경을 확인하세요.")
            if isinstance(output, bytes):
                output = output.decode("utf-8-sig", errors="replace")
            try:
                data = json.loads(output)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"ffprobe JSON 해석 실패: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("ffprobe JSON 최상위 값이 객체가 아닙니다.")
            self._apply_ffprobe_metadata(item, data)
            tools["ffprobe"] = {"status": "success", "detail": ""}
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or b""
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            message = f"종료 코드 {exc.returncode}; {detail.strip()[:500]}"
            tools["ffprobe"] = {"status": "error", "detail": message}
            item.warnings.append(f"영상 메타 추출 실패(ffprobe): {message}")
        except FileNotFoundError as exc:
            tools["ffprobe"] = {"status": "unavailable", "detail": str(exc)}
            item.warnings.append(f"영상 메타 추출 실패(ffprobe): {exc}")
        except Exception as exc:
            tools["ffprobe"] = {"status": "error", "detail": str(exc)}
            item.warnings.append(f"영상 메타 추출 실패(ffprobe): {exc}")
        if item.captured_at is not None and item.model_name:
            tools["mediainfo"] = {"status": "not_needed", "detail": "ffprobe에서 일시와 모델명을 확인함"}
        elif MediaInfo is None:
            tools["mediainfo"] = {"status": "unavailable", "detail": "pymediainfo를 사용할 수 없음"}
        else:
            try:
                self._apply_mediainfo(item, MediaInfo.parse(str(item.source_path)).to_data())
                tools["mediainfo"] = {"status": "success", "detail": ""}
            except Exception as exc:
                tools["mediainfo"] = {"status": "error", "detail": str(exc)}
                item.warnings.append(f"영상 메타 추출 실패(pymediainfo): {exc}")
        # 원본에서 직접 확인한 값만 기록한다. 이후 파일명/사진/사용자 보완과 분리한다.
        direct_model = item.metadata.get("display_metadata", {}).get("video_model")
        status = "found" if direct_model else "not_found" if any(
            tool["status"] == "success" for tool in tools.values()
        ) else "failed"
        item.metadata["video_model_lookup"] = {"status": status, "model": direct_model, "tools": tools}

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
        datetime_original = tags.get("EXIF DateTimeOriginal")
        if datetime_original:
            self._set_display_metadata(item, "photo_datetime_original", str(datetime_original))
        datetime_digitized = tags.get("EXIF DateTimeDigitized")
        if datetime_digitized:
            self._set_display_metadata(item, "photo_datetime_digitized", str(datetime_digitized))
        make = tags.get("Image Make")
        if make:
            self._set_display_metadata(item, "photo_make", str(make))
        model = tags.get("Image Model")
        if model:
            item.model_name = sanitize_model_name(str(model))
            item.model_source = "사진 메타"
            self._set_display_metadata(item, "photo_model", str(model))
        orientation = tags.get("Image Orientation")
        if orientation:
            self._set_display_metadata(item, "photo_orientation", str(orientation))

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
            self._set_display_metadata(item, "photo_model", text)
        raw_make = exif_dict.get("0th", {}).get(piexif.ImageIFD.Make)
        if raw_make:
            text = raw_make.decode("utf-8") if isinstance(raw_make, bytes) else str(raw_make)
            self._set_display_metadata(item, "photo_make", text)
        raw_orientation = exif_dict.get("0th", {}).get(piexif.ImageIFD.Orientation)
        if raw_orientation:
            self._set_display_metadata(item, "photo_orientation", str(raw_orientation))
        original = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if original:
            text = original.decode("utf-8") if isinstance(original, bytes) else str(original)
            self._set_display_metadata(item, "photo_datetime_original", text)
        digitized = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeDigitized)
        if digitized:
            text = digitized.decode("utf-8") if isinstance(digitized, bytes) else str(digitized)
            self._set_display_metadata(item, "photo_datetime_digitized", text)

    def _apply_ffprobe_metadata(self, item: MediaItem, data: dict[str, Any]) -> None:
        tags: dict[str, Any] = data.get("format", {}).get("tags", {}) or {}
        streams = data.get("streams", [])
        for stream in streams:
            tags = {**stream.get("tags", {}), **tags}
        self._record_source_metadata(item, "ffprobe", tags)
        format_info = data.get("format", {}) or {}
        duration = format_info.get("duration")
        if duration is not None:
            self._set_media_info(item, "duration_seconds", str(duration))
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        if video_stream:
            width = video_stream.get("width")
            height = video_stream.get("height")
            if width is not None:
                self._set_media_info(item, "width", width)
            if height is not None:
                self._set_media_info(item, "height", height)
            codec = video_stream.get("codec_name")
            if codec:
                self._set_media_info(item, "video_codec", str(codec))
            frame_rate = _simplify_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
            if frame_rate:
                self._set_media_info(item, "frame_rate", frame_rate)
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if audio_stream and audio_stream.get("codec_name"):
            self._set_media_info(item, "audio_codec", str(audio_stream.get("codec_name")))
        for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
            parsed = _parse_video_datetime(tags.get(key))
            if parsed:
                item.captured_at = parsed
                item.datetime_source = "영상 메타"
                break
        creation_time = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate") or tags.get("date")
        if creation_time:
            self._set_display_metadata(item, "video_creation_time", str(creation_time))
        # 빈 값/UNKNOWN 컨테이너 태그가 유효한 스트림 모델을 가리지 않도록 따로 탐색한다.
        model = _find_video_model([
            format_info.get("tags", {}) or {},
            *(stream.get("tags", {}) or {} for stream in streams),
        ])
        if model:
            item.model_name = sanitize_model_name(str(model))
            item.model_source = "영상 메타"
            self._set_display_metadata(item, "video_model", str(model))

    def _apply_mediainfo(self, item: MediaItem, data: dict[str, Any]) -> None:
        snapshot: list[dict[str, Any]] = []
        tracks = data.get("tracks", [])
        model = _find_video_model(tracks)
        if model and (not item.model_name or item.model_name == "UNKNOWN"):
            item.model_name = sanitize_model_name(str(model))
            item.model_source = "영상 메타"
            self._set_display_metadata(item, "video_model", str(model))
        for track in tracks:
            snapshot.append(
                {
                    "track_type": track.get("@type") or track.get("track_type") or "",
                    "encoded_date": track.get("encoded_date"),
                    "tagged_date": track.get("tagged_date"),
                    "recorded_date": track.get("recorded_date"),
                    "model": _find_video_model([track]),
                }
            )
            parsed = _parse_video_datetime(
                track.get("encoded_date") or track.get("tagged_date") or track.get("recorded_date")
            )
            if parsed and item.captured_at is None:
                item.captured_at = parsed
                item.datetime_source = "영상 메타"
            if (track.get("@type") or track.get("track_type")) == "Video":
                width = track.get("width")
                height = track.get("height")
                if width is not None and item.metadata.get("media_info", {}).get("width") is None:
                    self._set_media_info(item, "width", width)
                if height is not None and item.metadata.get("media_info", {}).get("height") is None:
                    self._set_media_info(item, "height", height)
                frame_rate = track.get("frame_rate")
                if frame_rate and item.metadata.get("media_info", {}).get("frame_rate") is None:
                    self._set_media_info(item, "frame_rate", str(frame_rate))
                codec = track.get("codec_id") or track.get("format")
                if codec and item.metadata.get("media_info", {}).get("video_codec") is None:
                    self._set_media_info(item, "video_codec", str(codec))
            if (track.get("@type") or track.get("track_type")) == "Audio":
                codec = track.get("codec_id") or track.get("format")
                if codec and item.metadata.get("media_info", {}).get("audio_codec") is None:
                    self._set_media_info(item, "audio_codec", str(codec))
            duration = track.get("duration")
            if duration and item.metadata.get("media_info", {}).get("duration_seconds") is None:
                self._set_media_info(item, "duration_seconds", str(duration))
        self._record_source_metadata(item, "mediainfo", snapshot)

    def _record_source_metadata(self, item: MediaItem, source: str, value: Any) -> None:
        metadata = item.metadata.setdefault("source_metadata", {})
        metadata[source] = _freeze_metadata_value(value)

    def _set_display_metadata(self, item: MediaItem, key: str, value: Any) -> None:
        if value in (None, ""):
            return
        metadata = item.metadata.setdefault("display_metadata", {})
        metadata[key] = _freeze_metadata_value(value)

    def _set_media_info(self, item: MediaItem, key: str, value: Any) -> None:
        if value in (None, ""):
            return
        metadata = item.metadata.setdefault("media_info", {})
        metadata[key] = _freeze_metadata_value(value)


def _find_video_model(sources: list[dict[str, Any]]) -> str | None:
    """명시적 모델 태그 우선. 실제 파일에서 확인된 기기 encoder만 보조로 허용한다."""
    keys = (
        "com.apple.quicktime.model", "model", "camera_model", "device_model",
        "recorded_hardware_model_name",
    )
    for source in sources:
        normalized = {str(key).casefold(): value for key, value in source.items()}
        for key in keys:
            value = normalized.get(key)
            if not isinstance(value, str):
                continue
            value = value.strip()
            if value and "unknown" not in value.casefold() and sanitize_model_name(value) != "UNKNOWN":
                return value
    # An encoder usually names software. Accept only verified, exact device identities.
    verified_encoders = {"djiosmoaction4": "DJI OsmoAction4"}
    for source in sources:
        for key, value in source.items():
            if str(key).casefold() == "encoder" and isinstance(value, str):
                model = verified_encoders.get("".join(value.split()).casefold())
                if model:
                    return model
    return None


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
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
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


def _simplify_frame_rate(value: Any) -> str | None:
    if value in (None, "", "0/0"):
        return None
    text = str(value)
    if "/" not in text:
        return text
    try:
        numerator_text, denominator_text = text.split("/", maxsplit=1)
        numerator = float(numerator_text)
        denominator = float(denominator_text)
        if denominator == 0:
            return None
        frame_rate = numerator / denominator
    except (TypeError, ValueError):
        return text
    if frame_rate.is_integer():
        return f"{int(frame_rate)} fps"
    return f"{frame_rate:.3f}".rstrip("0").rstrip(".") + " fps"
