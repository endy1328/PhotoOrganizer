import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import OrganizeRequest


class OutputSizeLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source_dir = self.base / 'source'
        self.source_dir.mkdir()
        self.source = self.source_dir / '20240101_120000_CAMERA.jpg'
        self.source.write_bytes(b'original')
        self.target = self.base / 'target'
        self.engine = OrganizerEngine(self.base)

    def request(self, **kwargs):
        return OrganizeRequest(self.source_dir, self.target, mobile_output_limit_enabled=True,
                               mobile_output_limit_mb=1, **kwargs)

    def fake_photo(self, *, target_path, **kwargs):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b'x' * self.size)

    def run_photo(self, size, request=None, edited=False):
        self.size = size
        request = request or self.request()
        bundle = self.engine.preview(request)
        if edited:
            self.engine.edit_preview_filename(bundle, bundle.preview_items[0].item_id, 'manual.jpg')
        with patch.object(self.engine, '_create_photo_mobile_output', side_effect=self.fake_photo):
            return self.engine.execute(request, preview_bundle=bundle)

    def test_boundary_and_below_for_photo(self):
        for size, expected in [(999999, 'SUCCESS'), (1000000, 'SIZE_EXCLUDED'), (1000001, 'SIZE_EXCLUDED')]:
            with self.subTest(size=size):
                request = self.request()
                request.target_path = self.base / str(size)
                result = self.run_photo(size, request).execution_results[0]
                self.assertEqual(result.status, 'SUCCESS')
                self.assertEqual(result.mobile_output_status, expected)
                self.assertEqual(Path(result.mobile_output_path).exists(), expected == 'SUCCESS')
                if expected == 'SIZE_EXCLUDED':
                    self.assertIn('1 MB', result.mobile_output_message)
                    self.assertFalse(Path(result.mobile_output_path).parent.exists())

    def test_exclusion_preserves_existing_output_and_regular_copy(self):
        request = self.request()
        preview = self.engine.preview(request)
        output = Path(preview.preview_items[0].mobile_output_path)
        output.parent.mkdir(parents=True)
        output.write_bytes(b'existing output')
        self.size = 1000000
        with patch.object(self.engine, '_create_photo_mobile_output', side_effect=self.fake_photo):
            result = self.engine.execute(request, preview_bundle=preview)
        self.assertEqual(output.read_bytes(), b'existing output')
        self.assertEqual(Path(result.execution_results[0].target_path).read_bytes(), b'original')
        self.assertEqual(len(result.delete_review_items), 1)
        self.assertTrue(any('용량 제한' in log.message for log in result.log_events))
        self.assertFalse(list(self.target.rglob('.photoorganizer_*')))

    def test_manual_move_exclusion_is_success_and_removes_source(self):
        result = self.run_photo(1000000, self.request(operation_mode='move'), edited=True)
        self.assertFalse(self.source.exists())
        self.assertEqual(result.execution_results[0].mobile_output_status, 'SIZE_EXCLUDED')
        self.assertEqual(Path(result.execution_results[0].target_path).read_bytes(), b'original')
        self.assertFalse(Path(result.execution_results[0].mobile_output_path).parent.exists())

    def test_disabled_keeps_large_output(self):
        request = OrganizeRequest(self.source_dir, self.target)
        result = self.run_photo(1000001, request).execution_results[0]
        self.assertEqual(result.mobile_output_status, 'SUCCESS')
        self.assertEqual(Path(result.mobile_output_path).stat().st_size, 1000001)

    def test_video_limit_and_skipped_precedence(self):
        for status in ['SUCCESS', 'SKIPPED']:
            with self.subTest(status=status):
                request = self.request()
                output = self.base / status / 'output_1' / 'video.mp4'
                output.parent.parent.mkdir()
                def video(**kwargs):
                    if status == 'SUCCESS':
                        kwargs['target_path'].write_bytes(b'x' * 1000000)
                    return status
                with patch('photo_organizer.engine.create_mobile_video_output', side_effect=video):
                    if status == 'SUCCESS':
                        with self.assertRaisesRegex(Exception, '용량 제한'):
                            self.engine._create_mobile_output(self.source, output, 'video', request)
                    else:
                        self.assertEqual(self.engine._create_mobile_output(self.source, output, 'video', request), 'SKIPPED')
                self.assertFalse(output.exists())
                self.assertFalse(output.parent.exists())

    def test_bad_enabled_limit_fails_before_writes(self):
        for limit in [0, -1, True, 1.5, '1', 1000001]:
            with self.subTest(limit=limit):
                request = self.request()
                request.mobile_output_limit_mb = limit
                preview = self.engine.preview(OrganizeRequest(self.source_dir, self.target))
                with self.assertRaises(ValueError):
                    self.engine.execute(request, preview_bundle=preview)
                self.assertFalse(self.target.exists())

    def test_exclusion_continues_next_file(self):
        (self.source_dir / '20240101_120001_CAMERA.jpg').write_bytes(b'next')
        result = self.run_photo(1000000)
        self.assertEqual(len(result.execution_results), 2)
        self.assertTrue(all(row.mobile_output_status == 'SIZE_EXCLUDED' for row in result.execution_results))
        self.assertFalse(result.error_items)

    def test_failed_conversion_cleans_temporary_and_preserves_existing(self):
        output = self.base / 'output_1' / 'photo.jpg'
        output.parent.mkdir()
        output.write_bytes(b'old')
        def fail(**kwargs):
            kwargs['target_path'].write_bytes(b'partial')
            raise RuntimeError('conversion failed')
        with patch.object(self.engine, '_create_photo_mobile_output', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'conversion failed'):
                self.engine._create_mobile_output(self.source, output, 'photo', self.request())
        self.assertEqual(output.read_bytes(), b'old')
        self.assertFalse(list(self.base.glob('.photoorganizer_*')))

    def test_excluded_does_not_apply_capture_times(self):
        with patch('photo_organizer.engine.set_capture_file_times') as times:
            self.run_photo(1000000)
        times.assert_not_called()

    def test_exclusive_accept_and_racing_existing_output(self):
        output = self.base / 'output_1' / 'manual.jpg'
        self.size = 999999
        with patch.object(self.engine, '_create_photo_mobile_output', side_effect=self.fake_photo):
            self.assertEqual(self.engine._create_mobile_output_exclusive(self.source, output, 'photo', self.request()), 'SUCCESS')
        self.assertEqual(output.stat().st_size, 999999)
        with self.assertRaises(FileExistsError):
            self.engine._create_mobile_output_exclusive(self.source, output, 'photo', self.request())
        self.assertEqual(output.stat().st_size, 999999)

    def test_success_without_staged_output_is_error(self):
        output = self.base / 'output_1' / 'video.mp4'
        with patch('photo_organizer.engine.create_mobile_video_output', return_value='SUCCESS'):
            with self.assertRaisesRegex(OSError, '파일이 없습니다'):
                self.engine._create_mobile_output(self.source, output, 'video', self.request())
        self.assertFalse(output.parent.exists())

    def test_actual_photo_uses_converted_size_not_source(self):
        from PIL import Image
        Image.new('RGB', (40, 40), 'red').save(self.source)
        with self.source.open('ab') as handle:
            handle.write(b'x' * 1000000)
        result = self.engine.execute(self.request()).execution_results[0]
        self.assertEqual(result.mobile_output_status, 'SUCCESS')
        self.assertLess(Path(result.mobile_output_path).stat().st_size, 1000000)

    def test_actual_large_png_is_excluded(self):
        from PIL import Image
        self.source.unlink()
        source = self.source.with_suffix('.png')
        Image.effect_noise((1800, 1800), 80).save(source)
        self.assertGreater(source.stat().st_size, 1000000)
        result = self.engine.execute(self.request()).execution_results[0]
        self.assertEqual(result.mobile_output_status, 'SIZE_EXCLUDED')
        self.assertFalse(Path(result.mobile_output_path).parent.exists())
        self.assertTrue(source.exists())
        self.assertTrue(Path(result.target_path).exists())

    def test_video_below_limit_is_published(self):
        output = self.base / 'output_1' / 'video.mp4'
        def video(**kwargs):
            kwargs['target_path'].write_bytes(b'x' * 999999)
            return 'SUCCESS'
        with patch('photo_organizer.engine.create_mobile_video_output', side_effect=video):
            status = self.engine._create_mobile_output(self.source, output, 'video', self.request())
        self.assertEqual(status, 'SUCCESS')
        self.assertEqual(output.stat().st_size, 999999)
        self.assertFalse(list(self.base.glob('.photoorganizer_*')))

    def test_real_video_helper_staging_and_cleanup(self):
        self.source.write_bytes(b'x' * 2000000)
        for size in [999999, 1000000, 2000000]:
            with self.subTest(size=size):
                output = self.base / f'video{size}' / 'clip.mp4'
                def ffmpeg(command, **kwargs):
                    Path(command[-1]).write_bytes(b'y' * size)
                    return subprocess.CompletedProcess(command, 0, b'', b'')
                with patch('photo_organizer.video_output.subprocess.run', side_effect=ffmpeg):
                    if size == 1000000:
                        with self.assertRaisesRegex(Exception, '용량 제한'):
                            self.engine._create_mobile_output(self.source, output, 'video', self.request())
                    else:
                        expected = 'SUCCESS' if size < 1000000 else 'SKIPPED'
                        self.assertEqual(self.engine._create_mobile_output(self.source, output, 'video', self.request()), expected)
                self.assertEqual(output.exists(), size < 1000000)
                self.assertFalse(list(self.base.glob('.photoorganizer_*')))
