from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv"}
SUPPORTED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass(slots=True)
class AppSettings:
    source_path: str = ""
    target_path: str = ""
    device_name_override: str = ""
    operation_mode: str = "copy"
    mobile_output_enabled: bool = True
    mobile_output_max_width: int = 3000
    mobile_output_jpeg_quality: int = 75
    mobile_output_keep_smaller_original: bool = True
    mobile_output_video_max_width: int = 1280
    mobile_output_video_quality: str = "balanced"
    mobile_output_video_only_if_smaller: bool = True
    mobile_output_limit_enabled: bool = False
    mobile_output_limit_mb: int = 500
    video_model_window_minutes: int = 5
    phone_conflict_policy: str = "overwrite"
    phone_video_limit_enabled: bool = False
    phone_video_limit_mb: int = 500
    model_name_mappings: dict[str, str] = field(default_factory=dict)
    model_mapping_scope: str = "filename_and_folders"
    restore_last_job: bool = True
    autosave_job_changes: bool = True
    video_encoder: str = "auto"
    conversion_speed: str = "balanced"
    photo_workers: int = 2
    video_workers: int = 1
    mixed_media_workers: bool = False


@dataclass(slots=True)
class OrganizeRequest:
    source_path: Path
    target_path: Path
    device_name_override: str = ""
    operation_mode: str = "copy"
    preview_only: bool = True
    mobile_output_enabled: bool = True
    mobile_output_max_width: int = 3000
    mobile_output_jpeg_quality: int = 75
    mobile_output_keep_smaller_original: bool = True
    mobile_output_video_max_width: int = 1280
    mobile_output_video_quality: str = "balanced"
    mobile_output_video_only_if_smaller: bool = True
    mobile_output_limit_enabled: bool = False
    mobile_output_limit_mb: int = 500
    video_model_window_minutes: int = 5
    model_name_mappings: dict[str, str] = field(default_factory=dict)
    model_mapping_scope: str = "filename_and_folders"
    video_encoder: str = "auto"
    conversion_speed: str = "balanced"
    photo_workers: int = 2
    video_workers: int = 1
    mixed_media_workers: bool = False


@dataclass(slots=True)
class MediaItem:
    source_path: Path
    media_type: str
    extension: str
    captured_at: datetime | None = None
    datetime_source: str = "UNKNOWN"
    model_name: str | None = None
    model_source: str = "UNKNOWN"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.captured_at is not None


@dataclass(slots=True)
class PreviewItem:
    item_id: str
    media_type: str
    source_path: str
    target_directory: str
    target_path: str
    new_filename: str
    write_mode: str
    captured_at: str
    datetime_source: str
    model_name: str
    model_source: str
    warnings: list[str]
    metadata_entries: list[tuple[str, str]] = field(default_factory=list)
    mobile_output_enabled: bool = False
    mobile_output_path: str = ""
    status: str = "READY"
    filename_edited: bool = False
    included: bool = True
    output_model_name: str = ""
    folder_model_name: str = ""
    file_selected: bool = True


@dataclass(slots=True)
class ErrorItem:
    source_path: str
    message: str
    media_type: str = "UNKNOWN"


@dataclass(slots=True)
class ExecutionResult:
    source_path: str
    target_path: str
    status: str
    action: str
    write_mode: str = "NEW"
    message: str = ""
    mobile_output_path: str = ""
    mobile_output_status: str = ""
    mobile_output_message: str = ""


@dataclass(slots=True)
class DeleteReviewItem:
    item_id: str
    delete_path: str
    reason: str
    selected: bool = True


@dataclass(slots=True)
class LogEvent:
    level: str
    message: str
    source_path: str = ""
    target_path: str = ""


@dataclass(slots=True)
class PreviewBundle:
    preview_items: list[PreviewItem] = field(default_factory=list)
    error_items: list[ErrorItem] = field(default_factory=list)
    log_events: list[LogEvent] = field(default_factory=list)
    media_items: list[MediaItem] = field(default_factory=list)
    selection_applied: bool = False
    model_name_mappings: dict[str, str] = field(default_factory=dict)
    model_mapping_scope: str = "filename_and_folders"

    # None denotes pre-feature snapshots: model selection is derived from included.
    selected_models: list[str] | None = None


@dataclass(slots=True)
class ExecutionBundle:
    preview_items: list[PreviewItem] = field(default_factory=list)
    execution_results: list[ExecutionResult] = field(default_factory=list)
    error_items: list[ErrorItem] = field(default_factory=list)
    delete_review_items: list[DeleteReviewItem] = field(default_factory=list)
    log_events: list[LogEvent] = field(default_factory=list)
