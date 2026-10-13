import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QSplitter,QTreeWidget,QTableWidget


class PhoneViewPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from photo_organizer.ui.phone_view_preferences import PhoneViewPreferences
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'phone_view.json'
        self.dialog=QDialog();self.addCleanup(self.dialog.close)
        layout=QVBoxLayout(self.dialog)
        self.dialog.panel_splitter=QSplitter(Qt.Vertical)
        self.dialog.remote_tree=QTreeWidget();self.dialog.remote_tree.setHeaderLabels(['remote'])
        self.dialog.output_tree=QTreeWidget();self.dialog.output_tree.setHeaderLabels(['path','count','bytes','excluded'])
        self.dialog.results_table=QTableWidget(0,3);self.dialog.results_table.setHorizontalHeaderLabels(['result','path','message'])
        for widget in (self.dialog.remote_tree,self.dialog.output_tree,self.dialog.results_table):
            self.dialog.panel_splitter.addWidget(widget)
        layout.addWidget(self.dialog.panel_splitter)
        self.dialog.resize(780,600);self.dialog.show();self.app.processEvents()
        self.prefs=PhoneViewPreferences(self.dialog,self.path)

    def test_geometry_splitter_header_roundtrip_without_session_ids(self):
        self.dialog.panel_splitter.setSizes([100,200,260])
        header=self.dialog.output_tree.header();header.moveSection(3,0);header.resizeSection(0,350)
        result=self.dialog.results_table.horizontalHeader();result.moveSection(2,0);result.resizeSection(1,430)
        self.assertTrue(self.prefs.save())
        saved=json.loads(self.path.read_text(encoding='utf-8'))
        self.assertNotIn('device',saved)
        header.moveSection(0,3);header.resizeSection(0,80)
        result.moveSection(0,2);result.resizeSection(1,90)
        self.dialog.panel_splitter.setSizes([200,200,200])
        self.prefs.restore();self.app.processEvents()
        self.assertEqual(header.logicalIndex(0),3)
        self.assertEqual(header.sectionSize(0),350)
        self.assertEqual(result.logicalIndex(0),2)
        self.assertEqual(result.sectionSize(1),430)
        self.assertEqual(self.dialog.panel_splitter.sizes(),saved['splitter'])

    def test_corrupt_large_and_malformed_preferences_are_safe(self):
        for text in ('broken',' '*65537,json.dumps({'version':1,'geometry':[True,0,9999999,0],
                            'maximized':'yes','splitter':[1,-2,3],
                            'tables':{'output_tree':{'order':[0,0,0,0],'widths':[True,-1,9999999,50]}}})):
            self.path.write_text(text,encoding='utf-8')
            self.prefs.restore()
            self.assertEqual(self.dialog.output_tree.header().logicalIndex(0),0)
            self.assertGreater(self.dialog.width(),0)

    def test_offscreen_geometry_is_clamped_and_maximized_flag_restored(self):
        self.path.write_text(json.dumps({'version':1,'geometry':[90000,90000,9000,9000],'maximized':True}),encoding='utf-8')
        self.prefs.restore();self.app.processEvents()
        self.assertTrue(self.dialog.isMaximized())
        available=self.dialog.screen().availableGeometry()
        rect=self.dialog.normalGeometry()
        self.assertLessEqual(rect.width(),available.width())
        self.assertLessEqual(rect.height(),available.height())
        self.assertTrue(available.contains(rect.center()))

    def test_no_path_is_noop_and_failed_atomic_save_preserves_previous(self):
        from photo_organizer.ui.phone_view_preferences import PhoneViewPreferences
        from unittest.mock import patch
        self.assertTrue(PhoneViewPreferences(self.dialog,None).save())
        self.assertTrue(self.prefs.save());before=self.path.read_bytes()
        with patch('photo_organizer.ui.phone_view_preferences.os.replace',side_effect=OSError('blocked')):
            self.assertFalse(self.prefs.save())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])
