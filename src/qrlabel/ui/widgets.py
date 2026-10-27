"""Small reusable widgets."""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import BANNER_STYLES


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 22))
        self.setGraphicsEffect(shadow)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 20)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.header.addWidget(t)
        self.header.addStretch(1)
        if title:
            self.body.addLayout(self.header)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("Muted")
            s.setWordWrap(True)
            self.body.addWidget(s)


class Banner(QLabel):
    """Inline status message with a severity colour."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hide()

    def show_message(self, text: str, level: str = "info") -> None:
        self.setStyleSheet(f"QLabel {{ {BANNER_STYLES[level]} border-radius: 8px; padding: 9px 12px; }}")
        self.setText(text)
        self.show()

    def clear_message(self) -> None:
        self.hide()


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 2)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def labeled(label: str, widget: QWidget) -> QWidget:
    """Field label stacked above its input."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lbl = QLabel(label)
    lbl.setObjectName("FieldLabel")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return w


def chip(text: str = "", gray: bool = False) -> QLabel:
    c = QLabel(text)
    c.setObjectName("ChipGray" if gray else "Chip")
    c.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return c


def nice_calendar(edit) -> None:
    """Give a QDateEdit a clean calendar popup (styled by #NiceCalendar in the theme)."""
    from PySide6.QtCore import QDate, QSize
    from PySide6.QtGui import QFont, QTextCharFormat
    from PySide6.QtWidgets import QCalendarWidget, QToolButton

    from .icons import icon

    cal = QCalendarWidget()
    cal.setObjectName("NiceCalendar")
    cal.setGridVisible(False)
    cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    cal.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
    head = QTextCharFormat()
    head.setForeground(QColor("#64748B"))
    head.setFontWeight(QFont.Weight.DemiBold)
    cal.setHeaderTextFormat(head)
    weekend = QTextCharFormat()
    weekend.setForeground(QColor("#E11D48"))
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        cal.setWeekdayTextFormat(day, weekend)
    today = QTextCharFormat()
    today.setForeground(QColor("#2563EB"))
    today.setFontWeight(QFont.Weight.Bold)
    today.setFontUnderline(True)
    cal.setDateTextFormat(QDate.currentDate(), today)
    for name, ic in (("qt_calendar_prevmonth", "chevron-left"), ("qt_calendar_nextmonth", "chevron-right")):
        b = cal.findChild(QToolButton, name)
        if b is not None:
            b.setIcon(icon(ic, "#334155", size=18))
            b.setIconSize(QSize(18, 18))
    cal.setMinimumSize(320, 290)
    edit.setCalendarPopup(True)
    edit.setCalendarWidget(cal)


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def sticker_pixmap(label: QPixmap, max_w: int, max_h: int) -> QPixmap:
    """Label image scaled to fit, drawn as a white sticker with rounded corners and a soft shadow."""
    pad = 14
    scale = min((max_w - 2 * pad) / label.width(), (max_h - 2 * pad) / label.height())
    w, h = int(label.width() * scale), int(label.height() * scale)
    mode = Qt.TransformationMode.FastTransformation if scale >= 1 else Qt.TransformationMode.SmoothTransformation
    scaled = label.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, mode)

    out = QPixmap(w + 2 * pad, h + 2 * pad)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(8, 0, -1):  # cheap soft shadow
        p.setBrush(QColor(15, 23, 42, 7))
        p.drawRoundedRect(QRectF(pad - i + 1, pad - i + 4, w + 2 * i - 2, h + 2 * i - 2), 6 + i, 6 + i)
    path = QPainterPath()
    path.addRoundedRect(QRectF(pad, pad, w, h), 6, 6)
    p.setClipPath(path)
    p.drawPixmap(pad, pad, scaled)
    p.end()
    return out
