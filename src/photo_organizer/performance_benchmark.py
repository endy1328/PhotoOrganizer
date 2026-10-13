"""Bounded output-only comparisons; never publish into an organizer job."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .models import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from .operation_control import OperationControl, OperationInterrupted
from .isolated_work import isolated_call, close_workers
from .video_output import create_mobile_video_output, get_last_video_encoder_report, resolve_video_encoder


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    elapsed: float
    success: bool
    error: str = ''


@dataclass(frozen=True)
class BenchmarkReport:
    cases: tuple[BenchmarkCase, ...]
    video_workers: int
    mixed_media_workers: bool
    notes: tuple[str, ...]


def recommend(cases):
    by_name = {case.name: case for case in cases}
    def faster(before, after):
        a, b = by_name.get(before), by_name.get(after)
        return bool(a and b and a.success and b.success and a.elapsed > 0 and b.elapsed < a.elapsed * .9)
    return (2 if faster('video_serial', 'video_parallel') else 1,
            faster('mixed_serial', 'mixed_parallel'))


def _photo(source, target, settings):
    isolated_call('photo', (source, target, settings.mobile_output_max_width,
                           settings.mobile_output_jpeg_quality,
                           settings.mobile_output_keep_smaller_original, settings.conversion_speed))


def _samples(source, control):
    video = photo = None
    # A bounded scan avoids a lengthy recursive preview merely to choose samples.
    for index, path in enumerate(source.rglob('*')):
        control.raise_if_interrupted()
        if index >= 1000:
            break
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if video is None and suffix in VIDEO_EXTENSIONS:
            video = path
        if photo is None and suffix in PHOTO_EXTENSIONS:
            photo = path
        if video and photo:
            break
    return video, photo


def run_benchmark(settings, source_path, target_path, video_path=None, photo_path=None,
                  control=None, progress_callback=None):
    control = control or OperationControl()
    source, target = Path(source_path), Path(target_path)
    if type(settings.photo_workers) is not int or settings.photo_workers not in {1, 2, 4}:
        raise ValueError('사진 동시 처리 수는 1, 2, 4개 중 선택하세요.')
    if not source.is_dir() or not target.is_dir():
        raise ValueError('존재하는 Source와 Target 디렉토리를 선택하세요.')
    with control.file_activity('benchmark-selection', source, '성능 테스트 샘플 선택'):
        auto_video, auto_photo = _samples(source, control) if video_path is None or photo_path is None else (None, None)
    video = Path(video_path) if video_path else auto_video
    photo = Path(photo_path) if photo_path else auto_photo
    if not video or not video.is_file() or video.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError('시험할 동영상 파일을 선택하세요. 자동 검색은 처음 1,000개 경로까지만 확인합니다.')
    if photo and (not photo.is_file() or photo.suffix.lower() not in PHOTO_EXTENSIONS):
        raise ValueError('지원되는 사진 파일을 선택하세요.')
    cases, encoder_reports = [], set()
    notes = ['동일 영상 앞 10초를 두 번 변환한 짧은 비교입니다. 캐시·발열·영상 구성에 따라 실제 속도는 달라집니다.',
             '현재 출력 설정을 사용하며 용량 제한과 작아질 때만 출력 정책은 시험에서 제외합니다.',
             '원본 정리 복사는 포함하지 않으므로 전체 실행 시간과 차이가 있습니다.']
    notes.append(f'영상 샘플: {video}')
    if photo:
        notes.append(f'사진 샘플: {photo}')
    # Availability probing happens before timers, otherwise the first trial
    # pays a one-time NVENC startup cost and biases the parallel recommendation.
    with control.file_activity('benchmark-encoder', video, '인코더 사용 가능 여부 확인'):
        backend = resolve_video_encoder(settings.video_encoder)
        control.raise_if_interrupted()
    notes.append(f"시험 인코더: {'NVIDIA NVENC' if backend == 'gpu' else 'CPU libx264'}")
    try:
        with TemporaryDirectory(prefix='.photoorganizer-benchmark-', dir=target) as temporary:
            root = Path(temporary)
            def task(kind, name, index):
                with control.file_activity(f'{name}-{kind}-{index}', video if kind == 'video' else photo, '성능 테스트'):
                    control.raise_if_interrupted()
                    destination = root / f'{name}-{kind}-{index}'
                    if kind == 'video':
                        destination = destination.with_suffix('.mp4')
                        status = create_mobile_video_output(video, destination,
                            settings.mobile_output_video_max_width, settings.mobile_output_video_quality,
                            False, settings.video_encoder, settings.conversion_speed, clip_seconds=10)
                        if status != 'SUCCESS' or not destination.is_file() or destination.stat().st_size == 0:
                            raise RuntimeError('유효한 시험 영상 출력이 생성되지 않았습니다.')
                        return get_last_video_encoder_report()
                    destination = destination.with_suffix('.png' if photo.suffix.lower() == '.png' else '.jpg')
                    _photo(photo, destination, settings)
                    if not destination.is_file() or destination.stat().st_size == 0:
                        raise RuntimeError('유효한 시험 사진 출력이 생성되지 않았습니다.')
                    return ''
            def case(name, video_workers, include_photo=False, mixed=False):
                control.raise_if_interrupted()
                if progress_callback:
                    progress_callback(name)
                started = perf_counter()
                errors = []
                with ThreadPoolExecutor(max_workers=video_workers + settings.photo_workers) as pool:
                    def collect(futures):
                        for future in futures:
                            try:
                                report = future.result()
                                if report:
                                    encoder_reports.add(report)
                            except OperationInterrupted:
                                raise
                            except Exception as exc:
                                errors.append(str(exc))
                    def videos():
                        for start in range(0, 2, video_workers):
                            collect([pool.submit(task, 'video', name, i) for i in range(start, min(2, start + video_workers))])
                    def photos():
                        for start in range(0, 4, settings.photo_workers):
                            collect([pool.submit(task, 'photo', name, i) for i in range(start, min(4, start + settings.photo_workers))])
                    if mixed:
                        # Dispatch coordinators separately: they do not consume media slots.
                        with ThreadPoolExecutor(max_workers=2) as coordinators:
                            collect([coordinators.submit(videos), coordinators.submit(photos)])
                    else:
                        videos()
                        if include_photo:
                            photos()
                control.raise_if_interrupted()
                cases.append(BenchmarkCase(name, perf_counter() - started, not errors, '; '.join(errors)))
            case('video_serial', 1)
            case('video_parallel', 2)
            workers, _ = recommend(cases)
            if photo:
                case('mixed_serial', workers, include_photo=True)
                case('mixed_parallel', workers, include_photo=True, mixed=True)
            else:
                notes.append('사진 샘플이 없어 사진·영상 혼합 성능은 측정하지 않았습니다.')
    finally:
        close_workers(control)
    notes.extend(sorted(encoder_reports))
    workers, mixed = recommend(cases)
    # Auto fallback can change backend under load. Such trials prove usability,
    # but are not evidence for recommending a more concurrent configuration.
    if any('CPU 재시도' in report for report in encoder_reports):
        workers, mixed = 1, False
        notes.append('GPU 실패 후 CPU 재시도가 발생하여 동시성 증가를 추천하지 않습니다.')
    return BenchmarkReport(tuple(cases), workers, mixed, tuple(notes))
