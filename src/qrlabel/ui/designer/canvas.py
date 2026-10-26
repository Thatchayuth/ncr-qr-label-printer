"""Label Designer canvas. Scene units are millimetres (1 scene unit = 1 mm).

Each element is drawn from the same raster renderer used for printing, so what you
see on the canvas is what the printer receives.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from ...domain.layout import mm_to_dots
from ...domain.models import LabelElement, LabelTemplate
from ...rendering.raster import rasterize_element
from ...services.template_io import snap
from ..widgets import pil_to_pixmap

HANDLE_MM = 1.4
SELECT_COLOR = QColor("#2563EB")


def footprint(el: LabelElement) -> tuple[float, float]:
    """Width/height the element occupies on the label (after rotation)."""
    w, h = el.w_mm, el.h_mm
    if el.kind == "line":
        if w >= h:
            h = max(h, el.thickness_mm)
        else:
            w = max(w, el.thickness_mm)
    return (h, w) if el.rotation in (90, 270) else (w, h)


class ElementItem(QGraphicsObject):
    changed = Signal(object)  # emits self after move / resize

    def __init__(self, el: LabelElement, ctx_provider: Callable[[], tuple]) -> None:
        super().__init__()
        self.el = el
        self._ctx = ctx_provider  # -> (template, values, qr_text, ecc, snap_step)
        self._pix: QPixmap | None = None
        self._pix_rect = QRectF()
        self._resizing = False
        self.bypass_snap = False  # exact moves from the property panel / arrow keys
        self.warnings: list[str] = []
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setPos(el.x_mm, el.y_mm)
        self.apply_lock()
        self.refresh()

    def apply_lock(self) -> None:
        movable = not self.el.locked
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
        self.setCursor(Qt.CursorShape.SizeAllCursor if movable else Qt.CursorShape.ArrowCursor)
        self.update()

    # ----------------------------------------------------------- rendering

    def refresh(self) -> None:
        template, values, qr_text, ecc, _ = self._ctx()
        self.prepareGeometryChange()
        placed, self.warnings = rasterize_element(self.el, template, values, qr_text, ecc)
        if placed is None:
            self._pix = None
        else:
            mm_per_dot = 25.4 / template.dpi
            ox = placed.x - mm_to_dots(self.el.x_mm, template.dpi)
            oy = placed.y - mm_to_dots(self.el.y_mm, template.dpi)
            img = placed.image.convert("L")
            self._pix = pil_to_pixmap(img)
            self._pix_rect = QRectF(ox * mm_per_dot, oy * mm_per_dot, img.width * mm_per_dot, img.height * mm_per_dot)
            # make white transparent so overlapping elements stay visible
            mask = self._pix.createMaskFromColor(QColor(255, 255, 255), Qt.MaskMode.MaskInColor)
            self._pix.setMask(mask)
        self.update()

    def boundingRect(self) -> QRectF:
        fw, fh = footprint(self.el)
        return QRectF(-0.3, -0.3, fw + HANDLE_MM + 0.6, fh + HANDLE_MM + 0.6)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        fw, fh = footprint(self.el)
        if self._pix is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(self._pix_rect, self._pix, QRectF(self._pix.rect()))
        else:
            painter.fillRect(QRectF(0, 0, fw, fh), QColor(37, 99, 235, 18))
        if self.isSelected():
            pen = QPen(QColor("#64748B") if self.el.locked else SELECT_COLOR, 0,
                       Qt.PenStyle.DashLine if self.el.locked else Qt.PenStyle.SolidLine)
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, fw, fh))
            if not self.el.locked:
                painter.setBrush(QBrush(QColor("#FFFFFF")))
                painter.drawRect(self._handle_rect())
        else:
            pen = QPen(QColor(148, 163, 184), 0, Qt.PenStyle.DotLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, fw, fh))
        if self.warnings:
            pen = QPen(QColor("#F59E0B"), 0)
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(QRectF(0, 0, fw, fh))

    def move_exact(self, x: float, y: float) -> None:
        self.bypass_snap = True
        try:
            self.setPos(x, y)
        finally:
            self.bypass_snap = False

    def _handle_rect(self) -> QRectF:
        fw, fh = footprint(self.el)
        return QRectF(fw - HANDLE_MM / 2, fh - HANDLE_MM / 2, HANDLE_MM, HANDLE_MM)

    # --------------------------------------------------------------- moving

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            template, *_, step = self._ctx()
            if self.bypass_snap:
                step = 0
            fw, fh = footprint(self.el)
            x = min(max(snap(value.x(), step), 0.0), max(0.0, template.width_mm - fw))
            y = min(max(snap(value.y(), step), 0.0), max(0.0, template.height_mm - fh))
            return QPointF(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.el.x_mm, self.el.y_mm = round(self.pos().x(), 2), round(self.pos().y(), 2)
            self.changed.emit(self)
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event) -> None:
        if self.el.locked:
            super().hoverMoveEvent(event)
            return
        on_handle = self.isSelected() and self._handle_rect().adjusted(-0.5, -0.5, 0.5, 0.5).contains(event.pos())
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if on_handle else Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self.el.locked and self.isSelected() and self._handle_rect().adjusted(-0.5, -0.5, 0.5, 0.5).contains(event.pos()):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._resizing:
            super().mouseMoveEvent(event)
            return
        template, *_, step = self._ctx()
        min_size = 1.0
        fw = max(min_size, snap(event.pos().x(), step))
        fh = max(min_size, snap(event.pos().y(), step))
        fw = min(fw, template.width_mm - self.pos().x())
        fh = min(fh, template.height_mm - self.pos().y())
        w, h = (fh, fw) if self.el.rotation in (90, 270) else (fw, fh)
        if self.el.kind == "qr":
            w = h = max(w, h) if self.el.rotation in (0, 180) else min(w, h)
            w = h = min(w, template.width_mm - self.pos().x(), template.height_mm - self.pos().y())
        if self.el.kind == "line":
            if self.el.w_mm >= self.el.h_mm:
                h = self.el.h_mm
            else:
                w = self.el.w_mm
        self.el.w_mm, self.el.h_mm = round(w, 2), round(h, 2)
        self.refresh()
        self.changed.emit(self)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LabelScene(QGraphicsScene):
    """Draws the sticker, margin and grid behind the elements."""

    def __init__(self) -> None:
        super().__init__()
        self.template: LabelTemplate | None = None
        self.show_grid = True
        self.grid_step = 1.0

    def set_template(self, t: LabelTemplate) -> None:
        self.template = t
        pad = 6.0
        self.setSceneRect(QRectF(-pad, -pad, t.width_mm + 2 * pad, t.height_mm + 2 * pad))
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#E2E8F0"))
        t = self.template
        if not t:
            return
        label = QRectF(0, 0, t.width_mm, t.height_mm)
        shadow = QRectF(label).translated(0.25, 0.4)
        painter.fillRect(shadow, QColor(15, 23, 42, 40))
        painter.fillRect(label, QColor("#FFFFFF"))
        if self.show_grid and self.grid_step > 0:
            pen = QPen(QColor("#CBD5E1"), 0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            step = self.grid_step
            while step < 1.0 and (t.width_mm / step) > 120:
                step *= 2
            x = step
            while x < t.width_mm:
                y = step
                while y < t.height_mm:
                    painter.drawPoint(QPointF(x, y))
                    y += step
                x += step
        m = t.margin_mm
        pen = QPen(QColor("#F87171"), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(QRectF(m, m, t.width_mm - 2 * m, t.height_mm - 2 * m))


class LabelView(QGraphicsView):
    zoom_changed = Signal(float)
    nudge = Signal(float, float)
    delete_pressed = Signal()

    def __init__(self, scene: LabelScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("QGraphicsView { background: #E2E8F0; border-radius: 10px; }")
        self._zoom = 1.0

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, pixels_per_mm: float) -> None:
        pixels_per_mm = min(max(pixels_per_mm, 2.0), 60.0)
        self.resetTransform()
        self.scale(pixels_per_mm, pixels_per_mm)
        self._zoom = pixels_per_mm
        self.zoom_changed.emit(pixels_per_mm)

    def fit(self) -> None:
        scene = self.scene()
        if scene is None or scene.sceneRect().isEmpty():
            return
        r = scene.sceneRect()
        vw, vh = max(self.viewport().width() - 20, 50), max(self.viewport().height() - 20, 50)
        self.set_zoom(min(vw / r.width(), vh / r.height()))
        self.centerOn(r.center())

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self._zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            step = 0.1
        elif mods & Qt.KeyboardModifier.ControlModifier:
            step = 1.0
        else:
            step = 0.5
        moves = {
            Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step),
        }
        if event.key() in moves:
            self.nudge.emit(*moves[event.key()])
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)
