import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.engine import OrganizerEngine
from photo_organizer.phone_transfer import scan_outputs
from photo_organizer.metadata_writer import STORAGE_NAME, OWNER


class MetadataStorageScanTests(unittest.TestCase):
    def test_owned_backups_and_staging_are_not_media_or_mobile_candidates(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            owned = root / STORAGE_NAME
            nested = owned / 'output_backup'
            nested.mkdir(parents=True)
            (owned / 'owner.json').write_text(json.dumps(OWNER), encoding='utf-8')
            (nested / 'staged.jpg').write_bytes(b'stage')
            (root / 'real.jpg').write_bytes(b'original')
            real = root / 'output_real'
            real.mkdir()
            (real / 'output.jpg').write_bytes(b'output')
            files = OrganizerEngine(root)._scan_media_files(root, root / 'target')
            self.assertNotIn(nested / 'staged.jpg', files)
            folders = scan_outputs(root)
            self.assertEqual([folder.path.name for folder in folders], ['output_real'])

    def test_similarly_named_unowned_folder_is_not_silently_excluded(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            folder = root / STORAGE_NAME / 'output_user'
            folder.mkdir(parents=True)
            (folder / 'real.jpg').write_bytes(b'user')
            self.assertIn(folder / 'real.jpg', OrganizerEngine(root)._scan_media_files(root, root / 'target'))
            self.assertEqual(len(scan_outputs(root)), 1)
