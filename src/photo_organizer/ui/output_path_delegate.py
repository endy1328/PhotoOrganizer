"""Native item chrome with a contrasting output-folder suffix in path text."""
import re
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPalette, QTextLayout, QTextCharFormat, QTextOption
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate


def output_suffix_start(text):
    match = re.search(r'(?:^|[/\\])(output_[^/\\]*)(?=[/\\]|$)', text, re.IGNORECASE)
    return match.start(1) if match else None


def output_display_range(original, displayed):
    """Python character range; paint converts it to Qt UTF-16 offsets."""
    start = output_suffix_start(original)
    if start is None:
        return None
    if displayed == original:
        return start, len(displayed) - start
    prefix = 0
    while prefix < min(len(original), len(displayed)) and original[prefix] == displayed[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(original) - prefix, len(displayed) - prefix) and
           original[-suffix - 1] == displayed[-suffix - 1]):
        suffix += 1
    if start < prefix:
        return start, len(displayed) - start
    if suffix and len(original) - suffix >= start:
        return prefix, len(displayed) - prefix
    if suffix and start >= len(original) - suffix:
        rendered_start = len(displayed) - suffix + start - (len(original) - suffix)
        return rendered_start, len(displayed) - rendered_start
    return None


class OutputPathDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        original = styled.text
        if output_suffix_start(original) is None or not styled.state & QStyle.State_Enabled:
            super().paint(painter, option, index)
            return
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, styled, styled.widget).adjusted(2, 0, -2, 0)
        displayed = styled.fontMetrics.elidedText(original, styled.textElideMode, max(0, rect.width()))
        span = output_display_range(original, displayed)
        if span is None:
            super().paint(painter, option, index)
            return
        group = QPalette.Active if styled.state & QStyle.State_Active else QPalette.Inactive
        selected = bool(styled.state & QStyle.State_Selected)
        role = QPalette.HighlightedText if selected else QPalette.Text
        background = styled.palette.color(group, QPalette.Highlight if selected else QPalette.Base)
        # Warm text is readable on dark selection; blue retains contrast on light surfaces.
        accent = (QColor('#ffe29a') if selected else QColor('#76bdff')) if background.lightness() < 128 else QColor('#005fa3')
        chrome = QStyleOptionViewItem(styled)
        chrome.text = ''
        painter.save()
        try:
            style.drawControl(QStyle.CE_ItemViewItem, chrome, painter, styled.widget)
            painter.setClipRect(rect, Qt.IntersectClip)
            painter.setFont(styled.font)
            painter.setPen(styled.palette.color(group, role))
            layout = QTextLayout(displayed, styled.font)
            text_option = QTextOption()
            text_option.setWrapMode(QTextOption.NoWrap)
            text_option.setTextDirection(styled.direction)
            alignment = QStyle.visualAlignment(styled.direction, styled.displayAlignment)
            text_option.setAlignment(alignment & Qt.AlignHorizontal_Mask)
            layout.setTextOption(text_option)
            formatting = QTextLayout.FormatRange()
            formatting.start = len(displayed[:span[0]].encode('utf-16-le')) // 2
            formatting.length = len(displayed[span[0]:span[0] + span[1]].encode('utf-16-le')) // 2
            formatting.format = QTextCharFormat()
            formatting.format.setForeground(accent)
            layout.setFormats([formatting])
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(max(0, rect.width()))
            layout.endLayout()
            y = rect.top()
            if alignment & Qt.AlignBottom:
                y += rect.height() - line.height()
            elif alignment & Qt.AlignVCenter:
                y += (rect.height() - line.height()) / 2
            layout.draw(painter, QPointF(rect.left(), y))
        finally:
            painter.restore()
