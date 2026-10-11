"""One media execution per Windows PC, including separate deployment folders."""
from __future__ import annotations

import os
import threading

_LOCAL_LOCK = threading.Lock()
MUTEX_NAME = r'Global\PhotoOrganizerMediaExecution_v2'


class ExecutionLock:
    def __init__(self):
        self._handle = None
        self._file = None
        self._held = False

    def __enter__(self):
        if not _LOCAL_LOCK.acquire(blocking=False):
            raise RuntimeError('다른 PhotoOrganizer 작업이 실행 중입니다. 완료 후 다시 시도해주세요.')
        try:
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
                kernel.CreateMutexW.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
                kernel.ReleaseMutex.restype = wintypes.BOOL
                kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
                kernel.CloseHandle.restype = wintypes.BOOL
                self._kernel = kernel
                self._handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
                if not self._handle:
                    raise RuntimeError('PhotoOrganizer 실행 잠금을 만들 수 없습니다.')
                status = kernel.WaitForSingleObject(self._handle, 0)
                if status not in (0, 0x80):  # WAIT_OBJECT_0 or abandoned mutex acquired.
                    kernel.CloseHandle(self._handle)
                    self._handle = None
                    raise RuntimeError('다른 PhotoOrganizer 작업이 실행 중이거나 잠금을 확인할 수 없습니다.')
            else:
                import fcntl
                import tempfile
                from pathlib import Path
                self._file = (Path(tempfile.gettempdir()) / 'photoorganizer-execution-v2.lock').open('a+b')
                try:
                    fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    self._file.close()
                    self._file = None
                    raise RuntimeError('다른 PhotoOrganizer 작업이 실행 중입니다.') from exc
            self._held = True
            return self
        except BaseException:
            _LOCAL_LOCK.release()
            raise

    def __exit__(self, *_args):
        if not self._held:
            return
        try:
            if self._handle is not None:
                self._kernel.ReleaseMutex(self._handle)
                self._kernel.CloseHandle(self._handle)
                self._handle = None
            elif self._file is not None:
                import fcntl
                fcntl.flock(self._file, fcntl.LOCK_UN)
                self._file.close()
                self._file = None
        finally:
            self._held = False
            _LOCAL_LOCK.release()
