"""A single read-only selection request; QPixmap remains in the GUI thread."""
from pathlib import Path
import json
import subprocess

from PySide6.QtCore import QThread, Signal, QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from ..engine import OrganizerEngine
from ..metadata import MetadataExtractor
from ..models import VIDEO_EXTENSIONS
from ..video_thumbnail import extract_video_thumbnail_bytes
from ..process_utils import hidden_process_kwargs


class ReadOnlyMetadataExtractor(MetadataExtractor):
    """Bound external video reads; conversion's full metadata policy is unchanged."""
    def _extract_video_metadata(self, item):
        tools = {'mediainfo': {'status': 'not_needed', 'detail': '작업 중 조회에서는 시간 제한이 있는 ffprobe를 사용합니다.'}}
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json',
                                     '-show_format', '-show_streams', str(item.source_path)],
                                    capture_output=True, check=True, timeout=15, **hidden_process_kwargs())
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                raise ValueError('ffprobe JSON 최상위 값이 객체가 아닙니다.')
            self._apply_ffprobe_metadata(item, data)
            tools['ffprobe'] = {'status': 'success', 'detail': ''}
        except Exception as exc:
            tools['ffprobe'] = {'status': 'error', 'detail': str(exc)}
            item.warnings.append(f'영상 메타 조회 실패(ffprobe): {exc}')
        direct = item.metadata.get('display_metadata', {}).get('video_model')
        item.metadata['video_model_lookup'] = {'status': 'found' if direct else
                                               'not_found' if tools['ffprobe']['status'] == 'success' else 'failed',
                                               'model': direct, 'tools': tools}


class ReadOnlyInspector(OrganizerEngine):
    """Use the engine's pure metadata presentation methods without file/log writers."""
    def __init__(self):
        self.extractor = ReadOnlyMetadataExtractor()


class BusyDetailWorker(QThread):
    result_ready = Signal(object)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request

    @staticmethod
    def read(request):
        token, path, fingerprint, size, cached, metadata = request
        image = QImage()
        entries = list(cached) if cached is not None else []
        error = ''
        try:
            if metadata and cached is None:
                entries = ReadOnlyInspector().describe_media_path(path)
                if path.suffix.lower() in VIDEO_EXTENSIONS:
                    entries.append(('작업 중 조회', 'ffprobe로 조회합니다(최대 15초). MediaInfo 보조 조회는 작업 후 사용할 수 있습니다.'))
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                payload = extract_video_thumbnail_bytes(path, max_width=max(240, size.width()), timeout=15)
                if payload:
                    image.loadFromData(payload, 'PNG')
            else:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                original = reader.size()
                if original.isValid():
                    reader.setScaledSize(original.scaled(size, Qt.KeepAspectRatio))
                image = reader.read()
        except Exception as exc:
            error = str(exc)
        try:
            after = path.stat()
            actual = (after.st_size, after.st_mtime_ns)
        except OSError:
            actual = None
        return token, path, fingerprint, actual, entries, image, error

    def run(self):
        if not self.isInterruptionRequested():
            self.result_ready.emit(self.read(self.request))
