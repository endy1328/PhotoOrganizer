import os
from pathlib import Path
import sys
import tempfile
import json
import hashlib
import uuid
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class MetadataWriterSafetyTests(unittest.TestCase):
    def test_missing_tool_and_unvalidated_formats_are_not_supported(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter
        with patch('photo_organizer.metadata_writer.discover_exiftool', return_value=None):
            writer = ModelMetadataWriter()
            self.assertFalse(writer.supports(Path('file.jpg')))
            self.assertFalse(writer.supports(Path('file.heic')))

    def test_invalid_model_and_link_rejected_before_file_changes(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.jpg'
            source.write_bytes(b'original')
            writer = ModelMetadataWriter()
            for model in ('', 'UNKNOWN', 'a\0b', 'x' * 256):
                with self.assertRaises(ValueError):
                    writer.write_model(source, model)
            linked = Path(folder) / 'linked.jpg'
            os.link(source, linked)
            with self.assertRaises(ValueError):
                writer.write_model(source, 'Camera')
            self.assertEqual(source.read_bytes(), b'original')

    def test_marker_is_required_for_owned_storage(self):
        from photo_organizer.metadata_writer import is_metadata_storage
        with tempfile.TemporaryDirectory() as folder:
            storage = Path(folder) / '.photo_organizer_metadata'
            storage.mkdir()
            self.assertFalse(is_metadata_storage(storage / 'stage.jpg'))
            (storage / 'owner.json').write_text('{"owner":"PhotoOrganizer metadata","version":1}')
            self.assertTrue(is_metadata_storage(storage / 'stage.jpg'))

    def test_hardlinked_owner_marker_and_reparse_storage_are_rejected(self):
        from photo_organizer.metadata_writer import is_metadata_storage, OWNER
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / 'original-owner.json'
            marker.write_text(json.dumps(OWNER))
            storage = root / '.photo_organizer_metadata'
            storage.mkdir()
            os.link(marker, storage / 'owner.json')
            self.assertFalse(is_metadata_storage(storage))
            (storage / 'owner.json').unlink()
            (storage / 'owner.json').write_text(json.dumps(OWNER))
            real_lstat = Path.lstat
            def fake_lstat(path):
                if path == storage:return SimpleNamespace(st_file_attributes=0x400)
                return real_lstat(path)
            with patch.object(Path, 'lstat', fake_lstat):
                self.assertFalse(is_metadata_storage(storage))

    def test_read_only_recovery_detects_external_or_backup_change(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter
        with tempfile.TemporaryDirectory() as folder:
            writer = ModelMetadataWriter(Path(folder))
            self.assertEqual(writer.recovery_records(), [])

    def test_prepared_recovery_reports_known_output_without_overwriting_and_tampered_backup(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, OWNER
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.jpg'
            source.write_bytes(b'after')
            storage = root / '.photo_organizer_metadata'
            storage.mkdir()
            (storage / 'owner.json').write_text(json.dumps(OWNER))
            identifier = str(uuid.uuid4())
            backup = storage / (identifier + '.bak')
            backup.write_bytes(b'before')
            record = {'transaction_id': identifier, 'source_path': str(source), 'backup_path': str(backup),
                      'before_hash': hashlib.sha256(b'before').hexdigest(),
                      'after_hash': hashlib.sha256(b'after').hexdigest(), 'state': 'PREPARED'}
            (storage / (identifier + '.json')).write_text(json.dumps(record))
            writer = ModelMetadataWriter(root)
            recovered = writer.recovery_records(source)[0]
            self.assertEqual(recovered['effective_state'], 'COMMITTED')
            self.assertTrue(recovered['can_restore'])
            self.assertEqual(source.read_bytes(), b'after')
            stat = source.stat()
            source.write_bytes(b'other')
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(writer.recovery_records(source)[0]['recovery_status'], 'external_change')
            with self.assertRaises(ValueError):writer.restore(source)
            source.write_bytes(b'after')
            backup.write_bytes(b'broken')
            self.assertFalse(writer.recovery_records(source)[0]['can_restore'])
            with self.assertRaises(ValueError):writer.restore(source)

    def test_latest_tampered_backup_does_not_silently_restore_older_transaction(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, OWNER
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.jpg';source.write_bytes(b'after')
            storage = root / '.photo_organizer_metadata';storage.mkdir()
            (storage / 'owner.json').write_text(json.dumps(OWNER))
            for index in (1, 2):
                identifier = str(uuid.uuid4());backup = storage / (identifier + '.bak')
                backup.write_bytes(b'before' if index == 1 else b'tampered')
                record = {'transaction_id': identifier, 'created_ns': index, 'source_path': str(source),
                          'backup_path': str(backup), 'before_hash': hashlib.sha256(b'before').hexdigest(),
                          'after_hash': hashlib.sha256(b'after').hexdigest(), 'state': 'COMMITTED',
                          'atime_ns': 0, 'mtime_ns': 0}
                (storage / (identifier + '.json')).write_text(json.dumps(record))
            with self.assertRaises(ValueError):ModelMetadataWriter().restore(source)
            self.assertEqual(source.read_bytes(), b'after')

    def test_exiftool_model_fallback_precedes_filename_for_missing_native_model(self):
        from photo_organizer.metadata import MetadataExtractor
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '20241012_100000_FILENAME.png'
            Image.new('RGB', (8, 8)).save(path)
            with patch('photo_organizer.metadata_writer.read_exiftool_model', return_value='Original Camera'):
                item = MetadataExtractor().extract(path)
            self.assertEqual(item.model_name, 'Original_Camera')
            self.assertEqual(item.metadata['display_metadata']['photo_model'], 'Original Camera')


class MetadataWriterRealMediaTests(unittest.TestCase):
    def test_inspection_fingerprint_blocks_later_same_size_same_mtime_edit(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool
        from PIL import Image
        if discover_exiftool() is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.png'
            Image.new('RGB', (8, 8)).save(path)
            writer = ModelMetadataWriter()
            inspected = writer.inspect(path)
            data, stat = path.read_bytes(), path.stat()
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            with self.assertRaises(ValueError):
                writer.write_model(path, 'Camera', expected_fingerprint=inspected['fingerprint'])
            self.assertFalse((path.parent / '.photo_organizer_metadata').exists())

    def test_post_publish_journal_failure_recovers_and_external_same_size_change_blocks_restore(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool, _atomic_json
        from PIL import Image
        if discover_exiftool() is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.png'
            Image.new('RGB', (8, 8)).save(path)
            writer = ModelMetadataWriter(Path(folder))
            before = path.read_bytes()
            def fail_committed(target, record):
                if record.get('state') == 'COMMITTED':raise OSError('journal commit failed')
                return _atomic_json(target, record)
            with patch('photo_organizer.metadata_writer._atomic_json', side_effect=fail_committed):
                with self.assertRaises(OSError):writer.write_model(path, 'Camera')
            recovery = writer.recovery_records(path)[0]
            self.assertEqual(recovery['effective_state'], 'COMMITTED')
            self.assertTrue(recovery['can_restore'])
            current = path.read_bytes()
            stat = path.stat()
            path.write_bytes(current[:-1] + bytes([current[-1] ^ 1]))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            with self.assertRaises(ValueError):writer.restore(path)
            path.write_bytes(current)
            writer.restore(path)
            self.assertEqual(path.read_bytes(), before)

    def test_source_change_at_prepare_is_not_overwritten(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool, _atomic_json
        from PIL import Image
        if discover_exiftool() is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.png'
            Image.new('RGB', (8, 8)).save(path)
            def edit_after_prepare(target, record):
                result = _atomic_json(target, record)
                if record.get('state') == 'PREPARED':path.write_bytes(b'external edit')
                return result
            with patch('photo_organizer.metadata_writer._atomic_json', side_effect=edit_after_prepare):
                with self.assertRaises(ValueError):ModelMetadataWriter().write_model(path, 'Camera')
            self.assertEqual(path.read_bytes(), b'external edit')

    def test_synthetic_jpeg_png_mp4_mov_m4v_roundtrip_and_restore(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool
        from photo_organizer.process_utils import hidden_process_kwargs
        from photo_organizer.metadata import MetadataExtractor
        from PIL import Image
        tool = discover_exiftool()
        if tool is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            writer = ModelMetadataWriter(root)
            for extension in ('.jpg', '.png', '.mp4', '.mov', '.m4v'):
                with self.subTest(extension=extension):
                    path = root / ('synthetic' + extension)
                    if extension in ('.jpg', '.png'):
                        Image.new('RGB', (32, 24), (10, 50, 90)).save(path)
                        subprocess.run([str(tool), '-config', '', '-overwrite_original',
                                        '-EXIF:Model=Before Camera', '-DateTimeOriginal=2024:01:02 03:04:05',
                                        '-Orientation#=6', '-GPSLatitude=37.5', '-GPSLatitudeRef=N', str(path)],
                                       check=True, capture_output=True, **hidden_process_kwargs())
                    else:
                        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=64x48:r=5',
                                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000', '-t', '0.4',
                                        '-c:v', 'libx264', '-c:a', 'aac', '-metadata',
                                        'creation_time=2024-01-02T03:04:05Z', str(path)], check=True,
                                       capture_output=True, **hidden_process_kwargs())
                    before = path.read_bytes()
                    before_stat = path.stat()
                    modified = writer.write_model(path, 'After Camera')
                    self.assertEqual(path.stat().st_mtime_ns, before_stat.st_mtime_ns)
                    if hasattr(before_stat, 'st_birthtime_ns'):
                        self.assertEqual(path.stat().st_birthtime_ns, before_stat.st_birthtime_ns)
                    self.assertEqual(MetadataExtractor().extract(path).model_name, 'After_Camera')
                    self.assertEqual(Path(modified['backup_path']).read_bytes(), before)
                    self.assertTrue(writer.recovery_records(path)[-1]['can_restore'])
                    writer.restore(path)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(path.stat().st_mtime_ns, before_stat.st_mtime_ns)
                    self.assertEqual(writer.recovery_records(path)[-1]['state'], 'RESTORED')

    def test_unicode_model_roundtrip_and_xmp_model_collision_resolved(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool
        from photo_organizer.process_utils import hidden_process_kwargs
        from photo_organizer.metadata import MetadataExtractor
        from PIL import Image
        tool = discover_exiftool()
        if tool is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '한글.jpg'
            Image.new('RGB', (8, 8)).save(path)
            subprocess.run([str(tool), '-config', '', '-overwrite_original', '-EXIF:Model=oldEXIF',
                            '-XMP-tiff:Model=oldXMP', str(path)], check=True, capture_output=True,
                           **hidden_process_kwargs())
            writer = ModelMetadataWriter()
            writer.write_model(path, '갤럭시 카메라')
            item = MetadataExtractor().extract(path)
            self.assertEqual(item.metadata['display_metadata']['photo_model'], '갤럭시 카메라')
            self.assertEqual(set(writer.inspect(path)['model_tags'].values()), {'갤럭시 카메라'})

    def test_png_unicode_model_is_read_without_pillow_ascii_reserialization(self):
        from photo_organizer.metadata_writer import ModelMetadataWriter, discover_exiftool
        from photo_organizer.metadata import MetadataExtractor
        from PIL import Image
        if discover_exiftool() is None:self.skipTest('bundled ExifTool unavailable')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '한글.png'
            Image.new('RGB', (8, 8)).save(path)
            ModelMetadataWriter().write_model(path, '갤럭시 Camera')
            self.assertEqual(MetadataExtractor().extract(path).metadata['display_metadata']['photo_model'], '갤럭시 Camera')
