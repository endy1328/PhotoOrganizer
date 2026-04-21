from __future__ import annotations

import tomllib
from pathlib import Path

from .models import AppSettings


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
                source_path=str(app.get("source_path", "")),
                target_path=str(app.get("target_path", "")),
                device_name_override=str(app.get("device_name_override", "")),
                operation_mode=str(app.get("operation_mode", "copy")),
                mobile_output_enabled=bool(app.get("mobile_output_enabled", True)),
                mobile_output_max_width=int(app.get("mobile_output_max_width", 3000)),
                mobile_output_jpeg_quality=int(app.get("mobile_output_jpeg_quality", 75)),
                mobile_output_keep_smaller_original=bool(app.get("mobile_output_keep_smaller_original", True)),
            )
        except Exception:
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        content = "\n".join(
            [
                "[app]",
                f'source_path = {self._quote(settings.source_path)}',
                f'target_path = {self._quote(settings.target_path)}',
                f'device_name_override = {self._quote(settings.device_name_override)}',
                f'operation_mode = {self._quote(settings.operation_mode)}',
                f"mobile_output_enabled = {self._bool_literal(settings.mobile_output_enabled)}",
                f"mobile_output_max_width = {settings.mobile_output_max_width}",
                f"mobile_output_jpeg_quality = {settings.mobile_output_jpeg_quality}",
                f"mobile_output_keep_smaller_original = {self._bool_literal(settings.mobile_output_keep_smaller_original)}",
                "",
            ]
        )
        self.config_path.write_text(content, encoding="utf-8")

    def _load_legacy_json(self) -> AppSettings | None:
        if not self.legacy_config_path.exists():
            return None
        try:
            import json

            data = json.loads(self.legacy_config_path.read_text(encoding="utf-8"))
            return AppSettings(**data)
        except Exception:
            return None

    def _quote(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _bool_literal(self, value: bool) -> str:
        return "true" if value else "false"
