"""Display-only preferences, independent of processing settings and job signatures."""
from __future__ import annotations

import json
import base64
import binascii
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QByteArray, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu


class ViewPreferences:
    def __init__(self, window, path: Path | None):
        self.window = window
        self.path = path
        self.tables = {name: getattr(window, name) for name in
                       ('preview_table', 'results_table', 'error_table', 'delete_table')}
        self.menus = {}
        self._widths = {}
        for name, table in self.tables.items():
            header = table.horizontalHeader()
            self._widths[name] = {i: max(40, table.columnWidth(i)) for i in range(table.columnCount())}
            header.sectionResized.connect(lambda i, old, new, key=name: self._remember_width(key, i, new))
            header.setSectionsMovable(True)
            header.setContextMenuPolicy(Qt.CustomContextMenu)
            menu = self.column_menu(table)
            header.customContextMenuRequested.connect(
                lambda point, h=header, m=menu: m.exec(h.mapToGlobal(point)))

    def _remember_width(self, key, index, width):
        if width > 0:
            self._widths[key][index] = width

    def column_menu(self, table):
        if table in self.menus:
            return self.menus[table]
        menu = QMenu(table)
        required = 3 if table is self.window.preview_table else 0
        for index in range(table.columnCount()):
            item = table.horizontalHeaderItem(index)
            action = menu.addAction(item.text() if item else str(index + 1))
            action.setData(index)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(index))
            action.setEnabled(index != required)
            action.toggled.connect(lambda checked, i=index, t=table: t.setColumnHidden(i, not checked))
        def refresh():
            for action in menu.actions():
                action.blockSignals(True)
                action.setChecked(not table.isColumnHidden(action.data()))
                action.blockSignals(False)
        menu.aboutToShow.connect(refresh)
        self.menus[table] = menu
        return menu

    def restore(self):
        data = {}
        try:
            if self.path is not None and self.path.stat().st_size <= 65536:
                loaded = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    data = loaded
        except (OSError, ValueError, RecursionError):
            pass
        for name, table in self.tables.items():
            saved = data.get('tables', {}).get(name, {}) if isinstance(data.get('tables'), dict) else {}
            if not isinstance(saved, dict):
                saved = {}
            count = table.columnCount()
            order = saved.get('order')
            if not (isinstance(order, list) and len(order) == count and
                    all(type(i) is int for i in order) and sorted(order) == list(range(count))):
                order = [3, 2, 6, 5, 0, 1, 4, 7] if name == 'preview_table' and count == 8 else list(range(count))
            header = table.horizontalHeader()
            for visual, logical in enumerate(order):
                header.moveSection(header.visualIndex(logical), visual)
            widths = saved.get('widths', [])
            if name == 'preview_table' and not widths:
                table.setColumnWidth(3, 360)
                table.setColumnWidth(2, 110)
                table.setColumnWidth(5, 160)
                table.setColumnWidth(6, 220)
            if isinstance(widths, list):
                for index, width in enumerate(widths[:count]):
                    if type(width) is int and 40 <= width <= 2000:
                        self._widths[name][index] = width
                        table.setColumnWidth(index, width)
            hidden = saved.get('hidden', [4, 7] if name == 'preview_table' else [])
            if not isinstance(hidden, list):
                hidden = []
            required = 3 if name == 'preview_table' else 0
            for index in range(count):
                table.setColumnHidden(index, index in hidden and index != required)
        geometry = data.get('geometry')
        if (isinstance(geometry, list) and len(geometry) == 4 and
                all(type(i) is int and -100000 <= i <= 100000 for i in geometry)):
            rect = QRect(*geometry)
            screens = QGuiApplication.screens()
            screen = next((s for s in screens if s.availableGeometry().contains(rect.center())), self.window.screen())
        else:
            rect = self.window.geometry()
            screen = self.window.screen()
        available = screen.availableGeometry()
        width = min(max(400, rect.width()), available.width())
        height = min(max(300, rect.height()), available.height())
        x = max(available.left(), min(rect.x(), available.right() - width + 1))
        y = max(available.top(), min(rect.y(), available.bottom() - height + 1))
        self.window.setGeometry(x, y, width, height)
        if not self._docks() and type(data.get('details_visible')) is bool:
            self.window.details_toggle.setChecked(data['details_visible'])
        sizes = data.get('splitter', {})
        self._saved_sizes = sizes if isinstance(sizes, dict) else {}
        self.restore_splitter()
        self._restore_docks(data)

    def _docks(self):
        return {key: dock for key in ('image', 'detail')
                if (dock := getattr(self.window, key + '_dock', None)) is not None}

    def _restore_docks(self, data):
        docks = self._docks()
        if not docks:
            return
        old_guard = getattr(self.window, '_arranging_docks', False)
        self.window._arranging_docks = True
        try:
            encoded = data.get('dock_state')
            state = None
            if type(encoded) is str and 0 < len(encoded) <= 32768:
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                    # Qt's native marker and our version avoid interpreting unrelated data.
                    if 8 <= len(decoded) <= 24576 and decoded[:8] == b'\x00\x00\x00\xff\x00\x00\x00\x01':
                        state = QByteArray(decoded)
                except (ValueError, binascii.Error):
                    pass
            if state is not None:
                fallback = self.window.saveState(1)
                if self.window.restoreState(state, 1):
                    self.window._custom_dock_layout = True
                else:
                    self.window.restoreState(fallback, 1)
            saved_visibility = data.get('dock_visibility')
            if not isinstance(saved_visibility, dict):
                saved_visibility = {}
            legacy = data.get('details_visible')
            current = getattr(self.window, '_dock_user_visibility', {})
            visibility = {}
            for key, dock in docks.items():
                visible = saved_visibility.get(key)
                if type(visible) is not bool:
                    visible = legacy if type(legacy) is bool else current.get(key, not dock.isHidden())
                visibility[key] = visible
                dock.setVisible(visible)
                if dock.isFloating():
                    self._clamp_floating_dock(dock)
            self.window._dock_user_visibility = visibility
            toggle = getattr(self.window, 'details_toggle', None)
            if toggle is not None:
                previous = toggle.blockSignals(True)
                toggle.setChecked(any(visibility.values()))
                toggle.blockSignals(previous)
        finally:
            self.window._arranging_docks = old_guard

    def _clamp_floating_dock(self, dock):
        rect = dock.geometry()
        screen = next((screen for screen in QGuiApplication.screens()
                       if screen.availableGeometry().contains(rect.center())), self.window.screen())
        available = screen.availableGeometry()
        width = min(max(120, rect.width()), available.width())
        height = min(max(100, rect.height()), available.height())
        x = max(available.left(), min(rect.x(), available.right() - width + 1))
        y = max(available.top(), min(rect.y(), available.bottom() - height + 1))
        dock.setGeometry(x, y, width, height)

    def restore_splitter(self):
        splitter = getattr(self.window, 'workspace_splitter', None)
        if splitter is None:
            return
        sizes = getattr(self, '_saved_sizes', {}).get(str(splitter.orientation().value))
        if (isinstance(sizes, list) and len(sizes) == splitter.count() and
                all(type(v) is int and 0 <= v <= 100000 for v in sizes) and sum(sizes) > 0):
            splitter.setSizes(sizes)

    def remember_splitter(self):
        splitter = getattr(self.window, 'workspace_splitter', None)
        if splitter is None:
            return
        if sum(splitter.sizes()) > 0:
            if not hasattr(self, '_saved_sizes'):
                self._saved_sizes = {}
            self._saved_sizes[str(splitter.orientation().value)] = splitter.sizes()

    def save(self):
        if self.path is None:
            return True
        rect = self.window.normalGeometry() if self.window.isMaximized() else self.window.geometry()
        splitter = getattr(self.window, 'workspace_splitter', None)
        sizes = dict(getattr(self, '_saved_sizes', {}))
        if splitter is not None:
            sizes[str(splitter.orientation().value)] = splitter.sizes()
        self._saved_sizes = sizes
        data = {'geometry': [rect.x(), rect.y(), rect.width(), rect.height()],
                'details_visible': bool(getattr(self.window, '_details_auto_restore', False) or
                                        self.window.details_toggle.isChecked()), 'splitter': sizes, 'tables': {}}
        docks = self._docks()
        if docks:
            data['dock_state'] = base64.b64encode(bytes(self.window.saveState(1))).decode('ascii')
            visibility = getattr(self.window, '_dock_user_visibility', {})
            data['dock_visibility'] = {key: visibility.get(key, not dock.isHidden()) for key, dock in docks.items()}
        for name, table in self.tables.items():
            header = table.horizontalHeader()
            data['tables'][name] = {'widths': [table.columnWidth(i) or self._widths[name].get(i, 100)
                                              for i in range(table.columnCount())],
                                   'order': [header.logicalIndex(i) for i in range(table.columnCount())],
                                   'hidden': [i for i in range(table.columnCount()) if table.isColumnHidden(i)]}
        staging = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.view_preferences_', suffix='.tmp', delete=False) as handle:
                staging = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False)
            os.replace(staging, self.path)
            return True
        except OSError:
            return False
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass
