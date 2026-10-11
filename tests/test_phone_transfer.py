import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.phone_transfer import RemoteEntry, scan_outputs, transfer_outputs


class MemoryPhone:
    def __init__(self):
        self.children = {'root': []}
        self.data = {}
        self.bad_size = False
        self.disconnect = False
        self.overwrites = []

    def list_children(self, parent_id):
        if self.disconnect:
            raise OSError('USB disconnected')
        return list(self.children[parent_id])

    def create_folder(self, parent_id, name):
        entry = RemoteEntry(str(len(self.children)), name, True)
        self.children[parent_id].append(entry)
        self.children[entry.id] = []
        return entry

    def upload_new(self, parent_id, name, source, progress, cancelled):
        if cancelled():
            raise InterruptedError('cancelled')
        data = source.read_bytes()
        progress(len(data))
        entry = RemoteEntry('file' + str(len(self.data)), name, False,
                            len(data) + int(self.bad_size))
        self.children[parent_id].append(entry)
        self.data[entry.id] = data
        return entry

    def overwrite_file(self, parent_id, name, source, progress, cancelled, existing_id):
        if cancelled():
            raise InterruptedError('cancelled')
        data = source.read_bytes()
        progress(len(data))
        self.overwrites.append(existing_id)
        entry = RemoteEntry(existing_id, name, False, len(data))
        self.children[parent_id] = [entry if old.id == existing_id else old
                                    for old in self.children[parent_id]]
        self.data[existing_id] = data
        return entry


class PhoneTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name)
        self.output = self.target / '2024' / '20240501' / 'model' / 'output_20240501_SM-A'
        self.output.mkdir(parents=True)
        (self.output / 'a.jpg').write_bytes(b'photo')
        (self.output / 'sub').mkdir()
        (self.output / 'sub' / 'b.mp4').write_bytes(b'video')
        (self.output.parent / 'original.jpg').write_bytes(b'original')

    def test_scan_only_output_preserves_nested_files_excludes_temporary(self):
        (self.output / 'a.tmp.mp4').write_bytes(b'incomplete')
        (self.output / '.photoorganizer_job').mkdir()
        (self.output / '.photoorganizer_job' / 'partial.jpg').write_bytes(b'partial')
        folders = scan_outputs(self.target)
        self.assertEqual(len(folders), 1)
        self.assertEqual({f.relative_to(self.output).as_posix() for f in folders[0].files},
                         {'a.jpg', 'sub/b.mp4'})
        self.assertEqual(folders[0].size, 10)

    def test_transfer_and_retry_preserve_existing_files(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        updates = []
        results = transfer_outputs(phone, 'root', folders, progress=updates.append)
        self.assertEqual([r.status for r in results], ['COPIED', 'COPIED'])
        self.assertEqual({*phone.data.values()}, {b'photo', b'video'})
        again = transfer_outputs(phone, 'root', folders, conflict_policy='skip')
        self.assertEqual([r.status for r in again], ['SKIPPED', 'SKIPPED'])
        self.assertEqual(len(phone.data), 2)
        self.assertEqual(updates[-1]['completed'], 2)
        self.assertTrue((self.output / 'a.jpg').exists())

    def test_default_policy_overwrites_same_name(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        (self.output / 'a.jpg').write_bytes(b'new-photo')
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['COPIED', 'COPIED'])
        self.assertEqual(len(phone.overwrites), 2)
        self.assertIn(b'new-photo', phone.data.values())
        self.assertNotIn(b'photo', phone.data.values())

    def test_rename_preserves_existing_and_uses_available_number(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        transfer_outputs(phone, 'root', folders, conflict_policy='rename')
        results = transfer_outputs(phone, 'root', folders, conflict_policy='rename')
        self.assertEqual([r.status for r in results], ['COPIED', 'COPIED'])
        output_id = phone.children['root'][0].id
        self.assertEqual({entry.name for entry in phone.children[output_id]},
                         {'a.jpg', 'a_copy0001.jpg', 'a_copy0002.jpg', 'sub'})
        self.assertEqual(len(phone.data), 6)
        self.assertFalse(phone.overwrites)

    def test_invalid_policy_rejects_before_device_mutation(self):
        phone = MemoryPhone()
        with self.assertRaises(ValueError):
            transfer_outputs(phone, 'root', scan_outputs(self.target), conflict_policy='delete')
        self.assertEqual(phone.children['root'], [])

    def test_multiple_same_name_files_are_not_automatically_overwritten(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        output_id = phone.children['root'][0].id
        phone.children[output_id].append(RemoteEntry('ambiguous', 'A.JPG', False, 9))
        results = transfer_outputs(phone, 'root', folders)
        self.assertEqual(results[0].status, 'FAILED')
        self.assertNotIn('ambiguous', phone.overwrites)

    def test_overwrite_error_is_unverified_and_stops_queue(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        before = dict(phone.data)
        def fail_replacement(*args):
            raise OSError('original preserved; staged file remains')
        phone.overwrite_file = fail_replacement
        results = transfer_outputs(phone, 'root', folders)
        self.assertEqual([r.status for r in results], ['UNVERIFIED', 'FAILED'])
        self.assertEqual(phone.data, before)
        self.assertIn('staged file', results[0].message)

    def test_rename_rechecks_a_name_created_during_upload(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        original_upload = phone.upload_new
        raced = []
        def upload(parent, name, source, progress, cancelled):
            if name == 'a_copy0001.jpg' and not raced:
                raced.append(name)
                phone.children[parent].append(RemoteEntry('external', name, False, 8))
                phone.data['external'] = b'external'
                raise FileExistsError(name)
            return original_upload(parent, name, source, progress, cancelled)
        phone.upload_new = upload
        results = transfer_outputs(phone, 'root', folders, conflict_policy='rename')
        self.assertEqual(results[0].status, 'COPIED')
        self.assertIn('a_copy0002.jpg', results[0].message)
        self.assertEqual(phone.data['external'], b'external')

    def test_default_overwrite_rechecks_concurrent_file_before_creation(self):
        phone = MemoryPhone()
        original_upload = phone.upload_new
        raced = []
        def upload(parent, name, source, progress, cancelled):
            if name == 'a.jpg' and not raced:
                raced.append(name)
                phone.children[parent].append(RemoteEntry('external', name, False, 8))
                phone.data['external'] = b'external'
                raise FileExistsError(name)
            return original_upload(parent, name, source, progress, cancelled)
        phone.upload_new = upload
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual(results[0].status, 'COPIED')
        self.assertEqual(phone.overwrites, ['external'])
        self.assertEqual(phone.data['external'], b'photo')

    def test_cancel_during_overwrite_keeps_original_and_cancels_remaining(self):
        phone = MemoryPhone()
        folders = scan_outputs(self.target)
        transfer_outputs(phone, 'root', folders)
        before = dict(phone.data)
        def cancel_replacement(*args):
            raise InterruptedError('stage cancelled, original kept')
        phone.overwrite_file = cancel_replacement
        results = transfer_outputs(phone, 'root', folders)
        self.assertEqual([r.status for r in results], ['CANCELLED', 'CANCELLED'])
        self.assertEqual(phone.data, before)

    def test_invalid_backend_completion_is_not_reported_as_success(self):
        phone = MemoryPhone()
        phone.upload_new = lambda *args: None
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['UNVERIFIED', 'FAILED'])

    def test_repeated_name_races_are_bounded(self):
        phone = MemoryPhone()
        calls = []
        def racing_upload(*args):
            calls.append(args[1])
            raise FileExistsError(args[1])
        phone.upload_new = racing_upload
        results = transfer_outputs(phone, 'root', scan_outputs(self.target), conflict_policy='rename')
        self.assertEqual([r.status for r in results], ['FAILED', 'FAILED'])
        self.assertEqual(len(calls), 40)

    def test_directory_file_collision_fails_without_writing(self):
        phone = MemoryPhone()
        phone.children['root'].append(RemoteEntry('old', self.output.name, False, 100))
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['FAILED', 'FAILED'])
        self.assertFalse(phone.data)

    def test_size_mismatch_is_unverified(self):
        phone = MemoryPhone()
        phone.bad_size = True
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['UNVERIFIED', 'UNVERIFIED'])

    def test_cancel_before_start_writes_nothing(self):
        phone = MemoryPhone()
        results = transfer_outputs(phone, 'root', scan_outputs(self.target), cancelled=lambda: True)
        self.assertEqual([r.status for r in results], ['CANCELLED', 'CANCELLED'])
        self.assertFalse(phone.data)

    def test_disconnect_stops_without_success_claim(self):
        phone = MemoryPhone()
        phone.disconnect = True
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['FAILED', 'FAILED'])

    def test_duplicate_output_folder_names_rejected(self):
        second = self.target / 'other' / self.output.name
        second.mkdir(parents=True)
        (second / 'a.jpg').write_bytes(b'other')
        with self.assertRaises(ValueError):
            scan_outputs(self.target)

    def test_missing_target_is_clear_error(self):
        with self.assertRaises(ValueError):
            scan_outputs(self.target / 'absent')

    def test_empty_subdirectories_are_copied(self):
        empty = self.output / 'empty'
        empty.mkdir()
        phone = MemoryPhone()
        transfer_outputs(phone, 'root', scan_outputs(self.target))
        output_id = phone.children['root'][0].id
        self.assertIn('empty', [entry.name for entry in phone.children[output_id]])

    def test_failed_upload_does_not_claim_known_completion(self):
        phone = MemoryPhone()
        def interrupted_upload(*args, **kwargs):
            raise OSError('device disconnected during Commit')
        phone.upload_new = interrupted_upload
        results = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual([r.status for r in results], ['UNVERIFIED', 'FAILED'])

    def test_replaced_ancestor_link_is_not_read(self):
        from unittest.mock import patch
        folders = scan_outputs(self.target)
        phone = MemoryPhone()
        with patch('photo_organizer.phone_transfer._is_link', side_effect=lambda p: p == self.output.parent):
            results = transfer_outputs(phone, 'root', folders)
        self.assertEqual([r.status for r in results], ['FAILED', 'FAILED'])
        self.assertFalse(phone.data)

    def test_empty_output_replaced_parent_is_not_created_remotely(self):
        from unittest.mock import patch
        empty = self.target / 'other' / 'output_20240502_CAM'
        empty.mkdir(parents=True)
        folders = [folder for folder in scan_outputs(self.target) if folder.path == empty]
        phone = MemoryPhone()
        with patch('photo_organizer.phone_transfer._is_link', side_effect=lambda p: p == empty.parent):
            results = transfer_outputs(phone, 'root', folders)
        self.assertEqual(results[0].status, 'FAILED')
        self.assertEqual(phone.children['root'], [])

    def test_links_are_not_followed(self):
        outside = self.target / 'outside'
        outside.mkdir()
        (outside / 'secret.jpg').write_bytes(b'outside')
        try:
            (self.output / 'linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Windows symlink privilege unavailable')
        self.assertEqual(len(scan_outputs(self.target)[0].files), 2)


if __name__ == '__main__':
    unittest.main()
