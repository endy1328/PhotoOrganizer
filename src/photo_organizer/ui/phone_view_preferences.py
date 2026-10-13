"""Display-only mobile transfer preferences; never stores device session IDs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication


class PhoneViewPreferences:
    def __init__(self, dialog, path: Path | None):
        self.dialog = dialog
        self.path = Path(path) if path is not None else None
        self.tables = {name: getattr(dialog, name) for name in
                       ('output_tree', 'remote_tree', 'results_table')}

    @staticmethod
    def _header(widget):
        return widget.horizontalHeader() if hasattr(widget, 'horizontalHeader') else widget.header()

    def _load(self):
        if self.path is None:
            return {}
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                return {}
            data = json.loads(raw)
            if isinstance(data, dict) and type(data.get('version')) is int and data['version'] == 1:
                return data
        except (OSError, ValueError, TypeError, RecursionError):
            pass
        return {}

    def restore(self):
        data = self._load()
        geometry = data.get('geometry')
        if (isinstance(geometry, list) and len(geometry) == 4 and
                all(type(value) is int and abs(value) <= 100000 for value in geometry) and
                geometry[2] > 0 and geometry[3] > 0):
            rect = QRect(*geometry)
            screen = QGuiApplication.screenAt(rect.center()) or self.dialog.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                width = min(available.width(), max(400, rect.width()))
                height = min(available.height(), max(300, rect.height()))
                x = min(max(rect.x(), available.left()), available.right() - width + 1)
                y = min(max(rect.y(), available.top()), available.bottom() - height + 1)
                self.dialog.setGeometry(x, y, width, height)
        tables = data.get('tables')
        for name, widget in self.tables.items():
            saved = tables.get(name) if isinstance(tables, dict) else None
            if not isinstance(saved, dict):
                continue
            header = self._header(widget)
            count = header.count()
            order = saved.get('order')
            if (isinstance(order, list) and len(order) == count and
                    all(type(value) is int for value in order) and sorted(order) == list(range(count))):
                for visual, logical in enumerate(order):
                    header.moveSection(header.visualIndex(logical), visual)
            widths = saved.get('widths')
            if isinstance(widths, list) and len(widths) == count:
                for logical, width in enumerate(widths):
                    if type(width) is int and 40 <= width <= 2000:
                        header.resizeSection(logical, width)
        sizes = data.get('splitter')
        if (isinstance(sizes, list) and len(sizes) == self.dialog.panel_splitter.count() and
                all(type(value) is int and 0 <= value <= 100000 for value in sizes) and sum(sizes) > 0):
            self.dialog.panel_splitter.setSizes(sizes)
        if type(data.get('maximized')) is bool:
            state = self.dialog.windowState()
            self.dialog.setWindowState(state | Qt.WindowMaximized if data['maximized'] else state & ~Qt.WindowMaximized)

    def save(self) -> bool:
        if self.path is None:
            return True
        full_screen = self.dialog.isFullScreen()
        maximized = (getattr(self.dialog, '_before_fullscreen_maximized', False)
                     if full_screen else self.dialog.isMaximized())
        rect = self.dialog.normalGeometry() if maximized or full_screen else self.dialog.geometry()
        tables = {}
        for name, widget in self.tables.items():
            header = self._header(widget)
            tables[name] = {
                'order': [header.logicalIndex(index) for index in range(header.count())],
                'widths': [min(2000, max(40, header.sectionSize(index))) for index in range(header.count())],
            }
        data = {'version': 1, 'geometry': [rect.x(), rect.y(), rect.width(), rect.height()],
                'maximized': maximized, 'splitter': self.dialog.panel_splitter.sizes(),
                'tables': tables}
        temporary = None
        try:
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(raw) > 65536:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.phone_view_preferences_',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
