import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.phone_transfer import RemoteEntry, scan_outputs, transfer_outputs, plan_video_transfer


class Phone:
    def __init__(self):
        self.children = {'root': []}
        self.calls = []
        self.uploads = []
        self.on_list = None

    def list_children(self, parent):
        self.calls.append(('list', parent))
        if self.on_list:
            callback, self.on_list = self.on_list, None
            callback()
        return list(self.children[parent])

    def create_folder(self, parent, name):
        self.calls.append(('mkdir', name))
        entry = RemoteEntry(str(len(self.children)), name, True)
        self.children[parent].append(entry)
        self.children[entry.id] = []
        return entry

    def upload_new(self, parent, name, source, progress, cancelled):
        self.uploads.append((name, source.stat().st_size))
        progress(source.stat().st_size)
        entry = RemoteEntry('file' + str(len(self.uploads)), name, False, source.stat().st_size)
        self.children[parent].append(entry)
        return entry

    def overwrite_file(self, parent, name, source, progress, cancelled, existing_id):
        self.calls.append(('overwrite', name))
        return self.upload_new(parent, name, source, progress, cancelled)


class PhoneVideoLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name)
        self.output = self.target / 'output_20240101'
        self.output.mkdir()

    def file(self, name, size):
        path = self.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * size)
        return path

    def test_boundary_uppercase_and_photo_unchanged(self):
        self.file('small.MP4', 9)
        exact = self.file('exact.MOV', 10)
        above = self.file('above.mkv', 11)
        self.file('photo.jpg', 50)
        eligible, excluded = plan_video_transfer(scan_outputs(self.target), 10)
        self.assertEqual({p.name for p in eligible[0].files}, {'small.MP4', 'photo.jpg'})
        self.assertEqual(eligible[0].size, 59)
        self.assertEqual({r.source for r in excluded}, {exact, above})
        self.assertTrue(all(r.status == 'SIZE_EXCLUDED' for r in excluded))
        self.assertIn('MB', excluded[0].message)

    def test_all_excluded_never_contacts_phone_for_any_policy(self):
        self.file('big.mp4', 10)
        folders = scan_outputs(self.target)
        for policy in ('overwrite', 'skip', 'rename'):
            with self.subTest(policy=policy):
                phone = Phone()
                results = transfer_outputs(phone, 'root', folders, conflict_policy=policy, limit_video_bytes=10)
                self.assertEqual([r.status for r in results], ['SIZE_EXCLUDED'])
                self.assertEqual(phone.calls, [])
                self.assertEqual(phone.uploads, [])

    def test_nested_prunes_empty_and_excluded_only_subtrees(self):
        self.file('excluded/deep/big.wmv', 10)
        self.file('included/deep/photo.jpg', 20)
        (self.output / 'empty').mkdir()
        folders, excluded = plan_video_transfer(scan_outputs(self.target), 10)
        self.assertEqual({p.relative_to(self.output).as_posix() for p in folders[0].directories},
                         {'included', 'included/deep'})
        phone = Phone()
        results = transfer_outputs(phone, 'root', scan_outputs(self.target), limit_video_bytes=10)
        self.assertEqual({r.status for r in results}, {'COPIED', 'SIZE_EXCLUDED'})
        self.assertEqual({name for operation, name in phone.calls if operation == 'mkdir'},
                         {'output_20240101', 'included', 'deep'})

    def test_disabled_preserves_empty_directory_behavior(self):
        (self.output / 'empty').mkdir()
        original = scan_outputs(self.target)
        folders, excluded = plan_video_transfer(original)
        self.assertEqual(folders, original)
        self.assertEqual(excluded, [])
        phone = Phone()
        transfer_outputs(phone, 'root', original)
        self.assertIn(('mkdir', 'empty'), phone.calls)

    def test_snapshot_size_rechecked_at_transfer_start(self):
        video = self.file('video.avi', 9)
        folders = scan_outputs(self.target)
        video.write_bytes(b'x' * 10)
        phone = Phone()
        self.assertEqual(transfer_outputs(phone, 'root', folders, limit_video_bytes=10)[0].status, 'SIZE_EXCLUDED')
        self.assertEqual(phone.calls, [])

    def test_growth_during_phone_list_is_excluded_before_upload(self):
        video = self.file('video.m4v', 9)
        phone = Phone()
        updates = []
        original_list = phone.list_children
        def grow_during_file_discovery(parent):
            children = original_list(parent)
            if parent != 'root':
                video.write_bytes(b'x' * 10)
            return children
        phone.list_children = grow_during_file_discovery
        results = transfer_outputs(phone, 'root', scan_outputs(self.target), limit_video_bytes=10,
                                   progress=updates.append)
        self.assertEqual(results[0].status, 'SIZE_EXCLUDED')
        self.assertEqual(phone.uploads, [])
        self.assertEqual(updates[-1]['total_bytes'], 0)

    def test_late_exclusion_subtracts_planned_size_preserves_photo_total(self):
        self.file('a_photo.jpg', 20)
        video = self.file('z_video.mp4', 9)
        phone = Phone()
        original_list = phone.list_children
        def grow_after_photo(parent):
            children = original_list(parent)
            if phone.uploads:
                video.write_bytes(b'x' * 30)
            return children
        phone.list_children = grow_after_photo
        updates = []
        results = transfer_outputs(phone, 'root', scan_outputs(self.target), limit_video_bytes=10,
                                   progress=updates.append)
        self.assertEqual([r.status for r in results], ['COPIED', 'SIZE_EXCLUDED'])
        self.assertEqual(updates[-1]['total_bytes'], 20)
        self.assertEqual(updates[-1]['bytes'], 20)

    def test_excluded_existing_video_untouched_while_photo_copied_all_policies(self):
        video = self.file('video.mp4', 10)
        self.file('photo.jpg', 20)
        for policy in ('overwrite', 'skip', 'rename'):
            with self.subTest(policy=policy):
                phone = Phone()
                root = phone.create_folder('root', self.output.name)
                old = RemoteEntry('original-video', video.name, False, 5)
                phone.children[root.id].append(old)
                results = transfer_outputs(phone, 'root', scan_outputs(self.target),
                                           conflict_policy=policy, limit_video_bytes=10)
                self.assertEqual({r.status for r in results}, {'SIZE_EXCLUDED', 'COPIED'})
                self.assertIn(old, phone.children[root.id])
                self.assertEqual(phone.uploads, [('photo.jpg', 20)])
                self.assertFalse(any(call[0] == 'overwrite' for call in phone.calls))

    def test_all_excluded_notifies_completed_with_zero_transfer_bytes(self):
        self.file('video.mp4', 10)
        updates = []
        transfer_outputs(Phone(), 'root', scan_outputs(self.target),
                         progress=updates.append, limit_video_bytes=10)
        self.assertEqual(updates[-1]['total_bytes'], 0)
        self.assertEqual(updates[-1]['bytes'], 0)
        self.assertEqual(updates[-1]['completed'], 1)
        self.assertEqual(updates[-1]['total_files'], 1)

    def test_invalid_threshold_rejected_before_backend(self):
        self.file('video.mp4', 5)
        for limit in (0, -1, True, 1.5, '5'):
            with self.subTest(limit=limit):
                phone = Phone()
                with self.assertRaises(ValueError):
                    transfer_outputs(phone, 'root', scan_outputs(self.target), limit_video_bytes=limit)
                self.assertEqual(phone.calls, [])


if __name__ == '__main__':
    unittest.main()
