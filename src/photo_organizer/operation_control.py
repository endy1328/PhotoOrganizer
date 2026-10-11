"""Thread-safe cooperative control, checked only at safe work boundaries."""
from threading import Condition
from time import monotonic
from contextlib import contextmanager
from dataclasses import dataclass, replace
from collections import deque


@dataclass(frozen=True)
class FileActivity:
    key: str
    source_path: str
    stage: str


@dataclass(frozen=True)
class FileResult:
    key: str
    source_path: str
    status: str
    message: str = ''


@dataclass(frozen=True)
class FileResultSummary:
    completed_keys: frozenset[str]
    succeeded: int
    failed: int
    incomplete: int
    had_error: bool


class OperationStopped(Exception):
    """A preview was deliberately stopped; do not replace the previous plan."""


class OperationControl:
    def __init__(self):
        self._condition = Condition()
        self._pause_requested = False
        self._paused = False
        self._stop_requested = False
        self._stopped = False
        self._active_files = {}
        self._file_results = deque(maxlen=50)
        self._result_statuses = {}
        self._result_summary = None
        self._result_had_error = False

    def report_file_result(self, key, source_path, status, message=''):
        with self._condition:
            self._file_results.append(FileResult(str(key), str(source_path), str(status), str(message)))
            self._result_statuses[str(key)] = str(status)
            self._result_had_error |= status != 'SUCCESS'
            self._result_summary = None

    def result_summary(self):
        """Lossless per-plan completion bookkeeping, separate from bounded history."""
        with self._condition:
            if self._result_summary is None:
                statuses = tuple(self._result_statuses.values())
                self._result_summary = FileResultSummary(
                    frozenset(self._result_statuses), statuses.count('SUCCESS'),
                    sum(status in {'ERROR', 'FAILED', 'UNCERTAIN'} for status in statuses),
                    sum(status not in {'SUCCESS', 'ERROR', 'FAILED', 'UNCERTAIN'} for status in statuses),
                    self._result_had_error)
            return self._result_summary

    def drain_file_results(self):
        with self._condition:
            results = tuple(self._file_results)
            self._file_results.clear()
            return results

    def activity_snapshot(self) -> tuple[FileActivity, ...]:
        with self._condition:
            return tuple(record for token, record in self._active_files.values())

    @contextmanager
    def file_activity(self, key, source_path, stage):
        key, token = str(key), object()
        with self._condition:
            previous = self._active_files.get(key)
            self._active_files[key] = (token, FileActivity(key, str(source_path), str(stage)))
        try:
            yield
        finally:
            with self._condition:
                current = self._active_files.get(key)
                if current is not None and current[0] is token:
                    if previous is None:
                        del self._active_files[key]
                    else:
                        self._active_files[key] = previous

    def update_file_activity(self, key, stage):
        with self._condition:
            current = self._active_files.get(str(key))
            if current is not None:
                self._active_files[str(key)] = (current[0], replace(current[1], stage=str(stage)))

    @property
    def pause_requested(self):
        with self._condition:
            return self._pause_requested

    @property
    def paused(self):
        with self._condition:
            return self._paused

    @property
    def stop_requested(self):
        with self._condition:
            return self._stop_requested

    @property
    def stopped(self):
        with self._condition:
            return self._stopped

    def request_pause(self):
        with self._condition:
            if not self._stop_requested:
                self._pause_requested = True
            self._condition.notify_all()

    def resume(self):
        with self._condition:
            self._pause_requested = False
            self._condition.notify_all()

    def request_stop(self):
        with self._condition:
            self._stop_requested = True
            self._pause_requested = False
            self._condition.notify_all()

    def checkpoint(self):
        with self._condition:
            while self._pause_requested and not self._stop_requested:
                self._paused = True
                self._condition.notify_all()
                self._condition.wait()
            self._paused = False
            if self._stop_requested:
                self._stopped = True
                self._condition.notify_all()
                return False
            return True

    def wait_until_paused(self, timeout):
        """Bounded observer wait used by non-Qt integrations and tests."""
        deadline = monotonic() + timeout
        with self._condition:
            while not self._paused:
                remaining = deadline - monotonic()
                if remaining <= 0 or self._stop_requested:
                    return False
                self._condition.wait(remaining)
            return True
