import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtWidgets import QApplication

from photo_organizer.phone_transfer import RemoteEntry
from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
from test_phone_transfer import MemoryPhone


class BrowsableMemoryPhone(MemoryPhone):
    def __init__(self):
        super().__init__()
        self.children['DEVICE'] = [RemoteEntry('storage', 'Internal storage', True)]
        self.children['storage'] = []
        self.fail_folder_once = set()
        self.photos = self.create_folder('storage', 'Photos')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_devices(self):
        return [SimpleNamespace(id='phone', name='Test phone')]

    def open_device(self, device_id):
        if device_id != 'phone':
            raise ValueError('Unexpected device')

    def create_folder(self, parent_id, name):
        if name in self.fail_folder_once:
            self.fail_folder_once.remove(name)
            raise OSError('Simulated folder creation failure before upload')
        return super().create_folder(parent_id, name)

    def entry_at(self, parts, start=None):
        parent = start or self.photos.id
        entry = None
        for part in parts:
            matches = [child for child in self.children[parent] if child.name == part]
            if len(matches) != 1:
                raise AssertionError(f'Expected one {part!r} under {parent!r}; found {matches!r}')
            entry = matches[0]
            parent = entry.id
        return entry


class PhonePathLayoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.target = self.base / 'Target'
        self.target.mkdir()
        self.phone = BrowsableMemoryPhone()
        self.dialog = None
        self.addCleanup(self.close_dialog)

    def wait_until(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Phone worker did not reach the expected state')

    def close_dialog(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.wait_until(lambda: not self.dialog.worker.isRunning())
            self.app.processEvents()

    def add_output(self, model='CAM_A'):
        parts = ('2024년', '2024년 05월', '20240501', f'20240501_{model}',
                 f'output_20240501_{model}')
        folder = self.target.joinpath(*parts)
        folder.mkdir(parents=True)
        (folder / f'20240501_120000_{model}_0001.jpg').write_bytes(b'photo')
        return folder, parts

    def open_dialog(self, limit=None):
        self.dialog = PhoneTransferDialog(None, self.target, backend_factory=lambda: self.phone,
                                          log_base_dir=self.base, preferences_dir=self.base / 'prefs',
                                          video_limit_bytes=limit)
        self.wait_until(lambda: not self.dialog.busy and self.dialog.device_open)
        self.enter('Internal storage')
        self.enter('Photos')
        return self.dialog

    def enter(self, name):
        for index in range(self.dialog.remote_tree.topLevelItemCount()):
            item = self.dialog.remote_tree.topLevelItem(index)
            if item.text(0) == name:
                self.dialog._enter_folder(item)
                self.wait_until(lambda: not self.dialog.busy)
                return
        self.fail(f'Remote folder not listed: {name}')

    def test_guidance_and_destination_tooltip_track_selected_base_and_filter(self):
        folder, parts = self.add_output()
        dialog = self.open_dialog()
        self.assertIn('기준 위치', dialog.destination_hint.text())
        self.assertIn('목록의 경로 구조', dialog.destination_hint.text())
        self.assertNotIn('바로 아래에 output_', dialog.destination_hint.text())
        tooltip = dialog.output_tree.topLevelItem(0).toolTip(0)
        self.assertIn(str(folder), tooltip)
        self.assertIn('PC 원본', tooltip)
        self.assertIn('복사될 휴대폰 경로', tooltip)
        self.assertIn(' / '.join(['Test phone', 'Internal storage', 'Photos', *parts]), tooltip)
        dialog.model_selection.checkboxes['CAM_A'].setChecked(False)
        tooltip = dialog.output_tree.topLevelItem(0).toolTip(0)
        self.assertIn('전송 대상에서 제외', tooltip)
        self.assertIn(' / '.join(parts), tooltip)
        dialog._go_up()
        self.wait_until(lambda: not dialog.busy)
        tooltip = dialog.output_tree.topLevelItem(0).toolTip(0)
        self.assertIn(' / '.join(['Test phone', 'Internal storage', *parts]), tooltip)
        self.assertNotIn('Internal storage / Photos /', tooltip)

    def test_worker_preserves_full_hierarchy_and_reuses_existing_year(self):
        folder, parts = self.add_output()
        year = self.phone.create_folder(self.phone.photos.id, '2024년')
        unrelated = RemoteEntry('unrelated', 'notes.txt', False, 9)
        self.phone.children[year.id].append(unrelated)
        self.phone.data[unrelated.id] = b'keep data'
        dialog = self.open_dialog()
        dialog._start_transfer()
        self.wait_until(lambda: not dialog.busy)
        self.assertEqual([result.status for result in dialog.last_results], ['COPIED'])
        remote_year = self.phone.entry_at(parts[:1])
        self.assertEqual(remote_year.id, year.id)
        remote_file = self.phone.entry_at((*parts, next(iter(folder.iterdir())).name))
        self.assertEqual(self.phone.data[remote_file.id], b'photo')
        self.assertEqual(self.phone.data[unrelated.id], b'keep data')
        self.assertEqual(self.phone.entry_at(('2024년', 'notes.txt')), unrelated)
        self.assertNotIn(parts[-1], [entry.name for entry in self.phone.children[self.phone.photos.id]])

    def test_model_filter_and_video_limit_keep_relative_path(self):
        folder, parts = self.add_output('CAM_A')
        self.add_output('CAM_B')
        nested = folder / 'clips'
        nested.mkdir()
        (nested / 'small.mp4').write_bytes(b'123456789')
        (nested / 'large.mp4').write_bytes(b'1234567890')
        dialog = self.open_dialog(limit=10)
        dialog.model_selection.checkboxes['CAM_B'].setChecked(False)
        dialog._start_transfer()
        self.wait_until(lambda: not dialog.busy)
        self.assertEqual(sorted(result.status for result in dialog.last_results),
                         ['COPIED', 'COPIED', 'SIZE_EXCLUDED'])
        remote = self.phone.entry_at((*parts, 'clips', 'small.mp4'))
        self.assertEqual(self.phone.data[remote.id], b'123456789')
        self.assertNotIn('large.mp4', [entry.name for entry in self.phone.children[self.phone.entry_at((*parts, 'clips')).id]])
        date = self.phone.entry_at(parts[:3])
        self.assertEqual([entry.name for entry in self.phone.children[date.id]], ['20240501_CAM_A'])

    def test_retry_after_device_refresh_preserves_original_relative_path(self):
        folder, parts = self.add_output()
        filename = next(iter(folder.iterdir())).name
        self.phone.fail_folder_once.add(parts[-1])
        dialog = self.open_dialog()
        dialog._start_transfer()
        self.wait_until(lambda: not dialog.busy)
        self.assertEqual([result.status for result in dialog.last_results], ['FAILED'])
        self.assertFalse(dialog.device_open)
        dialog.refresh_button.click()
        self.wait_until(lambda: not dialog.busy and dialog.device_open)
        self.enter('Internal storage')
        self.enter('Photos')
        self.assertTrue(dialog.retry_button.isEnabled())
        dialog._start_retry()
        self.wait_until(lambda: not dialog.busy)
        self.assertEqual([result.status for result in dialog.last_results], ['COPIED'])
        remote = self.phone.entry_at((*parts, filename))
        self.assertEqual(self.phone.data[remote.id], b'photo')
        self.assertNotIn(parts[-1], [entry.name for entry in self.phone.children[self.phone.photos.id]])

    def test_cancel_while_listing_base_does_not_create_year_folder(self):
        self.add_output()
        dialog = self.open_dialog()
        original_list = self.phone.list_children
        def cancel_after_listing(parent_id):
            entries = original_list(parent_id)
            if parent_id == self.phone.photos.id:
                dialog.worker.cancel_event.set()
            return entries
        self.phone.list_children = cancel_after_listing
        dialog._start_transfer()
        self.wait_until(lambda: not dialog.busy)
        self.assertEqual([result.status for result in dialog.last_results], ['CANCELLED'])
        self.assertEqual(self.phone.children[self.phone.photos.id], [])
        self.assertEqual(self.phone.data, {})


if __name__ == '__main__':
    unittest.main()
