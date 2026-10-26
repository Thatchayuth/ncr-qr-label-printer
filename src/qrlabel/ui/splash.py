"""Startup splash screen: logo, name, real loading steps and a smooth progress bar."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from .. import __version__
from ..app.paths import resource_path

W, H, SHADOW = 480, 310, 18
MIN_VISIBLE_MS = 1100


class SplashScreen(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W + 2 * SHADOW, H + 2 * SHADOW)
        self.logo = QPixmap(str(resource_path("app.png")))
        self.status = "Starting..."
        self._progress = 0.0  # 0..1 as drawn
        self._shine = 0.0  # moving highlight on the bar
        self._clock = QElapsedTimer()
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_drawn_progress)
        self._shine_timer = QTimer(self)
        self._shine_timer.timeout.connect(self._tick)
        self._shine_timer.start(30)
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.move(screen.availableGeometry().center() - self.rect().center())

    # ---------------------------------------------------------------- API

    def start(self) -> None:
        self._clock.start()
        self.show()
        self.raise_()
        QApplication.processEvents()

    def step(self, text: str, progress: int) -> None:
        """Show a loading step; progress is 0-100. Keeps the UI painted during blocking work."""
        self.status = text
        self._animate_to(progress / 100, 220)
        for _ in range(4):  # let the bar move a little before the next blocking step
            QApplication.processEvents()

    def finish(self, then: Callable[[], None]) -> None:
        """Fill the bar, wait the minimum display time, fade out, then call `then`."""
        self.status = "Ready"
        wait = max(0, MIN_VISIBLE_MS - self._clock.elapsed())
        self._animate_to(1.0, max(250, wait))

        def fade() -> None:
            self._fade = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade.setDuration(260)
            self._fade.setStartValue(1.0)
            self._fade.setEndValue(0.0)
            self._fade.finished.connect(done)
            then()  # show the main window underneath while the splash fades
            self.raise_()
            self._fade.start()

        def done() -> None:
            self._shine_timer.stop()
            self.close()

        QTimer.singleShot(max(260, wait + 60), fade)

    # ------------------------------------------------------------ internals

    def _animate_to(self, value: float, ms: int) -> None:
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(max(self._progress, value))
        self._anim.start()

    def _set_drawn_progress(self, v) -> None:
        self._progress = float(v)
        self.update()

    def _tick(self) -> None:
        self._shine = (self._shine + 0.018) % 1.4
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = QRectF(SHADOW, SHADOW, W, H)

        # soft shadow
        for i in range(SHADOW, 0, -2):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(2, 6, 23, int(5 + (SHADOW - i) * 0.6)))
            p.drawRoundedRect(card.adjusted(-i * 0.6, -i * 0.4, i * 0.6, i * 0.9), 20 + i * 0.5, 20 + i * 0.5)

        # card background
        path = QPainterPath()
        path.addRoundedRect(card, 20, 20)
        p.setClipPath(path)
        bg = QLinearGradient(card.topLeft(), card.bottomRight())
        bg.setColorAt(0.0, QColor("#0F172A"))
        bg.setColorAt(0.65, QColor("#172554"))
        bg.setColorAt(1.0, QColor("#1E3A8A"))
        p.fillRect(card, bg)
        for center, radius, color in (
            (QPointF(card.right() - 40, card.top() + 30), 190, QColor(99, 102, 241, 70)),
            (QPointF(card.left() + 30, card.bottom() + 10), 170, QColor(59, 130, 246, 55)),
        ):
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(card, glow)
        p.setClipping(False)
        p.setPen(QColor(255, 255, 255, 22))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)

        # logo
        size = 76
        logo_rect = QRectF(card.center().x() - size / 2, card.top() + 44, size, size)
        if not self.logo.isNull():
            p.drawPixmap(logo_rect.toRect(), self.logo)

        # title + subtitle
        title = QFont(self.font())
        title.setPointSizeF(17)
        title.setBold(True)
        p.setFont(title)
        p.setPen(QColor("#F8FAFC"))
        p.drawText(QRectF(card.left(), logo_rect.bottom() + 16, W, 30), Qt.AlignmentFlag.AlignHCenter, "NCR QR Label Printer")
        sub = QFont(self.font())
        sub.setPointSizeF(9.5)
        p.setFont(sub)
        p.setPen(QColor("#94A3B8"))
        p.drawText(QRectF(card.left(), logo_rect.bottom() + 48, W, 22), Qt.AlignmentFlag.AlignHCenter, "Asset QR labels from Dynamics AX")

        # progress bar
        bar_w, bar_h = 300, 6
        bar = QRectF(card.center().x() - bar_w / 2, card.bottom() - 70, bar_w, bar_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(bar, 3, 3)
        fill_w = max(bar_h, bar_w * self._progress)
        fill = QRectF(bar.left(), bar.top(), fill_w, bar_h)
        grad = QLinearGradient(fill.topLeft(), fill.topRight())
        grad.setColorAt(0.0, QColor("#3B82F6"))
        grad.setColorAt(1.0, QColor("#A5B4FC"))
        p.setBrush(grad)
        p.drawRoundedRect(fill, 3, 3)
        # moving shine inside the filled part
        sx = bar.left() + (self._shine - 0.2) * bar_w
        shine = QLinearGradient(QPointF(sx - 40, 0), QPointF(sx + 40, 0))
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 110))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(fill, 3, 3)
        p.setClipPath(clip)
        p.fillRect(fill, shine)
        p.restore()

        # status + percent
        small = QFont(self.font())
        small.setPointSizeF(9)
        p.setFont(small)
        p.setPen(QColor("#CBD5E1"))
        p.drawText(QRectF(bar.left(), bar.bottom() + 10, bar_w - 40, 20), Qt.AlignmentFlag.AlignLeft, self.status)
        p.setPen(QColor("#93C5FD"))
        p.drawText(QRectF(bar.left(), bar.bottom() + 10, bar_w, 20), Qt.AlignmentFlag.AlignRight, f"{int(self._progress * 100)}%")

        # version
        tiny = QFont(self.font())
        tiny.setPointSizeF(8)
        p.setFont(tiny)
        p.setPen(QColor("#64748B"))
        p.drawText(QRectF(card.left(), card.bottom() - 28, W - 20, 18), Qt.AlignmentFlag.AlignRight, f"v{__version__}")
        p.drawText(QRectF(card.left() + 20, card.bottom() - 28, W, 18), Qt.AlignmentFlag.AlignLeft, "NCR")
        p.end()
