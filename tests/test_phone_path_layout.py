import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.phone_transfer import OutputFolder, RemoteEntry, scan_outputs, plan_video_transfer, transfer_outputs
from photo_organizer.phone_retry import capture_retry_snapshot, retry_folders
from test_phone_transfer import MemoryPhone


class PhonePathLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name)
        self.paths = []
        for year in ('2023년', '2024년'):
            output = self.target / year / (year + '10월') / '20241001' / '20241001_CAM' / 'output_same'
            output.mkdir(parents=True)
            (output / 'a.jpg').write_bytes(b'photo')
            (output / 'b.mp4').write_bytes(b'video')
            self.paths.append(output)

    def test_same_output_name_distinct_parents_preserves_layout(self):
        folders = scan_outputs(self.target)
        self.assertEqual(len(folders), 2)
        self.assertEqual(folders[1].relative_parts, self.paths[1].relative_to(self.target).parts)
        phone = MemoryPhone()
        results = transfer_outputs(phone, 'root', folders)
        self.assertTrue(all(result.status == 'COPIED' for result in results))
        for folder in folders:
            parent = 'root'
            for component in folder.relative_parts:
                parent = next(entry.id for entry in phone.children[parent] if entry.name == component)
            self.assertEqual({entry.name for entry in phone.children[parent]}, {'a.jpg', 'b.mp4'})

    def test_reuses_existing_year_month_preserves_unrelated_file_and_policies(self):
        folders = scan_outputs(self.target)
        phone = MemoryPhone()
        year = phone.create_folder('root', '2023년')
        month = phone.create_folder(year.id, '2023년10월')
        phone.children[month.id].append(RemoteEntry('unrelated', 'keep.jpg', False, 3))
        transfer_outputs(phone, 'root', folders)
        self.assertEqual(len([entry for entry in phone.children['root'] if entry.name == '2023년']), 1)
        self.assertIn('unrelated', {entry.id for entry in phone.children[month.id]})
        self.assertEqual({result.status for result in transfer_outputs(phone, 'root', folders, conflict_policy='skip')}, {'SKIPPED'})
        self.assertEqual({result.status for result in transfer_outputs(phone, 'root', folders, conflict_policy='rename')}, {'COPIED'})
        self.assertEqual({result.status for result in transfer_outputs(phone, 'root', folders)}, {'COPIED'})
        self.assertEqual(len(phone.overwrites), 4)

    def test_limit_and_retry_preserve_relative_path(self):
        folders = scan_outputs(self.target)
        eligible, _ = plan_video_transfer(folders, 5)
        self.assertEqual(eligible[0].relative_parts, folders[0].relative_parts)
        snapshot = capture_retry_snapshot(folders)
        from photo_organizer.phone_transfer import TransferResult
        results = [TransferResult(folders[0].files[0], 'FAILED')]
        retry = retry_folders(folders, results, snapshot)
        self.assertEqual(retry[0].relative_parts, folders[0].relative_parts)

    def test_invalid_path_rejected_before_any_remote_mutation(self):
        from photo_organizer.phone_transfer import output_relative_parts
        folder = scan_outputs(self.target)[0]
        for parts in (('..', 'output_same'), ('/root', 'output_same'), ('a/b', 'output_same'),
                      ('a\\b', 'output_same'), ('C:', 'output_same'), ('', 'output_same'),
                      ('.', 'output_same'), ('wrong',), ('unexpected', 'output_same'), ['output_same']):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                output_relative_parts(replace(folder, relative_parts=parts))
            phone = MemoryPhone()
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                transfer_outputs(phone, 'root', [folder, replace(folder, relative_parts=parts)])
            self.assertEqual(phone.children, {'root': []})

    def test_intermediate_file_collision_and_cancel_preserve_phone(self):
        folders = scan_outputs(self.target)
        phone = MemoryPhone()
        phone.children['root'].append(RemoteEntry('blocker', '2023년', False, 7))
        results = transfer_outputs(phone, 'root', folders[:1])
        self.assertEqual({result.status for result in results}, {'FAILED'})
        self.assertFalse(phone.data)
        empty = MemoryPhone()
        transfer_outputs(empty, 'root', folders, cancelled=lambda: True)
        self.assertEqual(empty.children, {'root': []})

    def test_duplicate_full_relative_path_rejected_and_legacy_flat_kept(self):
        folders = scan_outputs(self.target)
        phone = MemoryPhone()
        with self.assertRaises(ValueError):
            transfer_outputs(phone, 'root', [folders[0], folders[0]])
        self.assertEqual(phone.children, {'root': []})
        legacy = replace(folders[0], relative_parts=())
        transfer_outputs(phone, 'root', [legacy])
        self.assertEqual([entry.name for entry in phone.children['root']], ['output_same'])

    def test_empty_folder_builds_all_parents(self):
        for path in self.paths:
            for source in path.iterdir():
                source.unlink()
        folders = scan_outputs(self.target)
        phone = MemoryPhone()
        self.assertEqual([result.status for result in transfer_outputs(phone, 'root', folders)], ['COPIED', 'COPIED'])
        self.assertEqual({entry.name for entry in phone.children['root']}, {'2023년', '2024년'})

    def test_cancellation_between_intermediate_folders_stops_creation(self):
        phone = MemoryPhone()
        result = transfer_outputs(phone, 'root', scan_outputs(self.target),
                                  cancelled=lambda: bool(phone.children['root']))
        self.assertEqual({entry.status for entry in result}, {'CANCELLED'})
        self.assertEqual(len(phone.children['root']), 1)
        first = phone.children['root'][0]
        self.assertEqual(phone.children[first.id], [])
        self.assertFalse(phone.data)

    def test_disconnect_during_parent_discovery_stops_remaining_outputs(self):
        phone = MemoryPhone()
        original = phone.list_children
        def disconnected(parent):
            if parent != 'root':
                raise OSError('USB disconnected')
            return original(parent)
        phone.list_children = disconnected
        result = transfer_outputs(phone, 'root', scan_outputs(self.target))
        self.assertEqual({entry.status for entry in result}, {'FAILED'})
        self.assertEqual(len(phone.children['root']), 1)
        self.assertFalse(phone.data)

    def test_casefold_full_path_duplicate_blocked_and_old_ducktyped_folder_supported(self):
        from types import SimpleNamespace
        from photo_organizer.phone_transfer import output_relative_parts
        folder = scan_outputs(self.target)[0]
        upper = replace(folder, path=folder.path.with_name(folder.path.name.upper()),
                        relative_parts=(*folder.relative_parts[:-1], folder.path.name.upper()))
        phone = MemoryPhone()
        with self.assertRaises(ValueError):
            transfer_outputs(phone, 'root', [folder, upper])
        self.assertEqual(phone.children, {'root': []})
        self.assertEqual(output_relative_parts(SimpleNamespace(path=folder.path)), (folder.path.name,))


if __name__ == '__main__':
    unittest.main()
