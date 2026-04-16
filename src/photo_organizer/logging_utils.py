from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .models import LogEvent


class AppLogger:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_old_logs(self, retention_days: int = 30) -> None:
        cutoff = datetime.now() - timedelta(days=retention_days)
        for path in self.logs_dir.glob("*.jsonl"):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                    path.unlink()
            except OSError:
                continue

    def write_session_log(self, events: list[LogEvent]) -> Path:
        self.cleanup_old_logs()
        log_path = self.logs_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        lines = [json.dumps(asdict(event), ensure_ascii=False) for event in events]
        log_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return log_path
