import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.phone_transfer import OutputFolder, RemoteEntry, TransferResult, transfer_outputs
from photo_organizer.phone_wpd import WpdBackend


class CheckingPhone:
    """Fake final collision checks model the unchanged WPD helper contract."""
    def __init__(self):
        self.children = {'root': []}
        self.lookups = []
        self.overwritten = []
        self.race = None

    def list_children(self, parent):
        self.lookups.append(parent)
        return list(self.children[parent])

    def create_folder(self, parent, name):
        entry = RemoteEntry('folder', name, True)
        self.children[parent].append(entry)
        self.children[entry.id] = []
        return entry

    def upload_new(self, parent, name, source, progress, cancelled):
        if self.race:
            self.race(self, parent, name)
        if any(entry.name.casefold() == name.casefold() for entry in self.children[parent]):
            raise FileExistsError(name)
        entry = RemoteEntry(name, name, False, source.stat().st_size)
        self.children[parent].append(entry)
        progress(entry.size)
        return entry

    def overwrite_file(self, parent, name, source, progress, cancelled, existing_id):
        matches = [entry for entry in self.children[parent] if entry.name.casefold() == name.casefold()]
        if len(matches) != 1 or matches[0].id != existing_id or matches[0].is_folder:
            raise FileExistsError(name)
        self.overwritten.append(existing_id)
        entry = RemoteEntry('new-' + existing_id, name, False, source.stat().st_size)
        self.children[parent] = [entry if old.id == existing_id else old for old in self.children[parent]]
        progress(entry.size)
        return entry


class PhoneCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'output_day_CAM'
        self.root.mkdir()
        files = tuple(self.root / name for name in ('a.jpg', 'b.jpg', 'c.jpg'))
        for source in files:
            source.write_bytes(b'image')
        self.folder = OutputFolder(self.root, files, 15)

    def test_one_policy_lookup_per_parent_and_telemetry(self):
        phone, updates = CheckingPhone(), []
        with patch('photo_organizer.phone_transfer.logger.info') as log:
            result = transfer_outputs(phone, 'root', [self.folder], progress=updates.append)
        self.assertEqual([entry.status for entry in result], ['COPIED'] * 3)
        self.assertEqual(phone.lookups, ['root', 'folder'])
        self.assertEqual(updates[-1]['lookup_count'], 2)
        self.assertGreaterEqual(updates[-1]['lookup_seconds'], 0)
        self.assertTrue(any('조회' in str(call.args[0]) for call in log.call_args_list))

    def test_external_writer_invalidation_requeries_before_overwrite(self):
        phone = CheckingPhone()
        def race(backend, parent, name):
            if name == 'b.jpg':
                backend.race = None
                backend.children[parent].append(RemoteEntry('external', name, False, 100))
        phone.race = race
        result = transfer_outputs(phone, 'root', [self.folder])
        self.assertEqual([entry.status for entry in result], ['COPIED'] * 3)
        self.assertEqual(phone.overwritten, ['external'])
        self.assertEqual(phone.lookups, ['root', 'folder', 'folder'])

    def test_external_writer_folder_collision_never_overwritten(self):
        phone = CheckingPhone()
        def race(backend, parent, name):
            if name == 'b.jpg':
                backend.race = None
                backend.children[parent].append(RemoteEntry('external-folder', name, True))
        phone.race = race
        result = transfer_outputs(phone, 'root', [self.folder])
        self.assertEqual([entry.status for entry in result], ['COPIED', 'FAILED', 'COPIED'])
        self.assertFalse(phone.overwritten)

    def test_unverified_result_discards_policy_cache(self):
        phone = CheckingPhone()
        original_upload = phone.upload_new
        def wrong_size(parent, name, source, progress, cancelled):
            entry = original_upload(parent, name, source, progress, cancelled)
            return RemoteEntry(entry.id, entry.name, False, 999) if name == 'a.jpg' else entry
        phone.upload_new = wrong_size
        result = transfer_outputs(phone, 'root', [self.folder])
        self.assertEqual([entry.status for entry in result], ['UNVERIFIED', 'COPIED', 'COPIED'])
        self.assertEqual(phone.lookups, ['root', 'folder', 'folder'])

    def test_stale_overwrite_object_id_requeries_after_final_check(self):
        phone = CheckingPhone()
        original_create = phone.create_folder
        def create_existing(parent, name):
            folder = original_create(parent, name)
            phone.children[folder.id] = [RemoteEntry('old-a', 'a.jpg', False, 2),
                                         RemoteEntry('old-b', 'b.jpg', False, 2)]
            return folder
        phone.create_folder = create_existing
        original_overwrite = phone.overwrite_file
        raced = False
        def replace_external(parent, name, source, progress, cancelled, existing_id):
            nonlocal raced
            if name == 'b.jpg' and not raced:
                raced = True
                phone.children[parent] = [RemoteEntry('external-b', name, False, 7)
                                          if entry.id == 'old-b' else entry for entry in phone.children[parent]]
            return original_overwrite(parent, name, source, progress, cancelled, existing_id)
        phone.overwrite_file = replace_external
        self.assertEqual([entry.status for entry in transfer_outputs(phone, 'root', [self.folder])], ['COPIED'] * 3)
        self.assertEqual(phone.overwritten, ['old-a', 'external-b'])
        self.assertEqual(phone.lookups, ['root', 'folder', 'folder'])


class PhoneActivityTests(unittest.TestCase):
    def test_delayed_atomic_response_reports_waiting_without_terminating(self):
        backend, events = WpdBackend(), []
        backend.set_activity_callback(lambda phase, cancellable: events.append((phase, cancellable)))
        backend._activity_phase, backend._activity_cancellable = 'swap', False
        backend._messages.put('{"ok": true}')
        with patch('photo_organizer.phone_wpd.time.monotonic', side_effect=[0, 3]), patch.object(backend, '_terminate') as terminate:
            self.assertEqual(backend._receive(60, lambda: True), {'ok': True})
        self.assertEqual(events, [('waiting:swap', False)])
        terminate.assert_not_called()

    def test_callback_precedes_bytes_and_preserves_atomic_ack(self):
        backend, events = WpdBackend(), []
        backend.set_activity_callback(lambda phase, cancellable: events.append((phase, cancellable)))
        with patch.object(backend, '_send') as send:
            backend._progress({'bytes': 12, 'phase': 'swap', 'cancellable': False},
                              lambda value: events.append(value), lambda: True)
        self.assertEqual(events, [('swap', False), 12])
        send.assert_called_once_with({'continue': True})

    def test_activity_callback_failure_cannot_interrupt_atomic_swap(self):
        backend = WpdBackend()
        def broken(*args):
            raise RuntimeError('view closed')
        backend.set_activity_callback(broken)
        with self.assertLogs('photo_organizer.phone_wpd', level='WARNING'), patch.object(backend, '_send') as send:
            backend._progress({'bytes': 12, 'phase': 'swap', 'cancellable': False}, lambda _: None, lambda: True)
        send.assert_called_once_with({'continue': True})


class PhoneRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'output_day_CAM'
        self.root.mkdir()
        self.sub = self.root / 'sub' / 'nested'
        self.sub.mkdir(parents=True)
        self.files = tuple(self.sub / (str(number) + '.jpg') for number in range(6))
        for source in self.files:
            source.write_bytes(b'image')
        self.folder = OutputFolder(self.root, self.files, 30, (self.sub.parent, self.sub))

    def test_only_failed_cancelled_preserve_ancestry(self):
        from photo_organizer.phone_retry import capture_retry_snapshot, retry_folders
        statuses = ('FAILED', 'CANCELLED', 'COPIED', 'SKIPPED', 'SIZE_EXCLUDED', 'UNVERIFIED')
        results = [TransferResult(path, status) for path, status in zip(self.files, statuses)]
        snapshot = capture_retry_snapshot([self.folder])
        retry = retry_folders([self.folder], results, snapshot)
        self.assertEqual(len(snapshot), 6)
        self.assertEqual(retry, [OutputFolder(self.root, self.files[:2], 10, (self.sub.parent, self.sub))])

    def test_changed_missing_baseline_or_missing_source_requires_rescan(self):
        from photo_organizer.phone_retry import capture_retry_snapshot, retry_folders
        snapshot = capture_retry_snapshot([self.folder])
        result = [TransferResult(self.files[0], 'FAILED')]
        with self.assertRaises(ValueError):
            retry_folders([self.folder], result, {})
        self.files[0].write_bytes(b'changed')
        with self.assertRaises(ValueError):
            retry_folders([self.folder], result, snapshot)
        self.files[0].unlink()
        with self.assertRaises(ValueError):
            retry_folders([self.folder], result, snapshot)

    def test_same_size_mtime_change_requires_rescan(self):
        import os
        from photo_organizer.phone_retry import capture_retry_snapshot, retry_folders
        snapshot = capture_retry_snapshot([self.folder])
        source = self.files[0]
        original = source.stat()
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns + 2_000_000_000))
        with self.assertRaises(ValueError):
            retry_folders([self.folder], [TransferResult(source, 'CANCELLED')], snapshot)

    def test_success_or_unverified_duplicate_blocks_retry_and_empty_folder_ignored(self):
        from photo_organizer.phone_retry import capture_retry_snapshot, retry_folders
        snapshot = capture_retry_snapshot([self.folder])
        result = [TransferResult(self.files[0], 'FAILED'), TransferResult(self.files[0], 'UNVERIFIED'),
                  TransferResult(self.root, 'FAILED')]
        self.assertEqual(retry_folders([self.folder], result, snapshot), [])


if __name__ == '__main__':
    unittest.main()
