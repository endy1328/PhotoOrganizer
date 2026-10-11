from __future__ import annotations

import os
import logging
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from .process_utils import hidden_process_kwargs


_encoder_report = threading.local()


def clear_video_encoder_report() -> None:
    """Clear this worker's evidence before an item can fail ahead of conversion."""
    _encoder_report.message = ""


def get_last_video_encoder_report() -> str:
    """The calling worker's most recent conversion report; safe across workers."""
    return getattr(_encoder_report, "message", "")


VIDEO_QUALITY_PRESETS: dict[str, dict[str, str]] = {
    "very_high": {
        "crf": "18", "audio_bitrate": "192k", "label": "매우 높음",
        "description": "세부 묘사와 화질을 우선합니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
    "high_plus": {
        "crf": "20", "audio_bitrate": "192k", "label": "높음+",
        "description": "높은 화질과 용량 사이에서 절충합니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
    "high": {
        "crf": "22", "audio_bitrate": "160k", "label": "높음",
        "description": "화질을 우선하면서 파일 용량도 고려합니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
    "balanced": {
        "crf": "24", "audio_bitrate": "128k", "label": "균형",
        "description": "화질과 용량을 균형 있게 조절하는 기본 설정입니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
    "compact": {
        "crf": "26", "audio_bitrate": "128k", "label": "용량 절약",
        "description": "균형보다 용량 절약을 우선합니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
    "small": {
        "crf": "28", "audio_bitrate": "96k", "label": "최대 용량 절약",
        "description": "파일 용량 절약을 가장 우선합니다. 파일 크기는 영상 길이와 장면에 따라 달라집니다.",
    },
}


def normalize_video_quality(value: object) -> str:
    return value if isinstance(value, str) and value in VIDEO_QUALITY_PRESETS else "balanced"


def video_quality_display_label(value: object) -> str:
    key = normalize_video_quality(value)
    preset = VIDEO_QUALITY_PRESETS[key]
    label = preset["label"] + (" (기본)" if key == "balanced" else "")
    return f"{label} — CRF {preset['crf']} / 오디오 {preset['audio_bitrate'][:-1]} kbps"


def _process_error_detail(exc: BaseException) -> str:
    stderr = getattr(exc, "stderr", None)
    return (stderr.decode("utf-8", errors="replace").strip()
            if isinstance(stderr, bytes) else str(stderr or exc))


@lru_cache(maxsize=1)
def get_gpu_encoder_capability() -> tuple[bool, str]:
    """Check the driver with a real, bounded encode; listing encoders is insufficient."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=c=black:s=320x240:r=30", "-frames:v", "1",
               "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
               "-b:v", "0", "-cq", "24", "-pix_fmt", "yuv420p", "-f", "null", "-"]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=10,
                       **hidden_process_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        return False, _process_error_detail(exc)
    return True, "NVIDIA NVENC H.264 실제 인코딩 확인"


def resolve_video_encoder(encoder: str) -> str:
    if encoder not in {"cpu", "auto", "gpu"}:
        raise ValueError(f"지원하지 않는 영상 인코더: {encoder}")
    if encoder == "cpu":
        return "cpu"
    usable, detail = get_gpu_encoder_capability()
    if usable:
        return "gpu"
    if encoder == "gpu":
        raise RuntimeError(f"NVIDIA NVENC GPU 인코더를 사용할 수 없습니다: {detail}")
    logging.getLogger(__name__).info("GPU 인코더 미사용, CPU 선택: %s", detail)
    return "cpu"


def create_mobile_video_output(
    source_path: Path,
    target_path: Path,
    max_width: int,
    quality: str,
    only_if_smaller: bool,
    encoder: str = "cpu",
    speed: str = "balanced",
) -> str:
    clear_video_encoder_report()
    if speed not in {"quality", "balanced", "fast"}:
        raise ValueError(f"지원하지 않는 변환 속도: {speed}")
    try:
        backend = resolve_video_encoder(encoder)
    except RuntimeError as exc:
        _encoder_report.message = str(exc)
        raise
    report_details = []
    if encoder == "auto" and backend == "cpu":
        report_details.append(f"GPU 사용 불가, CPU 선택: {get_gpu_encoder_capability()[1]}")
    preset = VIDEO_QUALITY_PRESETS[normalize_video_quality(quality)]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f"{target_path.stem}.tmp{target_path.suffix}")
    if temp_path.exists():
        temp_path.unlink()
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-map_metadata",
        "0",
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        preset["audio_bitrate"],
    ]
    if max_width > 0:
        command.extend(["-vf", f"scale='min({max_width},iw)':-2"])
    command.append(str(temp_path))
    def encode(selected: str) -> None:
        if selected == "gpu":
            # CQ and CPU CRF share profile ordering, not an identical quality scale.
            options = ["-c:v", "h264_nvenc", "-preset",
                       {"quality": "p7", "balanced": "p5", "fast": "p3"}[speed],
                       "-rc", "vbr", "-b:v", "0", "-cq", preset["crf"]]
        else:
            options = ["-c:v", "libx264", "-preset",
                       {"quality": "slow", "balanced": "medium", "fast": "fast"}[speed],
                       "-crf", preset["crf"]]
        logging.getLogger(__name__).info("영상 출력 인코더=%s 속도=%s 품질=%s 파일=%s",
                                         selected, speed, normalize_video_quality(quality), source_path)
        _encoder_report.message = "; ".join(report_details + [
            f"인코더={'NVIDIA NVENC' if selected == 'gpu' else 'CPU libx264'} / 속도={speed} / 품질={normalize_video_quality(quality)}"])
        subprocess.run(command[:-1] + options + command[-1:], capture_output=True,
                       check=True, **hidden_process_kwargs())
    try:
        encode(backend)
    except (OSError, subprocess.SubprocessError) as exc:
        temp_path.unlink(missing_ok=True)
        if encoder == "auto" and backend == "gpu":
            original_detail = _process_error_detail(exc)
            report_details.append(f"GPU 변환 실패 후 CPU 재시도: {original_detail}")
            logging.getLogger(__name__).warning("GPU 변환 실패, CPU로 한 번 재시도: %s", original_detail)
            try:
                encode("cpu")
            except (OSError, subprocess.SubprocessError) as cpu_exc:
                temp_path.unlink(missing_ok=True)
                _encoder_report.message += f"; CPU 실패: {_process_error_detail(cpu_exc)}"
                raise RuntimeError(f"동영상 모바일 출력 실패: GPU: {original_detail}; CPU: {_process_error_detail(cpu_exc)}") from cpu_exc
        elif isinstance(exc, FileNotFoundError):
            _encoder_report.message += f"; 변환 실패: {_process_error_detail(exc)}"
            raise RuntimeError("ffmpeg가 설치되어 있지 않아 동영상 모바일 출력을 생성할 수 없습니다.") from exc
        else:
            _encoder_report.message += f"; 변환 실패: {_process_error_detail(exc)}"
            raise RuntimeError(f"동영상 모바일 출력 실패(ffmpeg): {_process_error_detail(exc)}") from exc
    if only_if_smaller:
        try:
            if temp_path.stat().st_size >= source_path.stat().st_size:
                temp_path.unlink(missing_ok=True)
                return "SKIPPED"
        except OSError:
            pass
    os.replace(temp_path, target_path)
    return "SUCCESS"
