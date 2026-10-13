"""Reusable, hidden workers for native calls which cannot cancel a Python thread.

The private binary pipe only carries requests from this process, never user files.
Windows Job Objects ensure killing a worker also ends its ffprobe descendants.
"""
from __future__ import annotations

import os
import pickle
import queue
import struct
import subprocess
import sys
import threading
from pathlib import Path

from .process_utils import hidden_process_kwargs
from .operation_control import current_control

_registry_lock = threading.Lock()


def worker_executable():
    """Use the running interpreter image, avoiding Windows Store activation aliases."""
    if os.name != 'nt' or getattr(sys, 'frozen', False):
        return sys.executable
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetModuleFileNameW(None, buffer, len(buffer))
    if not size or size >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def suspended_options(options):
    if os.name == 'nt':
        options['creationflags'] = options.get('creationflags', 0) | 0x4  # CREATE_SUSPENDED
    return options


def resume_process(process):
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes as w
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('thread_id', w.DWORD),
                    ('owner_pid', w.DWORD), ('base_priority', w.LONG),
                    ('delta_priority', w.LONG), ('flags', w.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenThread.restype = w.HANDLE
    kernel.ResumeThread.argtypes = [w.HANDLE]
    kernel.ResumeThread.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.owner_pid == process.pid:
                thread = kernel.OpenThread(2, False, entry.thread_id)
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if kernel.ResumeThread(thread) == 0xffffffff:
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                finally:
                    kernel.CloseHandle(thread)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError('내부 작업 프로세스의 주 스레드를 찾지 못했습니다.')
    finally:
        kernel.CloseHandle(snapshot)


class ProcessTree:
    def __init__(self, process):
        self.handle = None
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('per_process', ctypes.c_int64), ('per_job', ctypes.c_int64),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active_limit', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_mem', ctypes.c_size_t),
                        ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(handle, int(process._handle))):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(handle)
            raise error
        self.kernel, self.handle = kernel, handle

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _send(stream, value):
    data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack('!I', len(data)))
    stream.write(data)
    stream.flush()


def _receive(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError('작업 프로세스가 종료되었습니다.')
    size = struct.unpack('!I', header)[0]
    parts, remaining = [], size
    while remaining:
        block = stream.read(remaining)
        if not block:
            raise EOFError('작업 응답이 완료되지 않았습니다.')
        parts.append(block)
        remaining -= len(block)
    return pickle.loads(b''.join(parts))


class IsolatedWorker:
    def __init__(self):
        options = suspended_options(hidden_process_kwargs())
        options['stdin'] = subprocess.PIPE
        environment = dict(os.environ)
        source = str(Path(__file__).resolve().parents[1])
        # The real image may be a base interpreter: retain this environment's
        # virtualenv packages and source paths explicitly.
        environment['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(
            [source] + [str(Path(path).resolve()) for path in sys.path if path]
            + [environment.get('PYTHONPATH', '')]))
        executable = worker_executable()
        command = ([executable, '--internal-worker'] if getattr(sys, 'frozen', False)
                   else [executable, '-m', 'photo_organizer.isolated_work'])
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment, **options)
        self.tree = None
        try:
            self.tree = ProcessTree(self.process)
            resume_process(self.process)
        except BaseException:
            if self.tree is not None:
                self.tree.close()
            self.process.kill()
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            raise
        self.closed = False

    def call(self, operation, arguments):
        control = current_control()
        if control:
            control.raise_if_interrupted()
        result = queue.Queue(maxsize=1)
        _send(self.process.stdin, (operation, arguments))
        def read():
            try:
                result.put(_receive(self.process.stdout))
            except BaseException as exc:
                result.put((False, str(exc)))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while True:
                if control:
                    control.raise_if_interrupted()
                try:
                    success, value = result.get(timeout=.025)
                    break
                except queue.Empty:
                    continue
            if control:
                control.raise_if_interrupted()
            if not success:
                raise RuntimeError(value)
            return value
        except BaseException:
            self.close()
            raise
        finally:
            if self.closed:
                reader.join(2)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.tree.close()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def isolated_call(operation, arguments):
    """One reusable worker per operation thread; pause kills and replaces it."""
    control = current_control()
    if control is None:
        with IsolatedWorker() as worker:
            return worker.call(operation, arguments)
    control.raise_if_interrupted()
    key = threading.get_ident()
    with _registry_lock:
        workers = getattr(control, '_isolated_workers', None)
        if workers is None:
            workers = control._isolated_workers = {}
        worker = workers.get(key)
        if worker is None or worker.closed:
            worker = workers[key] = IsolatedWorker()
    return worker.call(operation, arguments)


def close_workers(control):
    with _registry_lock:
        workers = tuple(getattr(control, '_isolated_workers', {}).values())
        control._isolated_workers = {}
    failure = None
    for worker in workers:
        try:
            worker.close()
        except Exception as exc:
            failure = failure or exc
    if failure is not None:
        raise failure


def worker_main():
    def binary_stream(stream, std_handle, mode):
        if stream is not None:
            return stream.buffer
        # A windowed PyInstaller executable sets sys.std* to None even when
        # the parent supplied valid Windows pipe handles.
        if os.name != 'nt':
            raise RuntimeError('내부 작업 파이프를 열 수 없습니다.')
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle(std_handle)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY |
                                         (os.O_RDONLY if mode == 'rb' else os.O_WRONLY))
        return os.fdopen(descriptor, mode)
    incoming = binary_stream(sys.stdin, -10, 'rb')
    outgoing = binary_stream(sys.stdout, -11, 'wb')
    # Libraries may print diagnostics: preserve the protocol stream separately.
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    sys.stdout = sys.stderr
    while True:
        try:
            operation, arguments = _receive(incoming)
        except EOFError:
            return 0
        try:
            if operation == 'metadata':
                from .metadata import MetadataExtractor
                value = MetadataExtractor().extract(*arguments)
            elif operation == 'photo':
                from .engine import OrganizerEngine
                engine = object.__new__(OrganizerEngine)
                value = engine._create_photo_mobile_output(*arguments)
            else:
                raise ValueError('지원하지 않는 내부 작업')
            _send(outgoing, (True, value))
        except Exception as exc:
            _send(outgoing, (False, f'{type(exc).__name__}: {exc}'))


if __name__ == '__main__':
    raise SystemExit(worker_main())
