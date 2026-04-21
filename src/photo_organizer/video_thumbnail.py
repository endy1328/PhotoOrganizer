from __future__ import annotations

import subprocess
from pathlib import Path


def extract_video_thumbnail_bytes(path: Path, max_width: int = 640, seek_seconds: int = 1) -> bytes | None:
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
        result = subprocess.run(command, capture_output=True, check=True)
    except Exception:
        return None
    return result.stdout or None
