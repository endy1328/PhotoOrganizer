import os
from pathlib import Path
import sys
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QStyle, QTableWidget, QTableWidgetItem


class OutputPathDelegateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_component_boundary_and_unicode_parser(self):
        from photo_organizer.ui.output_path_delegate import output_suffix_start
        for text,expected in [('E:/사진/output_20241012_CAM/영상.mp4',6),
                              ('E:\\사진\\output_20241012_CAM\\영상.mp4',6),
                              ('output_CAM/file.jpg',0),('a/OUTPUT_CAM/output_X/f.jpg',2),
                              ('a/notoutput_CAM/f.jpg',None),('a/output/f.jpg',None)]:
            with self.subTest(text=text):
                self.assertEqual(output_suffix_start(text),expected)

    def test_native_paint_preserves_check_selection_disabled_and_data(self):
        from photo_organizer.ui.output_path_delegate import OutputPathDelegate
        table=QTableWidget(1,1)
        self.addCleanup(table.close)
        text='E:/사진/output_20241012_CAM/영상.mp4'
        item=QTableWidgetItem(text);item.setCheckState(Qt.Checked)
        table.setItem(0,0,item)
        delegate=OutputPathDelegate(table)
        table.setItemDelegate(delegate)
        index=table.model().index(0,0)
        before=delegate.sizeHint(QStyleOptionViewItem(),index)
        for selected,enabled,dark,elide in [(False,True,False,Qt.ElideNone),(True,True,False,Qt.ElideRight),
                                          (False,False,False,Qt.ElideMiddle),(True,True,True,Qt.ElideMiddle)]:
            option=QStyleOptionViewItem();option.rect=QRect(0,0,280,36)
            option.widget=table;option.textElideMode=elide
            option.state=QStyle.State_Active | (QStyle.State_Enabled if enabled else QStyle.State_None)
            if selected:option.state |= QStyle.State_Selected
            if dark:
                option.palette.setColor(QPalette.Base,Qt.black)
                option.palette.setColor(QPalette.Text,Qt.white)
                option.palette.setColor(QPalette.Highlight,Qt.darkBlue)
                option.palette.setColor(QPalette.HighlightedText,Qt.white)
            image=QImage(280,36,QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter=QPainter(image)
            try:delegate.paint(painter,option,index)
            finally:painter.end()
            self.assertFalse(image.isNull())
            self.assertEqual(item.text(),text)
            self.assertEqual(item.checkState(),Qt.Checked)
        self.assertEqual(delegate.sizeHint(QStyleOptionViewItem(),index),before)

    def test_highlight_range_survives_native_middle_elision(self):
        from photo_organizer.ui.output_path_delegate import output_display_range
        self.assertEqual(output_display_range('root/output_CAM/file.jpg','root/…file.jpg'),(5,9))
        self.assertIsNone(output_display_range('root/notoutput_CAM/file.jpg','root/…file.jpg'))
        self.assertEqual(output_display_range('longroot/output_CAM/file.jpg','…/output_CAM/file.jpg'),(2,19))

    def test_non_bmp_prefix_uses_utf16_and_disabled_matches_native_paint(self):
        from photo_organizer.ui.output_path_delegate import OutputPathDelegate
        from PySide6.QtGui import QTextLayout
        from PySide6.QtWidgets import QStyledItemDelegate
        from unittest.mock import patch
        table=QTableWidget(1,1);self.addCleanup(table.close)
        text='E:/📷사진/output_CAM/영상.mp4'
        table.setItem(0,0,QTableWidgetItem(text))
        option=QStyleOptionViewItem();option.rect=QRect(0,0,600,36)
        option.widget=table;option.state=QStyle.State_Enabled|QStyle.State_Active
        option.textElideMode=Qt.ElideNone
        captured=[]
        def capture(*args):
            layout=QTextLayout(*args);captured.append(layout);return layout
        delegate=OutputPathDelegate(table)
        image=QImage(600,36,QImage.Format_ARGB32);image.fill(Qt.transparent)
        painter=QPainter(image)
        try:
            with patch('photo_organizer.ui.output_path_delegate.QTextLayout',side_effect=capture) as factory:
                factory.FormatRange=QTextLayout.FormatRange
                delegate.paint(painter,option,table.model().index(0,0))
        finally:painter.end()
        self.assertEqual(captured[0].formats()[0].start,len('E:/📷사진/'.encode('utf-16-le'))//2)
        option.state=QStyle.State_Active
        images=[]
        for renderer in (delegate,QStyledItemDelegate(table)):
            image=QImage(600,36,QImage.Format_ARGB32);image.fill(Qt.transparent)
            painter=QPainter(image)
            try:renderer.paint(painter,option,table.model().index(0,0))
            finally:painter.end()
            images.append(image)
        self.assertEqual(images[0],images[1])
