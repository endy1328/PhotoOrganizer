"""Options shared by non-interactive metadata and video child processes."""
from __future__ import annotations

import os
import subprocess


def hidden_process_kwargs() -> dict:
    options = {'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        options.update(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startupinfo)
    return options
