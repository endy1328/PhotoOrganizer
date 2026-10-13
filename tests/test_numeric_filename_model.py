import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from photo_organizer.fallback import parse_filename_fallback
from photo_organizer.metadata import MetadataExtractor
from photo_organizer.models import MediaItem, OrganizeRequest
from photo_organizer.engine import OrganizerEngine


class NumericFilenameModelTests(unittest.TestCase):
    def test_numeric_suffixes_do_not_supply_models_but_keep_timestamp(self):
        for suffix in ('02', '99', '0001', '02_0028', '02-99'):
            for extension in ('mp4', 'jpg'):
                with self.subTest(suffix=suffix, extension=extension):
                    captured, model, label = parse_filename_fallback(f'20240929_103347_{suffix}.{extension}')
                    self.assertEqual(captured, datetime(2024, 9, 29, 10, 33, 47))
                    self.assertIsNone(model)
                    self.assertEqual(label, 'YYYYMMDD_HHMMSS_NUMERIC_SUFFIX')

    def test_named_models_and_their_output_sequence_remain_supported(self):
        for model in ('SM-F926N', 'Galaxy_Z_Fold6', 'DJI_OsmoAction4', 'CAM-02'):
            self.assertEqual(parse_filename_fallback(f'20240929_103347_{model}_0028.mp4')[1], model)

    def test_numeric_suffix_records_notice_without_overriding_metadata(self):
        extractor = MetadataExtractor()
        for model, source in ((None, 'UNKNOWN'), ('1234', '영상 메타'), ('SM-F926N', '영상 메타')):
            with self.subTest(model=model):
                item = MediaItem(Path('sample/20240929_103347_02.mp4'), 'video', '.mp4', model_name=model, model_source=source)
                extractor._apply_filename_fallback(item)
                self.assertEqual(item.model_name, model)
                self.assertEqual(item.model_source, source)
                entries = dict(object.__new__(OrganizerEngine)._build_metadata_entries(item))
                self.assertIn('숫자', entries.get('파일명 모델명 안내', ''))
                self.assertEqual(item.warnings, [])

    def test_nearby_photos_infer_model_while_unresolved_numbers_cannot_poison_candidates(self):
        extractor = MetadataExtractor()
        video = MediaItem(Path('sample/20240929_103347_02.mp4'), 'video', '.mp4')
        other = MediaItem(Path('sample/20240929_103347_99.mp4'), 'video', '.mp4')
        for item in (video, other):
            extractor._apply_filename_fallback(item)
        photo = MediaItem(Path('sample/20240929_103347_01.jpg'), 'photo', '.jpg',
                          captured_at=datetime(2024, 9, 29, 10, 33, 47), model_name='Galaxy_Z_Fold6', model_source='사진 메타')
        object.__new__(OrganizerEngine)._infer_video_models([video, other, photo])
        self.assertEqual([video.model_name, other.model_name], ['Galaxy_Z_Fold6'] * 2)
        self.assertEqual(video.model_source, '영상 모델명 사진 추론')

    def test_missing_or_conflicting_photos_leave_unknown(self):
        extractor = MetadataExtractor()
        for models in ([], ['CAM-A', 'CAM-B']):
            with self.subTest(models=models):
                video = MediaItem(Path('sample/20240929_103347_02.mp4'), 'video', '.mp4')
                extractor._apply_filename_fallback(video)
                photos = [MediaItem(Path(f'sample/photo{index}.jpg'), 'photo', '.jpg',
                                    captured_at=video.captured_at, model_name=model, model_source='사진 메타')
                          for index, model in enumerate(models)]
                object.__new__(OrganizerEngine)._infer_video_models([video] + photos)
                self.assertEqual(video.model_name, 'UNKNOWN')

    def test_real_preview_retains_shared_sequence_and_exposes_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'; source.mkdir()
            video = source / '20240929_103347_02.mp4'; video.write_bytes(b'fixture')
            photo = source / '20240929_103347_01.jpg'; photo.write_bytes(b'fixture')
            engine = OrganizerEngine(root)
            def extract(path):
                item = MediaItem(path, 'video' if path == video else 'photo', path.suffix)
                if path == photo:
                    item.model_name, item.model_source = 'Galaxy_Z_Fold6', '사진 메타'
                MetadataExtractor()._apply_filename_fallback(item)
                return item
            with patch.object(engine.extractor, 'extract', side_effect=extract):
                preview = engine.preview(OrganizeRequest(source, root / 'target'))
            self.assertEqual([item.new_filename for item in preview.preview_items],
                ['20240929_103347_Galaxy_Z_Fold6_0001.jpg', '20240929_103347_Galaxy_Z_Fold6_0002.mp4'])
            self.assertIn('파일명 모델명 안내', dict(preview.preview_items[1].metadata_entries))
