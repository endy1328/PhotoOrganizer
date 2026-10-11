"""Run pure engine work off the GUI thread and emit progress only."""
from PySide6.QtCore import QThread, Signal


class OperationWorker(QThread):
    progress = Signal(str, int, int)

    def __init__(self, method, args, options, parent=None):
        super().__init__(parent)
        self.method = method
        self.args = args
        self.options = dict(options)
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.method(*self.args, progress_callback=self.progress.emit, **self.options)
        except BaseException as exc:
            self.error = exc
