from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_phone_transfer_ui as fixtures
from PySide6.QtCore import Qt


class PhoneModelFilterUiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PhoneTransferUiTests.setUpClass.__func__)
    setUp = fixtures.PhoneTransferUiTests.setUp
    wait_until = fixtures.PhoneTransferUiTests.wait_until
    _close_worker_dialogs = fixtures.PhoneTransferUiTests._close_worker_dialogs

    def dialog(self):
        from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog
        self.folders = [SimpleNamespace(path=Path(f'target/output_{date}_{model}'),
            files=(Path(f'target/output_{date}_{model}/a.jpg'),), size=8)
            for date, model in [('20240101', 'CAM_A'), ('20240102', 'CAM_A'), ('20240101', 'CAM_B')]]
        with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=self.folders):
            dialog = PhoneTransferDialog(None, Path('target'), backend_factory=fixtures.FakeBackend)
            self.wait_until(lambda: not dialog.busy and dialog.device_open)
        return dialog

    def test_model_exclusion_applies_to_all_dates_and_transfer_payload(self):
        dialog = self.dialog()
        dialog.model_selection.checkboxes['CAM_A'].setChecked(False)
        self.assertEqual(dialog._selected_folders(), [self.folders[2]])
        self.assertTrue(dialog.output_tree.topLevelItem(0).isDisabled())
        self.assertIn('선택 1개 폴더 / 전송 1개 파일', dialog.selection_label.text())
        dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
        self.wait_until(lambda: not dialog.busy)
        with patch.object(dialog.worker, 'submit') as submit:
            dialog._start_transfer()
        self.assertEqual(submit.call_args.args, ('transfer', 'storage', [self.folders[2]]))
        self.assertFalse(dialog.model_selection.isEnabled())

    def test_manual_folder_choice_survives_model_off_on(self):
        dialog = self.dialog()
        dialog.output_tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)
        dialog.model_selection.checkboxes['CAM_A'].setChecked(False)
        dialog.model_selection.checkboxes['CAM_A'].setChecked(True)
        self.assertEqual(dialog._selected_folders(), self.folders[1:])
        self.assertFalse(dialog.output_tree.topLevelItem(0).isDisabled())

    def test_all_models_unchecked_disables_copy(self):
        dialog = self.dialog()
        dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
        self.wait_until(lambda: not dialog.busy)
        for box in dialog.model_selection.checkboxes.values():
            box.setChecked(False)
        self.assertEqual(dialog._selected_folders(), [])
        self.assertFalse(dialog.copy_button.isEnabled())
        self.assertIn('선택 0개 폴더', dialog.selection_label.text())

    def test_refresh_keeps_model_exclusion_and_selects_new_models(self):
        dialog = self.dialog()
        dialog.model_selection.checkboxes['CAM_A'].setChecked(False)
        dialog.output_tree.topLevelItem(2).setCheckState(0, Qt.Unchecked)
        new_folder = SimpleNamespace(path=Path('target/output_20240103_CAM_C'),
            files=(Path('target/output_20240103_CAM_C/a.jpg'),), size=9)
        refreshed = self.folders + [new_folder]
        with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=refreshed):
            dialog.refresh_button.click()
            self.wait_until(lambda: not dialog.busy and dialog.device_open)
        self.assertEqual(dialog._selected_folders(), [new_folder])
        self.assertFalse(dialog.model_selection.checkboxes['CAM_A'].isChecked())
        self.assertTrue(dialog.model_selection.checkboxes['CAM_C'].isChecked())

    def test_model_filter_summary_retains_video_size_limit(self):
        import tempfile
        from photo_organizer.phone_transfer import scan_outputs, plan_video_transfer
        dialog = self.dialog()
        with tempfile.TemporaryDirectory() as temp:
            for model in ('CAM_A', 'CAM_B'):
                directory = Path(temp) / f'output_20240101_{model}'
                directory.mkdir()
                (directory / 'photo.jpg').write_bytes(b'x' * 3)
                (directory / 'large.mp4').write_bytes(b'x' * 10)
            folders = scan_outputs(Path(temp))
            plans = [plan_video_transfer([folder], 10) for folder in folders]
            dialog._completed('initialize', (folders, [], plans))
            dialog.model_selection.checkboxes['CAM_A'].setChecked(False)
            self.assertEqual(dialog._selected_folders(), [folders[1]])
            self.assertIn('전송 1개 파일', dialog.selection_label.text())
            self.assertIn('용량 제한 제외 1개', dialog.selection_label.text())

    def test_maximize_and_fullscreen_restore_without_closing_worker(self):
        from PySide6.QtTest import QTest
        dialog = self.dialog()
        self.assertTrue(dialog.windowFlags() & Qt.WindowMaximizeButtonHint)
        dialog.showMaximized(); self.app.processEvents()
        self.assertTrue(dialog.isMaximized())
        dialog.fullscreen_button.click(); self.app.processEvents()
        self.assertTrue(dialog.isFullScreen())
        QTest.keyClick(dialog, Qt.Key_Escape); self.app.processEvents()
        self.assertFalse(dialog.isFullScreen())
        self.assertTrue(dialog.isMaximized())
        self.assertTrue(dialog.worker.isRunning())


if __name__ == '__main__':
    unittest.main()
