"""Label Designer: clicking an element must not move or resize it (it used to jump to the grid / a guide)."""
import pytest

from qrlabel.domain.models import LabelElement, LabelTemplate


@pytest.fixture
def canvas():
    from PySide6.QtWidgets import QApplication

    from qrlabel.ui.designer.canvas import ElementItem, LabelScene, LabelView

    app = QApplication.instance() or QApplication([])
    t = LabelTemplate(id="t", name="t", width_mm=38.1, height_mm=38.1)
    el = LabelElement(kind="rect", x_mm=7.37, y_mm=5.13, w_mm=20.15, h_mm=10.05)  # off the 0.5 mm grid
    t.elements = [el]
    scene = LabelScene()
    scene.set_template(t)
    item = ElementItem(el, lambda: (t, {}, "", "M", 0.5))
    scene.addItem(item)
    view = LabelView(scene)
    view.resize(600, 600)
    view.set_zoom(12)
    view.show()
    app.processEvents()
    view._keep = scene  # keep the scene alive (Python owns it)
    return app, view, item, el


def _drag(app, view, item, from_mm, by_px):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    start = view.mapFromScene(item.mapToScene(*from_mm))
    vp = view.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for i in range(1, 6):  # several small moves, like a real hand
        QTest.mouseMove(vp, start + QPoint(round(by_px[0] * i / 5), round(by_px[1] * i / 5)))
        app.processEvents()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(*by_px))
    app.processEvents()


def test_click_with_small_wobble_does_not_move(canvas):
    app, view, item, el = canvas
    _drag(app, view, item, (5, 5), (1, 1))
    assert item.isSelected()
    assert (el.x_mm, el.y_mm, el.w_mm, el.h_mm) == (7.37, 5.13, 20.15, 10.05)


def test_click_on_resize_handle_does_not_resize(canvas):
    app, view, item, el = canvas
    item.setSelected(True)
    _drag(app, view, item, (el.w_mm, el.h_mm), (1, 0))
    assert (el.w_mm, el.h_mm) == (20.15, 10.05)


def test_real_drag_still_moves(canvas):
    app, view, item, el = canvas
    _drag(app, view, item, (5, 5), (60, 0))  # 5 mm at 12 px/mm
    assert el.x_mm != 7.37 and abs(el.x_mm - 12.37) < 1.0
    assert el.y_mm in (5.0, 5.13, 5.5)  # snapped or unchanged vertically, not far away
