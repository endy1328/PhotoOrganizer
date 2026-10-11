import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.process_utils import hidden_process_kwargs
from photo_organizer.metadata import MetadataExtractor
from photo_organizer.models import MediaItem
from photo_organizer.video_output import create_mobile_video_output
from photo_organizer.video_thumbnail import extract_video_thumbnail_bytes


class BackgroundProcessTests(unittest.TestCase):
    def assert_hidden(self, kwargs):
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertTrue(kwargs['capture_output'])
        self.assertTrue(kwargs['check'])
        self.assertNotIn('shell', kwargs)
        if sys.platform == 'win32':
            self.assertEqual(kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            info = kwargs['startupinfo']
            self.assertTrue(info.dwFlags & subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(info.wShowWindow, subprocess.SW_HIDE)

    def test_non_windows_options_do_not_use_windows_flags(self):
        with patch('photo_organizer.process_utils.os.name', 'posix'):
            options = hidden_process_kwargs()
        self.assertEqual(options, {'stdin': subprocess.DEVNULL})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows startup information')
    def test_windows_options_are_independent_mutable_instances(self):
        first = hidden_process_kwargs()
        second = hidden_process_kwargs()
        self.assertEqual(first['creationflags'], subprocess.CREATE_NO_WINDOW)
        self.assertIsNot(first['startupinfo'], second['startupinfo'])

    def test_ffprobe_uses_hidden_options_and_preserves_arguments(self):
        payload = json.dumps({'format': {'tags': {'creation_time': '2024-01-01T12:00:00', 'model': 'CAM'}}}).encode()
        item = MediaItem(Path('sample.mp4'), 'video', '.mp4')
        with patch('photo_organizer.metadata.subprocess.run', return_value=subprocess.CompletedProcess([], 0, payload)) as run, patch('photo_organizer.metadata.MediaInfo', None):
            MetadataExtractor()._extract_video_metadata(item)
        self.assertEqual(run.call_args.args[0], ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', 'sample.mp4'])
        self.assert_hidden(run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'], 60)
        self.assertEqual(item.model_name, 'CAM')

    def test_video_conversion_uses_hidden_options_and_same_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'source.mov', root / 'target.mp4'
            source.write_bytes(b'original')
            def complete(command, **kwargs):
                Path(command[-1]).write_bytes(b'encoded')
                return subprocess.CompletedProcess(command, 0, b'', b'')
            with patch('photo_organizer.video_output.subprocess.run', side_effect=complete) as run:
                status = create_mobile_video_output(source, target, 1280, 'balanced', False)
            self.assertEqual(status, 'SUCCESS')
            self.assertEqual(target.read_bytes(), b'encoded')
            self.assert_hidden(run.call_args.kwargs)
            command = run.call_args.args[0]
            self.assertEqual(command[0], 'ffmpeg')
            self.assertEqual(command[command.index('-crf') + 1], '24')
            self.assertEqual(command[command.index('-b:a') + 1], '128k')

    def test_video_thumbnail_uses_hidden_options_and_retains_png_pipe(self):
        with patch('photo_organizer.video_thumbnail.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'png')) as run:
            self.assertEqual(extract_video_thumbnail_bytes(Path('sample.mp4')), b'png')
        self.assert_hidden(run.call_args.kwargs)
        self.assertEqual(run.call_args.args[0][-3:], ['-vcodec', 'png', '-'])


if __name__ == '__main__':
    unittest.main()
