from __future__ import annotations

import tomllib
import os
import tempfile
from pathlib import Path

from .models import AppSettings
from .video_output import normalize_video_quality
from .model_mapping import (
    normalize_loaded_model_mappings,
    normalize_model_mapping_scope,
    validate_model_mappings,
)


class ConfigManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.config_path = self.base_dir / "config.toml"
        self.legacy_config_path = self.base_dir / "settings.json"

    def load(self) -> AppSettings:
        if not self.config_path.exists():
            legacy = self._load_legacy_json()
            if legacy is not None:
                self.save(legacy)
                return legacy
            return AppSettings()
        try:
            data = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
            app = data.get("app", {})
            return AppSettings(
                video_encoder=self._choice(app.get('video_encoder'), {'auto', 'cpu', 'gpu'}, 'auto'),
                conversion_speed=self._choice(app.get('conversion_speed'), {'quality', 'balanced', 'fast'}, 'balanced'),
                photo_workers=self._photo_workers(app.get('photo_workers')),
                video_workers=self._video_workers(app.get('video_workers')),
                mixed_media_workers=self._phone_video_enabled(app.get('mixed_media_workers', False)),
                source_path=str(app.get("source_path", "")),
                target_path=str(app.get("target_path", "")),
                device_name_override=str(app.get("device_name_override", "")),
                operation_mode=str(app.get("operation_mode", "copy")),
                mobile_output_enabled=bool(app.get("mobile_output_enabled", True)),
                mobile_output_max_width=int(app.get("mobile_output_max_width", 3000)),
                mobile_output_jpeg_quality=int(app.get("mobile_output_jpeg_quality", 75)),
                mobile_output_keep_smaller_original=bool(app.get("mobile_output_keep_smaller_original", True)),
                mobile_output_video_max_width=int(app.get("mobile_output_video_max_width", 1280)),
                mobile_output_video_quality=normalize_video_quality(app.get("mobile_output_video_quality", "balanced")),
                restore_last_job=self._job_preference(app.get("restore_last_job", True)),
                autosave_job_changes=self._job_preference(app.get("autosave_job_changes", True)),
                mobile_output_video_only_if_smaller=bool(app.get("mobile_output_video_only_if_smaller", True)),
                mobile_output_limit_enabled=self._phone_video_enabled(app.get("mobile_output_limit_enabled", False)),
                mobile_output_limit_mb=self._phone_video_mb(app.get("mobile_output_limit_mb", 500)),
                video_model_window_minutes=self._model_window(app.get("video_model_window_minutes", 5)),
                phone_conflict_policy=self._phone_policy(app.get("phone_conflict_policy", "overwrite")),
                phone_video_limit_enabled=self._phone_video_enabled(app.get("phone_video_limit_enabled", False)),
                phone_video_limit_mb=self._phone_video_mb(app.get("phone_video_limit_mb", 500)),
                model_name_mappings=normalize_loaded_model_mappings(data.get("model_name_mappings", {})),
                model_mapping_scope=normalize_model_mapping_scope(app.get("model_mapping_scope")),
            )
        except Exception:
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        mappings = validate_model_mappings(settings.model_name_mappings)
        content = "\n".join(
            [
                "[app]",
                f"video_encoder = {self._quote(self._choice(settings.video_encoder, {'auto', 'cpu', 'gpu'}, 'auto'))}",
                f"conversion_speed = {self._quote(self._choice(settings.conversion_speed, {'quality', 'balanced', 'fast'}, 'balanced'))}",
                f"photo_workers = {self._photo_workers(settings.photo_workers)}",
                f"video_workers = {self._video_workers(settings.video_workers)}",
                f"mixed_media_workers = {self._bool_literal(self._phone_video_enabled(settings.mixed_media_workers))}",
                f"restore_last_job = {self._bool_literal(self._job_preference(settings.restore_last_job))}",
                f"autosave_job_changes = {self._bool_literal(self._job_preference(settings.autosave_job_changes))}",
                f'source_path = {self._quote(settings.source_path)}',
                f'target_path = {self._quote(settings.target_path)}',
                f'device_name_override = {self._quote(settings.device_name_override)}',
                f'operation_mode = {self._quote(settings.operation_mode)}',
                f"mobile_output_enabled = {self._bool_literal(settings.mobile_output_enabled)}",
                f"mobile_output_max_width = {settings.mobile_output_max_width}",
                f"mobile_output_jpeg_quality = {settings.mobile_output_jpeg_quality}",
                f"mobile_output_keep_smaller_original = {self._bool_literal(settings.mobile_output_keep_smaller_original)}",
                f"mobile_output_video_max_width = {settings.mobile_output_video_max_width}",
                f"mobile_output_video_quality = {self._quote(normalize_video_quality(settings.mobile_output_video_quality))}",
                f"mobile_output_video_only_if_smaller = {self._bool_literal(settings.mobile_output_video_only_if_smaller)}",
                f"mobile_output_limit_enabled = {self._bool_literal(self._phone_video_enabled(settings.mobile_output_limit_enabled))}",
                f"mobile_output_limit_mb = {self._phone_video_mb(settings.mobile_output_limit_mb)}",
                f"video_model_window_minutes = {self._model_window(settings.video_model_window_minutes)}",
                f"phone_conflict_policy = {self._quote(self._phone_policy(settings.phone_conflict_policy))}",
                f"phone_video_limit_enabled = {self._bool_literal(self._phone_video_enabled(settings.phone_video_limit_enabled))}",
                f"phone_video_limit_mb = {self._phone_video_mb(settings.phone_video_limit_mb)}",
                f"model_mapping_scope = {self._quote(normalize_model_mapping_scope(settings.model_mapping_scope))}",
                "",
                "[model_name_mappings]",
                *(f"{self._quote(source)} = {self._quote(alias)}" for source, alias in mappings.items()),
                "",
            ]
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.config_path.parent,
                prefix=".config-", suffix=".tmp", delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
            os.replace(temporary_path, self.config_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _load_legacy_json(self) -> AppSettings | None:
        if not self.legacy_config_path.exists():
            return None
        try:
            import json

            data = json.loads(self.legacy_config_path.read_text(encoding="utf-8"))
            settings = AppSettings(**data)
            settings.video_encoder = self._choice(settings.video_encoder, {'auto', 'cpu', 'gpu'}, 'auto')
            settings.conversion_speed = self._choice(settings.conversion_speed, {'quality', 'balanced', 'fast'}, 'balanced')
            settings.photo_workers = self._photo_workers(settings.photo_workers)
            settings.video_workers = self._video_workers(settings.video_workers)
            settings.mixed_media_workers = self._phone_video_enabled(settings.mixed_media_workers)
            settings.restore_last_job = self._job_preference(settings.restore_last_job)
            settings.autosave_job_changes = self._job_preference(settings.autosave_job_changes)
            settings.mobile_output_video_quality = normalize_video_quality(settings.mobile_output_video_quality)
            settings.video_model_window_minutes = self._model_window(settings.video_model_window_minutes)
            settings.phone_conflict_policy = self._phone_policy(settings.phone_conflict_policy)
            settings.phone_video_limit_enabled = self._phone_video_enabled(settings.phone_video_limit_enabled)
            settings.phone_video_limit_mb = self._phone_video_mb(settings.phone_video_limit_mb)
            settings.mobile_output_limit_enabled = self._phone_video_enabled(settings.mobile_output_limit_enabled)
            settings.mobile_output_limit_mb = self._phone_video_mb(settings.mobile_output_limit_mb)
            settings.model_name_mappings = normalize_loaded_model_mappings(settings.model_name_mappings)
            settings.model_mapping_scope = normalize_model_mapping_scope(settings.model_mapping_scope)
            return settings
        except Exception:
            return None

    def _quote(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _bool_literal(self, value: bool) -> str:
        return "true" if value else "false"

    @staticmethod
    def _choice(value: object, choices: set[str], default: str) -> str:
        return value if type(value) is str and value in choices else default

    @staticmethod
    def _photo_workers(value: object) -> int:
        return value if type(value) is int and value in {1, 2, 4} else 2

    @staticmethod
    def _video_workers(value: object) -> int:
        return value if type(value) is int and value in {1, 2} else 1

    @staticmethod
    def _job_preference(value: object) -> bool:
        return value if type(value) is bool else True

    @staticmethod
    def _model_window(value: object) -> int:
        return value if type(value) is int and 0 <= value <= 1440 else 5

    @staticmethod
    def _phone_policy(value: object) -> str:
        return value if isinstance(value, str) and value in ("overwrite", "skip", "rename") else "overwrite"

    @staticmethod
    def _phone_video_enabled(value: object) -> bool:
        return value if type(value) is bool else False

    @staticmethod
    def _phone_video_mb(value: object) -> int:
        return value if type(value) is int and 1 <= value <= 1000000 else 500
