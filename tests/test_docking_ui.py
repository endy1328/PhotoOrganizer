import unittest
import test_responsive_ui as fixtures
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget


class DockingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResponsiveUiTests.setUpClass()
        cls.app = fixtures.ResponsiveUiTests.app

    setUp = fixtures.ResponsiveUiTests.setUp
    cleanup = fixtures.ResponsiveUiTests.cleanup

    def test_independent_native_panels_and_view_menu(self):
        w = self.window
        self.assertIsInstance(w.image_dock, QDockWidget)
        self.assertIsInstance(w.detail_dock, QDockWidget)
        self.assertEqual(w.image_dock.objectName(), 'photo_image_dock')
        self.assertEqual(w.detail_dock.objectName(), 'photo_detail_dock')
        expected = Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        for dock in (w.image_dock, w.detail_dock):
            self.assertEqual(dock.allowedAreas(), expected)
            for feature in (QDockWidget.DockWidgetMovable, QDockWidget.DockWidgetFloatable,
                            QDockWidget.DockWidgetClosable):
                self.assertTrue(dock.features() & feature)
        w.image_dock.toggleViewAction().trigger()
        self.assertFalse(w.image_dock.isVisible())
        self.assertTrue(w.detail_dock.isVisible())
        self.assertFalse(w._dock_user_visibility['image'])

    def test_user_location_and_floating_survive_resize_and_reset(self):
        w = self.window
        w.addDockWidget(Qt.LeftDockWidgetArea, w.detail_dock)
        self.assertTrue(w._custom_dock_layout)
        w.resize(1600, 900)
        self.app.processEvents()
        self.assertEqual(w.dockWidgetArea(w.detail_dock), Qt.LeftDockWidgetArea)
        w.image_dock.setFloating(True)
        w.resize(1204, 900)
        self.app.processEvents()
        self.assertTrue(w.image_dock.isFloating())
        w.restore_default_dock_layout()
        self.app.processEvents()
        self.assertFalse(w.image_dock.isFloating())
        self.assertFalse(w._custom_dock_layout)
        self.assertEqual(w.dockWidgetArea(w.detail_dock), Qt.BottomDockWidgetArea)

    def test_panel_controls_during_busy_do_not_change_job(self):
        w = self.window
        w._job_dirty = False
        before = w._job_state.job_id
        signature = w._request_signature(w._request_from_inputs(False))
        w._set_busy(True)
        w.image_dock.toggleViewAction().trigger()
        w.addDockWidget(Qt.LeftDockWidgetArea, w.detail_dock)
        w.restore_default_dock_layout()
        self.assertTrue(w.preview_table.isEnabled())
        self.assertTrue(w.selection_detail.isEnabled())
        self.assertFalse(w._job_dirty)
        self.assertEqual(w._job_state.job_id, before)
        self.assertEqual(w._request_signature(w._request_from_inputs(False)), signature)
        w._set_busy(False)

    def test_tabbed_inactive_panel_remains_user_visible(self):
        w = self.window
        w.tabifyDockWidget(w.image_dock, w.detail_dock)
        w.detail_dock.raise_()
        self.app.processEvents()
        self.assertTrue(w._dock_user_visibility['image'])
        self.assertTrue(w._dock_user_visibility['detail'])

    def test_default_bottom_panels_share_width(self):
        w = self.window
        w.resize(1920, 1080)
        self.app.processEvents()
        w.resize(1204, 1032)
        self.app.processEvents()
        self.assertLess(abs(w.image_dock.width() - w.detail_dock.width()), 80)
