"""Set output filesystem dates from an already resolved capture time."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def set_capture_file_times(path: Path, captured_at: datetime) -> None:
    timestamp = captured_at.timestamp()
    os.utime(path, (timestamp, timestamp))
    if os.name != "nt":
        return

    import ctypes
    import msvcrt
    from ctypes import wintypes

    ticks = round(timestamp * 10_000_000) + 116_444_736_000_000_000
    creation = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    set_file_time = kernel.SetFileTime
    set_file_time.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                             ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    set_file_time.restype = wintypes.BOOL
    descriptor = os.open(path, os.O_RDWR | os.O_BINARY)
    try:
        if not set_file_time(msvcrt.get_osfhandle(descriptor), ctypes.byref(creation), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        os.close(descriptor)
