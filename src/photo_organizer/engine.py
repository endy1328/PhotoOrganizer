from __future__ import annotations

import ctypes
import shutil
from pathlib import Path
from typing import Callable, Iterable

try:
    from send2trash import send2trash  # type: ignore
except Exception:
    send2trash = None

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None

try:
    from PIL import PngImagePlugin  # type: ignore
except Exception:
    PngImagePlugin = None

from .fallback import infer_video_model_from_photos, sanitize_model_name
from .logging_utils import AppLogger
from .metadata import MetadataExtractor
from .models import (
    DeleteReviewItem,
    ErrorItem,
    ExecutionBundle,
    ExecutionResult,
    LogEvent,
    MediaItem,
    OrganizeRequest,
    PreviewBundle,
    PreviewItem,
    SUPPORTED_EXTENSIONS,
)


class OrganizerEngine:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.extractor = MetadataExtractor()
        self.logger = AppLogger(self.base_dir)

    def preview(
        self,
        request: OrganizeRequest,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> PreviewBundle:
        self._report_progress(progress_callback, "파일 스캔 중", 0, 0)
        items = self._scan_media_files(request.source_path, request.target_path)
        total_items = len(items)
        self._report_progress(progress_callback, "메타데이터 읽는 중", 0, total_items)
        media_items: list[MediaItem] = []
        for index, path in enumerate(items, start=1):
            media_items.append(self.extractor.extract(path))
            self._report_progress(progress_callback, "메타데이터 읽는 중", index, total_items)
        self._report_progress(progress_callback, "영상 모델명 정리 중", 0, total_items)
        self._infer_video_models(media_items)
        self._apply_device_name_override(media_items, request.device_name_override)
        self._report_progress(progress_callback, "미리보기 생성 중", 0, total_items)
        preview_items, error_items, log_events = self._build_preview(media_items, request.target_path, request)
        self._report_progress(progress_callback, "미리보기 완료", total_items, total_items)
        return PreviewBundle(preview_items=preview_items, error_items=error_items, log_events=log_events)

    def execute(
        self,
        request: OrganizeRequest,
        progress_callback: Callable[[str, int, int], None] | None = None,
        preview_bundle: PreviewBundle | None = None,
    ) -> ExecutionBundle:
        if preview_bundle is None:
            preview_bundle = self.preview(request, progress_callback=progress_callback)
        results: list[ExecutionResult] = []
        delete_review_items: list[DeleteReviewItem] = []
        log_events = list(preview_bundle.log_events)
        total_items = len(preview_bundle.preview_items)
        self._report_progress(progress_callback, "파일 정리 실행 중", 0, total_items)
        for index, preview_item in enumerate(preview_bundle.preview_items, start=1):
            source = Path(preview_item.source_path)
            target = Path(preview_item.target_path)
            try:
                if preview_item.write_mode == "CONFLICT":
                    raise FileExistsError("날짜 기준 고정 SEQ 파일명이 이미 존재합니다.")
                target.parent.mkdir(parents=True, exist_ok=True)
                if request.operation_mode == "move":
                    if preview_item.write_mode == "OVERWRITE" and target.exists():
                        target.unlink()
                    shutil.move(str(source), str(target))
                    action = "move"
                    mobile_output_source = target
                else:
                    shutil.copy2(str(source), str(target))
                    action = "copy"
                    mobile_output_source = source
                mobile_output_status = ""
                if preview_item.mobile_output_enabled and preview_item.mobile_output_path:
                    self._create_mobile_output(
                        source_path=mobile_output_source,
                        target_path=Path(preview_item.mobile_output_path),
                        max_width=request.mobile_output_max_width,
                        jpeg_quality=request.mobile_output_jpeg_quality,
                        keep_smaller_original=request.mobile_output_keep_smaller_original,
                    )
                    mobile_output_status = "SUCCESS"
                if request.operation_mode == "copy":
                    delete_review_items.append(
                        DeleteReviewItem(
                            item_id=preview_item.item_id,
                            delete_path=str(source),
                            reason="복사 완료 후 원본 정리 후보",
                        )
                    )
                results.append(
                    ExecutionResult(
                        source_path=str(source),
                        target_path=str(target),
                        status="SUCCESS",
                        action=action,
                        write_mode=preview_item.write_mode,
                        message=preview_item.write_mode,
                        mobile_output_path=preview_item.mobile_output_path,
                        mobile_output_status=mobile_output_status,
                    )
                )
                log_events.append(
                    LogEvent(
                        level="INFO",
                        message=f"{action.upper()} {preview_item.write_mode} 성공",
                        source_path=str(source),
                        target_path=str(target),
                    )
                )
            except Exception as exc:
                results.append(
                    ExecutionResult(
                        source_path=str(source),
                        target_path=str(target),
                        status="ERROR",
                        action=request.operation_mode,
                        write_mode=preview_item.write_mode,
                        message=str(exc),
                        mobile_output_path=preview_item.mobile_output_path,
                        mobile_output_status="ERROR" if preview_item.mobile_output_enabled and preview_item.mobile_output_path else "",
                    )
                )
                preview_bundle.error_items.append(ErrorItem(source_path=str(source), message=str(exc)))
                log_events.append(LogEvent(level="ERROR", message=f"실행 실패: {exc}", source_path=str(source), target_path=str(target)))
                if preview_item.mobile_output_enabled and preview_item.mobile_output_path:
                    break
            self._report_progress(progress_callback, "파일 정리 실행 중", index, total_items)
        self.logger.write_session_log(log_events)
        self._report_progress(progress_callback, "실행 완료", total_items, total_items)
        return ExecutionBundle(
            preview_items=preview_bundle.preview_items,
            execution_results=results,
            error_items=preview_bundle.error_items,
            delete_review_items=delete_review_items,
            log_events=log_events,
        )

    def delete_selected(self, items: Iterable[DeleteReviewItem]) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for item in items:
            if not item.selected:
                continue
            path = Path(item.delete_path)
            try:
                self._move_to_recycle_bin(path)
                results.append(
                    ExecutionResult(
                        source_path=str(path),
                        target_path="",
                        status="SUCCESS",
                        action="delete_review",
                        write_mode="DELETE",
                        message="휴지통 이동 완료",
                    )
                )
            except Exception as exc:
                results.append(
                    ExecutionResult(
                        source_path=str(path),
                        target_path="",
                        status="ERROR",
                        action="delete_review",
                        write_mode="DELETE",
                        message=str(exc),
                    )
                )
        if results:
            self.logger.write_session_log(
                [LogEvent(level="INFO" if r.status == "SUCCESS" else "ERROR", message=f"삭제 리뷰 {r.status}", source_path=r.source_path) for r in results]
            )
        return results

    def describe_media_path(self, path: Path) -> list[tuple[str, str]]:
        if not path.exists() or not path.is_file():
            return []
        try:
            item = self.extractor.extract(path)
        except Exception:
            return []
        return self._build_metadata_entries(item)

    def _scan_media_files(self, source_path: Path, target_path: Path | None = None) -> list[Path]:
        source_resolved = source_path.resolve()
        target_resolved = target_path.resolve() if target_path else None
        paths: list[Path] = []
        for path in source_path.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
                if target_resolved and (resolved == target_resolved or target_resolved in resolved.parents):
                    continue
                if resolved == source_resolved:
                    continue
            except Exception:
                pass
            paths.append(path)
        return sorted(paths)

    def _infer_video_models(self, media_items: list[MediaItem]) -> None:
        photos_by_dir: dict[Path, list[MediaItem]] = {}
        for item in media_items:
            if item.media_type == "photo" and item.captured_at and item.model_name:
                photos_by_dir.setdefault(item.source_path.parent, []).append(item)
        for item in media_items:
            if item.media_type != "video" or item.model_name:
                continue
            model, source = infer_video_model_from_photos(item, photos_by_dir.get(item.source_path.parent, []))
            if model:
                item.model_name = model
                item.model_source = source
            else:
                item.model_name = "UNKNOWN"
                item.model_source = "UNKNOWN"
                item.warnings.append("영상 모델명 추론 실패")

    def _apply_device_name_override(self, media_items: list[MediaItem], device_name_override: str) -> None:
        override_name = sanitize_model_name(device_name_override)
        if not device_name_override.strip() or override_name == "UNKNOWN":
            return
        for item in media_items:
            item.model_name = override_name
            item.model_source = "사용자 입력"

    def _build_preview(
        self,
        media_items: list[MediaItem],
        target_root: Path,
        request: OrganizeRequest,
    ) -> tuple[list[PreviewItem], list[ErrorItem], list[LogEvent]]:
        preview_items: list[PreviewItem] = []
        error_items: list[ErrorItem] = []
        log_events: list[LogEvent] = []
        sequence_counters: dict[Path, int] = {}
        ordered_items = sorted(
            media_items,
            key=lambda item: (
                item.captured_at or item.source_path.name,
                str(item.source_path).lower(),
            ),
        )
        for item in ordered_items:
            if not item.captured_at:
                message = "촬영 일시를 메타데이터와 파일명에서 모두 찾지 못했습니다."
                error_items.append(ErrorItem(source_path=str(item.source_path), message=message, media_type=item.media_type))
                log_events.append(LogEvent(level="WARNING", message=message, source_path=str(item.source_path)))
                continue
            model_name = sanitize_model_name(item.model_name)
            target_dir = self._build_target_directory(target_root, item.captured_at, model_name)
            seq = self._next_sequence_for_directory(target_dir, sequence_counters)
            self._remember_next_sequence(target_dir, seq + 1, sequence_counters)
            target_filename, write_mode = self._build_target_filename(item, target_dir, seq)
            target_path = target_dir / target_filename
            mobile_output_path = ""
            if request.mobile_output_enabled and item.media_type == "photo":
                mobile_output_path = str(self._build_mobile_output_path(target_dir, target_filename))
            warnings = list(item.warnings)
            if model_name == "UNKNOWN":
                warnings.append("모델명 UNKNOWN 사용")
            if write_mode == "CONFLICT":
                warnings.append("날짜 기준 고정 SEQ가 이미 사용 중인 파일과 충돌합니다.")
            preview_items.append(
                PreviewItem(
                    item_id=str(item.source_path),
                    media_type=item.media_type,
                    source_path=str(item.source_path),
                    target_directory=str(target_dir),
                    target_path=str(target_path),
                    new_filename=target_filename,
                    write_mode=write_mode,
                    captured_at=item.captured_at.isoformat(sep=" "),
                    datetime_source=item.datetime_source,
                    model_name=model_name,
                    model_source=item.model_source,
                    warnings=warnings,
                    metadata_entries=self._build_metadata_entries(item),
                    mobile_output_enabled=request.mobile_output_enabled and item.media_type == "photo",
                    mobile_output_path=mobile_output_path,
                )
            )
            log_events.append(LogEvent(level="INFO", message="미리보기 생성", source_path=str(item.source_path), target_path=str(target_path)))
        return preview_items, error_items, log_events

    def _build_target_directory(self, target_root: Path, captured_at, model_name: str) -> Path:
        day_dir = f"{captured_at:%Y%m%d}"
        model_dir = f"{day_dir}_{sanitize_model_name(model_name)}"
        return target_root / f"{captured_at:%Y}년" / f"{captured_at:%Y}년 {captured_at:%m}월" / day_dir / model_dir

    def _build_target_filename(
        self,
        item: MediaItem,
        target_dir: Path,
        seq: int,
    ) -> tuple[str, str]:
        captured_at = item.captured_at
        assert captured_at is not None
        model_name = sanitize_model_name(item.model_name)
        prefix = f"{captured_at:%Y%m%d_%H%M%S}_{model_name}"
        ext = item.extension
        candidate = f"{prefix}_{seq:04d}{ext}"
        candidate_path = target_dir / candidate
        if candidate_path.exists():
            if self._can_overwrite(item, candidate_path):
                return candidate, "OVERWRITE"
            return candidate, "CONFLICT"
        return candidate, "NEW"

    def _build_mobile_output_path(self, target_dir: Path, target_filename: str) -> Path:
        output_dir = target_dir / f"output_{target_dir.name}"
        source_suffix = Path(target_filename).suffix
        if source_suffix.lower() == ".heic":
            mobile_name = f"{Path(target_filename).stem}{self._jpg_suffix_for(source_suffix)}"
        else:
            mobile_name = target_filename
        return output_dir / mobile_name

    def _jpg_suffix_for(self, source_suffix: str) -> str:
        suffix_body = source_suffix[1:] if source_suffix.startswith(".") else source_suffix
        if suffix_body.isupper():
            return ".JPG"
        if suffix_body.islower():
            return ".jpg"
        return ".jpg"

    def _create_mobile_output(
        self,
        source_path: Path,
        target_path: Path,
        max_width: int,
        jpeg_quality: int,
        keep_smaller_original: bool,
    ) -> None:
        if Image is None:
            raise RuntimeError("Pillow가 설치되어 있지 않아 모바일 출력을 생성할 수 없습니다.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            exif_bytes = self._extract_exif_bytes(image)
            icc_profile = image.info.get("icc_profile")
            pnginfo = self._extract_pnginfo(image)
            image.load()
            working = image.copy()
        if working.mode not in ("RGB", "RGBA", "L"):
            working = working.convert("RGB")
        if working.width > max_width:
            new_height = max(1, int(round(working.height * (max_width / working.width))))
            working = working.resize((max_width, new_height), Image.Resampling.LANCZOS)
        elif not keep_smaller_original and working.width != max_width:
            new_height = max(1, int(round(working.height * (max_width / working.width))))
            working = working.resize((max_width, new_height), Image.Resampling.LANCZOS)
        suffix = target_path.suffix.lower()
        save_kwargs: dict[str, object] = {}
        if suffix in {".jpg", ".jpeg"}:
            if working.mode in ("RGBA", "LA"):
                background = Image.new("RGB", working.size, (255, 255, 255))
                background.paste(working, mask=working.getchannel("A"))
                working = background
            elif working.mode != "RGB":
                working = working.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": jpeg_quality, "optimize": True}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        elif suffix == ".png":
            save_kwargs = {"format": "PNG", "optimize": True, "compress_level": 9}
            if pnginfo is not None:
                save_kwargs["pnginfo"] = pnginfo
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        else:
            if working.mode in ("RGBA", "LA"):
                background = Image.new("RGB", working.size, (255, 255, 255))
                background.paste(working, mask=working.getchannel("A"))
                working = background
            elif working.mode != "RGB":
                working = working.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": jpeg_quality, "optimize": True}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        working.save(target_path, **save_kwargs)

    def _extract_exif_bytes(self, image) -> bytes | None:
        try:
            exif = image.getexif()
        except Exception:
            exif = None
        if exif:
            try:
                exif_bytes = exif.tobytes()
                if exif_bytes:
                    return exif_bytes
            except Exception:
                pass
        raw_exif = image.info.get("exif")
        if isinstance(raw_exif, bytes) and raw_exif:
            return raw_exif
        return None

    def _extract_pnginfo(self, image):
        if PngImagePlugin is None:
            return None
        text_keys = {
            key: value
            for key, value in image.info.items()
            if isinstance(value, str) and key not in {"exif", "icc_profile"}
        }
        if not text_keys:
            return None
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in text_keys.items():
            pnginfo.add_text(key, value)
        return pnginfo

    def _next_sequence_for_directory(self, target_dir: Path, sequence_counters: dict[Path, int] | None = None) -> int:
        if sequence_counters is None:
            return 1
        return sequence_counters.get(target_dir, 1)

    def _remember_next_sequence(
        self,
        target_dir: Path,
        next_seq: int,
        sequence_counters: dict[Path, int] | None = None,
    ) -> None:
        if sequence_counters is None:
            return
        current = sequence_counters.get(target_dir, 1)
        sequence_counters[target_dir] = max(current, next_seq)

    def _can_overwrite(self, source_item: MediaItem, target_path: Path) -> bool:
        if not target_path.is_file():
            return False
        if source_item.extension.lower() != target_path.suffix.lower():
            return False
        try:
            source_size = source_item.source_path.stat().st_size
            target_size = target_path.stat().st_size
        except OSError:
            return False
        if source_size != target_size:
            return False
        source_metadata = source_item.metadata.get("source_metadata")
        if not source_metadata:
            return False
        try:
            target_item = self.extractor.extract(target_path)
        except Exception:
            return False
        target_metadata = target_item.metadata.get("source_metadata")
        if not target_metadata:
            return False
        return source_metadata == target_metadata

    def _build_metadata_entries(self, item: MediaItem) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        media_info = item.metadata.get("media_info", {})
        display_metadata = item.metadata.get("display_metadata", {})
        source_metadata = item.metadata.get("source_metadata", {})
        file_size = self._safe_file_size(item.source_path)

        entries.append(("미디어 종류", "사진" if item.media_type == "photo" else "영상"))
        entries.append(("확장자", item.extension or "-"))
        entries.append(("파일 크기", self._format_file_size(file_size) if file_size is not None else "-"))
        resolution = self._format_resolution(media_info)
        if resolution:
            entries.append(("원본 크기", resolution))
        entries.append(("추출된 촬영/생성 일시", item.captured_at.strftime("%Y-%m-%d %H:%M:%S") if item.captured_at else "-"))
        entries.append(("추출된 모델명", sanitize_model_name(item.model_name)))
        entries.append(("일시 출처", item.datetime_source or "-"))
        entries.append(("모델명 출처", item.model_source or "-"))
        entries.append(("메타 추출 도구", self._format_metadata_tools(source_metadata, item)))

        if item.media_type == "photo":
            self._append_if_present(entries, "EXIF Make", display_metadata.get("photo_make"))
            self._append_if_present(entries, "EXIF Model", display_metadata.get("photo_model"))
            self._append_if_present(entries, "EXIF DateTimeOriginal", display_metadata.get("photo_datetime_original"))
            self._append_if_present(entries, "EXIF DateTimeDigitized", display_metadata.get("photo_datetime_digitized"))
            self._append_if_present(entries, "Orientation", display_metadata.get("photo_orientation"))
        else:
            self._append_if_present(entries, "생성 시각 메타", display_metadata.get("video_creation_time"))
            self._append_if_present(entries, "Video Codec", media_info.get("video_codec"))
            self._append_if_present(entries, "Audio Codec", media_info.get("audio_codec"))
            self._append_if_present(entries, "Duration", self._format_duration(media_info.get("duration_seconds")))
            self._append_if_present(entries, "Frame Rate", media_info.get("frame_rate"))

        return [(label, value if value not in ("", None) else "-") for label, value in entries]

    def _append_if_present(self, entries: list[tuple[str, str]], label: str, value: object) -> None:
        if value in (None, ""):
            return
        entries.append((label, str(value)))

    def _safe_file_size(self, path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _format_file_size(self, size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        unit = units[0]
        for candidate in units:
            unit = candidate
            if value < 1024 or candidate == units[-1]:
                break
            value /= 1024
        if unit == "B":
            return f"{int(value)} {unit}"
        return f"{value:.1f} {unit}"

    def _format_resolution(self, media_info: object) -> str | None:
        if not isinstance(media_info, dict):
            return None
        width = media_info.get("width")
        height = media_info.get("height")
        if width in (None, "") or height in (None, ""):
            return None
        return f"{width} x {height}"

    def _format_metadata_tools(self, source_metadata: object, item: MediaItem) -> str:
        if not isinstance(source_metadata, dict):
            return "파일명 fallback" if item.metadata.get("filename_pattern") else "-"
        tool_map = {
            "exifread": "exifread",
            "pillow": "Pillow",
            "ffprobe": "ffprobe",
            "mediainfo": "pymediainfo",
        }
        tools = [tool_map.get(key, key) for key in source_metadata.keys()]
        if item.metadata.get("filename_pattern"):
            tools.append("파일명 fallback")
        return ", ".join(tools) if tools else "-"

    def _format_duration(self, raw_seconds: object) -> str | None:
        if raw_seconds in (None, ""):
            return None
        try:
            total_seconds = float(str(raw_seconds))
        except (TypeError, ValueError):
            return str(raw_seconds)
        minutes, seconds = divmod(int(round(total_seconds)), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _move_to_recycle_bin(self, path: Path) -> None:
        if send2trash is not None:
            send2trash(str(path))
            return
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        operation = SHFILEOPSTRUCTW()
        operation.wFunc = 3
        operation.pFrom = str(path) + "\0\0"
        operation.fFlags = 0x0040 | 0x0010 | 0x0400
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0:
            raise OSError(f"휴지통 이동 실패: {result}")

    def _report_progress(
        self,
        progress_callback: Callable[[str, int, int], None] | None,
        message: str,
        current: int,
        total: int,
    ) -> None:
        if progress_callback is not None:
            progress_callback(message, current, total)


def human_reason(preview_item: PreviewItem) -> str:
    parts = [preview_item.datetime_source, preview_item.model_source]
    return " / ".join(part for part in parts if part and part != "UNKNOWN") or "UNKNOWN"
