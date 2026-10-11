"""Thread-safe cooperative control, checked only at safe work boundaries."""
from threading import Condition
from time import monotonic


class OperationStopped(Exception):
    """A preview was deliberately stopped; do not replace the previous plan."""


class OperationControl:
    def __init__(self):
        self._condition = Condition()
        self._pause_requested = False
        self._paused = False
        self._stop_requested = False
        self._stopped = False

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
