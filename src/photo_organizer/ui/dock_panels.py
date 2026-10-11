"""Independent native docks, with responsive defaults and explicit user choices."""
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import QDockWidget, QApplication


class DockPanelsMixin:
    def _build_dock_panels(self):
        self._arranging_docks = True
        self._custom_dock_layout = False
        self._dock_user_visibility = {'image': True, 'detail': True}
        self._dock_auto_hidden = set()
        self._dock_default_orientation = None
        self.image_dock = QDockWidget('선택 파일 이미지', self)
        self.detail_dock = QDockWidget('상세 정보 / 메타정보', self)
        for key, dock, panel in (('image', self.image_dock, self.selection_image_panel),
                                 ('detail', self.detail_dock, self.selection_detail_panel)):
            dock.setObjectName('photo_' + key + '_dock')
            dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
            dock.setWidget(panel)
            dock.setMinimumWidth(140)
            dock.installEventFilter(self)
            dock.dockLocationChanged.connect(lambda area, k=key: self._dock_placement_changed(k))
            dock.topLevelChanged.connect(lambda floating, k=key: self._dock_placement_changed(k))
            dock.visibilityChanged.connect(lambda visible, k=key: self._dock_visibility_changed(k))
        self.view_menu = self.menuBar().addMenu('보기')
        self.view_menu.addAction(self.image_dock.toggleViewAction())
        self.view_menu.addAction(self.detail_dock.toggleViewAction())
        self.view_menu.addSeparator()
        self.reset_docks_action = self.view_menu.addAction('기본 패널 배치 복원')
        self.reset_docks_action.triggered.connect(self.restore_default_dock_layout)
        self._arranging_docks = False
        self._apply_default_dock_layout()

    def _dock_placement_changed(self, key):
        if not self._arranging_docks:
            self._custom_dock_layout = True

    def _dock_visibility_changed(self, key):
        if self._arranging_docks:
            return
        dock = self.image_dock if key == 'image' else self.detail_dock
        self._dock_user_visibility[key] = not dock.isHidden()
        self._dock_auto_hidden.discard(key)
        self._details_auto_restore = bool(self._dock_auto_hidden)
        self._sync_details_toggle()

    def _settle_default_dock_sizes(self, wide):
        if self._custom_dock_layout or self._dock_default_orientation != wide:
            return
        self._arranging_docks = True
        try:
            self.layout().activate()
            docks = [self.image_dock, self.detail_dock]
            self.resizeDocks(docks, [340, 340] if wide else [120, 120],
                             Qt.Horizontal if wide else Qt.Vertical)
            if not wide:
                self.resizeDocks(docks, [self.width() // 2] * 2, Qt.Horizontal)
            self.layout().activate()
        finally:
            self._arranging_docks = False

    def _sync_details_toggle(self):
        self.details_toggle.blockSignals(True)
        self.details_toggle.setChecked(any(not dock.isHidden() for dock in (self.image_dock, self.detail_dock)))
        self.details_toggle.blockSignals(False)

    def _set_all_docks_visible(self, visible):
        self._dock_auto_hidden.clear()
        self._details_auto_restore = False
        self._arranging_docks = True
        try:
            for key, dock in (('image', self.image_dock), ('detail', self.detail_dock)):
                self._dock_user_visibility[key] = visible
                dock.setVisible(visible)
        finally:
            self._arranging_docks = False

    def _apply_default_dock_layout(self):
        wide = self.width() >= 1400
        area = Qt.RightDockWidgetArea if wide else Qt.BottomDockWidgetArea
        orientation = Qt.Vertical if wide else Qt.Horizontal
        self._arranging_docks = True
        try:
            for dock in (self.image_dock, self.detail_dock):
                dock.setFloating(False)
                self.removeDockWidget(dock)
                self.addDockWidget(area, dock)
            self.splitDockWidget(self.image_dock, self.detail_dock, orientation)
            self.resizeDocks([self.image_dock, self.detail_dock], [340, 340] if wide else [120, 120],
                             Qt.Horizontal if wide else Qt.Vertical)
            if not wide:
                self.resizeDocks([self.image_dock, self.detail_dock], [self.width() // 2] * 2, Qt.Horizontal)
            for key, dock in (('image', self.image_dock), ('detail', self.detail_dock)):
                dock.setVisible(self._dock_user_visibility[key] and key not in self._dock_auto_hidden)
            self._dock_default_orientation = wide
            progress = getattr(self, 'execution_progress_dock', None)
            if (progress is not None and not progress.isHidden() and not progress.isFloating()
                    and getattr(self, '_execution_dock_sized', False)):
                self._arrange_default_execution_progress()
        finally:
            self._arranging_docks = False
        self._sync_details_toggle()
        QTimer.singleShot(0, lambda: self._settle_default_dock_sizes(wide))

    def restore_default_dock_layout(self):
        self._custom_dock_layout = False
        self._dock_user_visibility = {'image': True, 'detail': True}
        self._dock_auto_hidden.clear()
        self._short_workspace = False
        self._apply_default_dock_layout()
        self._update_dock_layout()
        progress = getattr(self, 'execution_progress_dock', None)
        if progress is not None:
            self._arranging_docks = True
            try:
                progress.setFloating(False)
                self.removeDockWidget(progress)
                self.addDockWidget(Qt.BottomDockWidgetArea, progress, Qt.Vertical)
                progress.hide()
                self._execution_dock_sized = False
                self._dock_user_visibility['execution_progress'] = False
            finally:
                self._arranging_docks = False

    def _update_dock_layout(self):
        if not self._custom_dock_layout and self._dock_default_orientation != (self.width() >= 1400):
            self._apply_default_dock_layout()
        compact = self.height() < 600 or (self.width() < 900 and self.height() < 680)
        spacious = self.height() >= 700 or (self.width() >= 900 and self.height() >= 650)
        self._arranging_docks = True
        try:
            if compact and not self._short_workspace:
                self._short_workspace = True
                for key, dock in (('image', self.image_dock), ('detail', self.detail_dock)):
                    if not dock.isHidden() and not dock.isFloating():
                        self._dock_auto_hidden.add(key)
                        dock.hide()
            elif spacious:
                self._short_workspace = False
                for key in self._dock_auto_hidden:
                    dock = self.image_dock if key == 'image' else self.detail_dock
                    dock.setVisible(self._dock_user_visibility[key])
                self._dock_auto_hidden.clear()
            self._details_auto_restore = bool(self._dock_auto_hidden)
        finally:
            self._arranging_docks = False
        self._sync_details_toggle()

    def eventFilter(self, watched, event):
        if (isinstance(watched, QDockWidget) and event.type() == QEvent.Resize
                and not self._arranging_docks and QApplication.mouseButtons() & Qt.LeftButton):
            self._custom_dock_layout = True
        return super().eventFilter(watched, event)
