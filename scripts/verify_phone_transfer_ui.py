"""Read-only UI smoke check: enumerate USB phone folders; never create/upload."""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from photo_organizer.phone_transfer import OutputFolder
from photo_organizer.ui.phone_transfer_dialog import PhoneTransferDialog

app = QApplication([])
app.setFont(QFont('Malgun Gothic', 9))
base = Path(__file__).resolve().parents[1]
folder = base / 'sample_target' / 'output_20240501_SM-F926N'
with patch('photo_organizer.ui.phone_transfer_dialog.scan_outputs', return_value=[
        OutputFolder(folder, (folder / 'sample.jpg', folder / 'sample.mp4'), 2000000)]):
    dialog = PhoneTransferDialog(None, base / 'sample_target')
    dialog.show()
    deadline = time.monotonic() + 15
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert dialog.device_open, dialog.status_label.text()
    assert dialog.remote_tree.topLevelItemCount() > 0
    dialog._enter_folder(dialog.remote_tree.topLevelItem(0))
    deadline = time.monotonic() + 15
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert dialog.copy_button.isEnabled(), dialog.status_label.text()
    app.processEvents()
    assert dialog.grab().save(str(base / 'phone_transfer_ui.png'))
    print('READ_ONLY_UI_BROWSE_OK', 'visible_folders=', dialog.remote_tree.topLevelItemCount())
    dialog.reject()
    deadline = time.monotonic() + 10
    while dialog.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert not dialog.worker.isRunning()
