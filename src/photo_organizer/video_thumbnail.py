from __future__ import annotations

import subprocess
from pathlib import Path
from .process_utils import hidden_process_kwargs


def extract_video_thumbnail_bytes(path: Path, max_width: int = 640, seek_seconds: int = 1,
                                  timeout: float | None = None) -> bytes | None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(seek_seconds),
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={max_width}:-1:force_original_aspect_ratio=decrease",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    try:
        options = {'timeout': timeout} if timeout is not None else {}
        result = subprocess.run(command, capture_output=True, check=True, **hidden_process_kwargs(), **options)
    except Exception:
        return None
    return result.stdout or None
