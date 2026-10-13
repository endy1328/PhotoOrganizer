from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import test_phone_transfer_ui as fixtures


class LocationBackend(fixtures.FakeBackend):
    def __init__(self, suffix='first', missing=False):
        super().__init__()
        self.suffix, self.missing = suffix, missing

    def list_children(self, parent):
        names = {'DEVICE': ('storage', 'Internal storage'),
                 'storage-' + self.suffix: ('photos', 'Photos')}
        if parent not in names or self.missing and parent != 'DEVICE':
            return []
        key, name = names[parent]
        return [SimpleNamespace(id=key + '-' + self.suffix, name=name, is_folder=True)]


class PhoneLocationsUiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PhoneTransferUiTests.setUpClass.__func__)
    setUp = fixtures.PhoneTransferUiTests.setUp
    wait_until = fixtures.PhoneTransferUiTests.wait_until
    _close_worker_dialogs = fixtures.PhoneTransferUiTests._close_worker_dialogs

    def dialog(self, base, backend=None):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        folder = SimpleNamespace(path=Path('target/output_20240101_CAM'), files=(), size=0)
        with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=[folder]):
            dialog = PhoneTransferDialog(None, Path('target'), preferences_dir=base,
                backend_factory=lambda: backend or LocationBackend())
            self.wait_until(lambda: not dialog.busy and dialog.device_open)
        return dialog

    def enter_photos(self, dialog):
        for _ in range(2):
            dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
            self.wait_until(lambda: not dialog.busy)

    def test_saved_path_resolves_new_object_ids_after_reopening(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = self.dialog(base)
            self.enter_photos(first)
            with patch('photo_organizer.ui.phone_transfer_dialog.QInputDialog.getText', return_value=('My photos', True)):
                first.save_location_button.click()
            first.reject(); self.wait_until(lambda: not first.worker.isRunning())
            second = self.dialog(base, LocationBackend('second'))
            second.load_location_button.click()
            self.wait_until(lambda: not second.busy)
            self.assertEqual(second.destination_stack[-1], ('photos-second', 'Photos'))
            self.assertIn('Photos', second.destination_label.text())
            self.assertEqual(second.location_combo.count(), 1)
            self.assertNotIn('photos-first', (base / 'phone_locations.json').read_text(encoding='utf-8'))

    def test_missing_bookmark_path_does_not_keep_old_copy_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = self.dialog(base)
            self.enter_photos(first)
            with patch('photo_organizer.ui.phone_transfer_dialog.QInputDialog.getText', return_value=('Photos', True)):
                first.save_location_button.click()
            second = self.dialog(base, LocationBackend('second', missing=True))
            second.load_location_button.click()
            self.wait_until(lambda: not second.busy)
            self.assertFalse(second.copy_button.isEnabled())
            self.assertEqual(len(second.destination_stack), 1)

    def test_delete_and_busy_lock_of_saved_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog = self.dialog(Path(temp))
            self.enter_photos(dialog)
            with patch('photo_organizer.ui.phone_transfer_dialog.QInputDialog.getText', return_value=('Photos', True)):
                dialog.save_location_button.click()
            dialog.busy = True; dialog._update_buttons()
            self.assertFalse(dialog.save_location_button.isEnabled())
            self.assertFalse(dialog.load_location_button.isEnabled())
            dialog.busy = False; dialog._update_buttons()
            dialog.delete_location_button.click()
            self.assertEqual(dialog.location_combo.count(), 0)

    def test_bookmark_for_another_device_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog = self.dialog(Path(temp))
            self.enter_photos(dialog)
            with patch('photo_organizer.ui.phone_transfer_dialog.QInputDialog.getText', return_value=('Photos', True)):
                dialog.save_location_button.click()
            dialog.device_combo.setItemText(0, 'Another phone')
            with patch.object(dialog.worker, 'submit') as submit:
                dialog.load_location_button.click()
            submit.assert_not_called()
            self.assertIn('Test phone', dialog.status_label.text())


if __name__ == '__main__':
    unittest.main()
