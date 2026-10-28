"""Label Designer page."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...app.defaults import default_asset_template
from ...domain.layout import TE200_MAX_PRINT_WIDTH_MM, validate_template
from ...domain.models import DataProfile, LabelElement, LabelTemplate, new_id
from ...services.formatting import build_label_values
from ...domain.layout import mm_to_dots
from ...rendering.images import SUPPORTED as SUPPORTED_IMAGES
from ...rendering.raster import qr_byte_capacity, qr_matrix
from ...rendering.images import load_image_file
from ...services.profile_rules import template_issues
from ...services.template_io import duplicate_template, export_template, import_template
from ..designer.canvas import ElementItem, LabelScene, LabelView, footprint
from ..icons import icon
from ..widgets import Banner, Card, chip, page_header
from ..workers import error_text

STATIC_TEXT = "__static__"


def _mm_spin(lo: float = 0.0, hi: float = 300.0, step: float = 0.5, decimals: int = 1, suffix: str = " mm") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def _tool_button(text: str, icon_name: str, tip: str) -> QPushButton:
    b = QPushButton(text)
    b.setIcon(icon(icon_name, "#334155", size=16))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tip)
    b.setStyleSheet("QPushButton { padding: 6px 9px; }")
    return b


class DesignerPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.template: LabelTemplate | None = None  # working copy being edited
        self.saved_version = 0
        self.dirty = False
        self.items: list[ElementItem] = []
        self.profile: DataProfile | None = None
        self.values: dict[str, str] = {}
        self.qr_text: str | None = None
        self.ecc = "M"
        self.snap_step = 0.5
        self._loading = False
        self._syncing = False  # True while canvas and layer list selection are being matched
        self._clipboard: list[LabelElement] = []
        self._saved_snapshot: LabelTemplate | None = None
        self.undo_stack: list[LabelTemplate] = []
        self.redo_stack: list[LabelTemplate] = []
        self._snapshot: LabelTemplate | None = None
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(350)
        self._commit_timer.timeout.connect(self._commit_snapshot)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header(
            "Label Designer",
            "Design the sticker in millimetres. The canvas uses the same renderer as the printer.",
        ))
        root.addWidget(self._build_template_bar())

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)
        body.addWidget(self._build_canvas_card(), 1)

        side = QWidget()
        side.setFixedWidth(340)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(18)
        sl.addWidget(self._build_layers_card())
        sl.addWidget(self._build_element_card())
        sl.addWidget(self._build_label_card())
        sl.addStretch(1)
        body.addWidget(side)

        self._install_shortcuts()
        self.reload()

    # ================================================================ build UI

    def _build_template_bar(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel("Template")
        lbl.setObjectName("FieldLabel")
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(280)
        self.state_chip = chip("", gray=True)
        row.addWidget(lbl)
        row.addWidget(self.template_combo)
        row.addWidget(self.state_chip)
        self.used_by = QPushButton("")
        self.used_by.setObjectName("Ghost")
        self.used_by.setToolTip("Data profiles that may use this label. Click to change.")
        self.used_by.clicked.connect(self._edit_profiles)
        row.addWidget(self.used_by)
        row.addStretch(1)
        self.new_btn = QPushButton("New")
        self.dup_btn = QPushButton("Duplicate")
        self.import_btn = QPushButton("Import...")
        self.export_btn = QPushButton("Export...")
        self.revert_btn = QPushButton("Revert")
        self.save_btn = QPushButton("  Save")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setIcon(icon("check", "#FFFFFF", size=16))
        for b in (self.new_btn, self.dup_btn, self.import_btn, self.export_btn, self.revert_btn, self.save_btn):
            row.addWidget(b)
        self.new_btn.setToolTip("New template (Ctrl+N)")
        self.dup_btn.setToolTip("Copy this whole template")
        self.save_btn.setToolTip("Save as a new version (Ctrl+S)")
        card.body.addLayout(row)
        self.banner = Banner()
        card.body.addWidget(self.banner)

        self.template_combo.activated.connect(self._on_template_chosen)
        self.new_btn.clicked.connect(self._new)
        self.dup_btn.clicked.connect(self._duplicate)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.revert_btn.clicked.connect(self._revert)
        self.save_btn.clicked.connect(self._save)
        return card

    def _build_canvas_card(self) -> Card:
        card = Card()
        tools = QHBoxLayout()
        tools.setSpacing(6)
        add_lbl = QLabel("Add")
        add_lbl.setObjectName("FieldLabel")
        tools.addWidget(add_lbl)
        for text, ic, tip, kind in [
            ("Field", "table", "Text from a data field, e.g. Asset ID (Alt+1)", "field"),
            ("Text", "layout", "Fixed text (Alt+2)", "text"),
            ("QR", "qr", "QR code - content from QR Configuration (Alt+3)", "qr"),
            ("Box", "layout", "Rectangle (Alt+4)", "rect"),
            ("Line", "minus", "Horizontal line (Alt+5)", "line"),
            ("Image", "image", "Picture or logo from a file (Alt+6)", "image"),
        ]:
            b = _tool_button(text, ic, tip)
            b.clicked.connect(lambda _=False, k=kind: self._add_element(k))
            tools.addWidget(b)
        self.delete_btn = _tool_button("", "x", "Delete selected element (Del)")
        tools.addWidget(self.delete_btn)
        tools.addStretch(1)
        self.align_combo = QComboBox()
        self.align_combo.addItems(["Align...", "Center horizontally", "Center vertically", "Left margin", "Right margin", "Top margin", "Bottom margin"])
        self.align_combo.setToolTip("Align the selected element on the label")
        tools.addWidget(self.align_combo)
        card.body.addLayout(tools)

        self.scene = LabelScene()
        self.view = LabelView(self.scene)
        self.view.setMinimumHeight(420)
        card.body.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        sample_lbl = QLabel("Sample data")
        sample_lbl.setObjectName("FieldLabel")
        self.sample_edit = QLineEdit("FA-IT-5-26-0001")
        self.sample_edit.setMaximumWidth(200)
        self.sample_edit.setToolTip("Value used for the first profile field (e.g. Asset ID) on the canvas")
        self.grid_check = QCheckBox("Grid")
        self.grid_check.setChecked(True)
        self.snap_combo = QComboBox()
        for label, step in [("Snap 0.5 mm", 0.5), ("Snap 1 mm", 1.0), ("Snap 0.1 mm", 0.1), ("No snap", 0.0)]:
            self.snap_combo.addItem(label, step)
        zoom_out = QPushButton()
        zoom_out.setObjectName("Stepper")
        zoom_out.setIcon(icon("minus"))
        zoom_in = QPushButton()
        zoom_in.setObjectName("Stepper")
        zoom_in.setIcon(icon("plus"))
        fit = QPushButton("Fit")
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("Muted")
        self.zoom_label.setMinimumWidth(48)
        for w in (sample_lbl, self.sample_edit):
            bottom.addWidget(w)
        bottom.addStretch(1)
        for w in (self.grid_check, self.snap_combo, zoom_out, self.zoom_label, zoom_in, fit):
            bottom.addWidget(w)
        card.body.addLayout(bottom)
        hint_row = QHBoxLayout()
        hint = QLabel("Drag to move · corner square resizes · arrows nudge · Ctrl+Z undo · Ctrl+D duplicate · Ctrl+S save")
        hint.setObjectName("Muted")
        keys_btn = QPushButton("Shortcuts (F1)")
        keys_btn.setObjectName("Ghost")
        keys_btn.clicked.connect(lambda: self._show_shortcuts())
        hint_row.addWidget(hint, 1)
        hint_row.addWidget(keys_btn)
        card.body.addLayout(hint_row)

        self.delete_btn.clicked.connect(self._delete_selected)
        self.align_combo.activated.connect(self._align)
        self.scene.selectionChanged.connect(self._on_selection)
        self.view.nudge.connect(self._nudge)
        self.view.delete_pressed.connect(self._delete_selected)
        self.view.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{z / 4:.0%}"))
        zoom_in.clicked.connect(lambda: self.view.set_zoom(self.view.zoom * 1.25))
        zoom_out.clicked.connect(lambda: self.view.set_zoom(self.view.zoom / 1.25))
        fit.clicked.connect(self.view.fit)
        self.grid_check.toggled.connect(self._on_grid)
        self.snap_combo.currentIndexChanged.connect(self._on_snap)
        self.sample_edit.editingFinished.connect(self._refresh_sample)
        return card

    def _build_layers_card(self) -> Card:
        card = Card("Layers")
        self.layer_count = chip("", gray=True)
        card.header.addWidget(self.layer_count)
        self.layers = QListWidget()
        self.layers.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layers.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.layers.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.layers.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.layers.setIconSize(QSize(16, 16))
        self.layers.setMinimumHeight(130)
        self.layers.setMaximumHeight(210)
        self.layers.setStyleSheet(
            "QListWidget { border: 1px solid #E2E8F0; border-radius: 8px; padding: 4px; background: #FFFFFF; outline: 0; }"
            "QListWidget::item { padding: 5px 6px; border-radius: 6px; }"
            "QListWidget::item:selected { background: #DBEAFE; color: #0F172A; }"
            "QListWidget::item:hover:!selected { background: #F1F5F9; }"
        )
        card.body.addWidget(self.layers)

        row = QHBoxLayout()
        row.setSpacing(2)
        self.layer_btns = {}
        for key, text, tip in [
            ("front", "Front", "Bring to front (Ctrl+Shift+])"),
            ("up", "Up", "Bring forward one layer (Ctrl+])"),
            ("down", "Down", "Send backward one layer (Ctrl+[)"),
            ("back", "Back", "Send to back (Ctrl+Shift+[)"),
            ("lock", "Lock", "Lock / unlock: locked layers cannot be moved or resized (Ctrl+L)"),
        ]:
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setToolTip(tip)
            row.addWidget(b)
            self.layer_btns[key] = b
        card.body.addLayout(row)
        hint = QLabel("Top of the list is in front. Drag to reorder, double-click to rename.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        for key in ("front", "up", "down", "back"):
            self.layer_btns[key].clicked.connect(lambda _=False, k=key: self._move_layers(k))
        self.layer_btns["lock"].clicked.connect(self._toggle_lock)
        self.layers.itemSelectionChanged.connect(self._on_layer_selection)
        self.layers.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._on_layers_dragged))
        self.layers.itemChanged.connect(self._on_layer_renamed)
        return card

    def _build_element_card(self) -> Card:
        card = Card("Selected element")
        self.el_kind_chip = chip("", gray=True)
        card.header.addWidget(self.el_kind_chip)
        keep = self.el_kind_chip.sizePolicy()
        keep.setRetainSizeWhenHidden(True)  # the header keeps its height when the chip hides
        self.el_kind_chip.setSizePolicy(keep)
        # One area for the empty message and the form, as tall as the tallest form (text element), so
        # the panels below do not jump up and down when another kind of element is clicked.
        self.el_area = QWidget()
        area = QVBoxLayout(self.el_area)
        area.setContentsMargins(0, 0, 0, 0)
        area.setSpacing(0)
        card.body.addWidget(self.el_area)
        self._el_height_reserved = False
        self.el_empty = QLabel("Click an element on the canvas to edit it.")
        self.el_empty.setObjectName("Muted")
        self.el_empty.setWordWrap(True)
        area.addWidget(self.el_empty)

        self.el_form_w = QWidget()
        f = QFormLayout(self.el_form_w)
        f.setContentsMargins(0, 0, 0, 0)
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(8)
        # 2 decimals like the stored positions: 1 decimal rounded 37.15 to 37.2 and made items jump
        # no " mm" in pairs of boxes: the label says (mm), so "16.50" is not cut off in the narrow panel
        self.e_x, self.e_y = _mm_spin(decimals=2, suffix=""), _mm_spin(decimals=2, suffix="")
        self.e_w, self.e_h = _mm_spin(0, 300, decimals=2, suffix=""), _mm_spin(0, 300, decimals=2, suffix="")
        pos = QHBoxLayout()
        pos.addWidget(self.e_x)
        pos.addWidget(self.e_y)
        size = QHBoxLayout()
        size.addWidget(self.e_w)
        size.addWidget(self.e_h)
        self.e_rot = QComboBox()
        for r in (0, 90, 180, 270):
            self.e_rot.addItem(f"{r}°", r)
        self.e_source = QComboBox()
        self.e_text = QLineEdit()
        self.e_text.setPlaceholderText("Text, or {COLUMN} placeholders")
        self.e_font = _mm_spin(0.8, 30, 0.1, 1)
        self.e_bold = QCheckBox("Bold")
        self.e_fit = QCheckBox("Shrink to fit")
        self.e_wrap = QCheckBox("Wrap to next line")
        self.e_wrap.setToolTip("Long text continues on the next line inside the box.\nMake the box tall enough for the lines you need.")
        font_row = QHBoxLayout()
        font_row.addWidget(self.e_font)
        font_row.addWidget(self.e_bold)
        self.e_align = QComboBox()
        for label, key in (("Left", "left"), ("Center", "center"), ("Right", "right")):
            self.e_align.addItem(label, key)
        self.e_thick = _mm_spin(0.1, 5, 0.1, 2)
        self.e_name = QLineEdit()

        f.addRow("X / Y (mm)", pos)
        f.addRow("W / H (mm)", size)
        f.addRow("Rotation", self.e_rot)
        f.addRow("Content", self.e_source)
        f.addRow("Text", self.e_text)
        self.FONT_ROW = f.rowCount()
        f.addRow("Font size", font_row)
        f.addRow("", self.e_fit)
        f.addRow("", self.e_wrap)
        f.addRow("Align", self.e_align)
        f.addRow("Line thickness", self.e_thick)
        self.e_image_btn = QPushButton("Replace image...")
        self.e_dither = QCheckBox("Dither grey tones (photos)")
        self.e_dither.setToolTip("On: grey tones become dot patterns (photos).\nOff: sharp black/white (logos, line art).")
        self.e_qr_size = QComboBox()
        self.e_qr_size.setToolTip(
            "Auto: the QR grows with the amount of data, so labels can differ in size.\n"
            "Fixed: every label gets the same QR size (only data that does not fit makes it bigger)."
        )
        self.QR_SIZE_ROW = f.rowCount()
        f.addRow("QR size", self.e_qr_size)
        self.e_qr_size.currentIndexChanged.connect(self._on_element_edit)
        self.IMAGE_ROW = f.rowCount()
        f.addRow("Image", self.e_image_btn)
        self.DITHER_ROW = f.rowCount()
        f.addRow("", self.e_dither)
        self.e_image_btn.clicked.connect(self._replace_image)
        self.e_dither.toggled.connect(self._on_element_edit)
        f.addRow("Name", self.e_name)
        self.e_lock = QCheckBox("Locked")
        self.e_lock.setToolTip("Locked layers cannot be moved or resized on the canvas (Ctrl+L)")
        f.addRow("", self.e_lock)
        self.e_lock.toggled.connect(self._on_element_edit)
        self.el_form = f
        area.addWidget(self.el_form_w)
        area.addStretch(1)
        self.el_form_w.hide()

        for s in (self.e_x, self.e_y, self.e_w, self.e_h, self.e_font, self.e_thick):
            s.valueChanged.connect(self._on_element_edit)
        for c in (self.e_rot, self.e_source, self.e_align):
            c.currentIndexChanged.connect(self._on_element_edit)
        for c in (self.e_bold, self.e_fit, self.e_wrap):
            c.toggled.connect(self._on_element_edit)
        self.e_text.editingFinished.connect(self._on_element_edit)
        self.e_name.editingFinished.connect(self._on_element_edit)
        return card

    def _build_label_card(self) -> Card:
        card = Card("Label settings")
        f = QFormLayout()
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(8)
        self.l_name = QLineEdit()
        self.l_w = _mm_spin(5, TE200_MAX_PRINT_WIDTH_MM, suffix="")
        self.l_h = _mm_spin(5, 300, suffix="")
        size = QHBoxLayout()
        size.addWidget(self.l_w)
        size.addWidget(self.l_h)
        self.l_gap = _mm_spin(0, 20)
        self.l_media = QComboBox()
        for label, key in (("Gap (die-cut stickers)", "gap"), ("Black mark", "bline"), ("Continuous", "continuous")):
            self.l_media.addItem(label, key)
        self.l_margin = _mm_spin(0, 10)
        self.l_density = QSpinBox()
        self.l_density.setRange(0, 15)
        self.l_speed = QSpinBox()
        self.l_speed.setRange(2, 6)
        self.l_speed.setSuffix(" ips")
        ds = QHBoxLayout()
        ds.addWidget(self.l_density)
        ds.addWidget(self.l_speed)
        self.l_direction = QComboBox()
        self.l_direction.addItem("Normal (1)", 1)
        self.l_direction.addItem("Reversed (0)", 0)
        self.l_qr_mode = QComboBox()
        self.l_qr_mode.addItem("Bitmap (exact preview)", "bitmap")
        self.l_qr_mode.addItem("Printer QR command", "native")
        self.l_text_mode = QComboBox()
        self.l_text_mode.addItem("Bitmap (Thai OK)", "bitmap")
        self.l_text_mode.addItem("Auto", "auto")
        self.l_text_mode.addItem("Printer fonts (ASCII)", "native")
        f.addRow("Name", self.l_name)
        f.addRow("W / H (mm)", size)
        f.addRow("Gap", self.l_gap)
        f.addRow("Media", self.l_media)
        f.addRow("Safe margin", self.l_margin)
        f.addRow("Density / Speed", ds)
        f.addRow("Direction", self.l_direction)
        f.addRow("QR output", self.l_qr_mode)
        f.addRow("Text output", self.l_text_mode)
        card.body.addLayout(f)
        self.issues = QLabel("")
        self.issues.setWordWrap(True)
        card.body.addWidget(self.issues)

        for s in (self.l_w, self.l_h, self.l_gap, self.l_margin):
            s.valueChanged.connect(self._on_label_edit)
        for s in (self.l_density, self.l_speed):
            s.valueChanged.connect(self._on_label_edit)
        for c in (self.l_media, self.l_direction, self.l_qr_mode, self.l_text_mode):
            c.currentIndexChanged.connect(self._on_label_edit)
        self.l_name.editingFinished.connect(self._on_label_edit)
        return card

    # ============================================================ templates

    def reload(self) -> None:
        """Refresh the template list. Keeps unsaved work on screen."""
        current = self.template.id if self.template else None
        self._fill_combo(select=current)
        if self.template is None:
            self._open(self.template_combo.currentData())

    def _fill_combo(self, select: str | None) -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for t in self.ctx.templates.list_latest():
            self.template_combo.addItem(icon("qr", "#64748B"), f"{t.name}  (v{t.version})", t.id)
        if self.template and self.template_combo.findData(self.template.id) < 0:
            self.template_combo.addItem(f"{self.template.name}  (new, not saved)", self.template.id)
        idx = self.template_combo.findData(select) if select else 0
        self.template_combo.setCurrentIndex(max(0, idx))
        self.template_combo.blockSignals(False)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Discard the unsaved changes to this template?")
        return answer == QMessageBox.StandardButton.Yes

    def _on_template_chosen(self, _index: int) -> None:
        tid = self.template_combo.currentData()
        if self.template and tid == self.template.id:
            return
        if not self._confirm_discard():
            self._fill_combo(select=self.template.id if self.template else None)
            return
        self._open(tid)

    def _open(self, template_id: str | None) -> None:
        t = self.ctx.templates.get(template_id) if template_id else None
        if t is None:
            return
        self._load(t, saved_version=t.version)

    def _load(self, t: LabelTemplate, saved_version: int) -> None:
        self.template = copy.deepcopy(t)
        self.saved_version = saved_version
        self._saved_snapshot = copy.deepcopy(t) if saved_version else None
        self._reset_history()
        self._pick_profile()
        self._build_values()
        self._fill_label_form(t)
        self._rebuild_scene()
        self._set_dirty(False)
        QTimer.singleShot(0, self.view.fit)

    def _fill_label_form(self, t: LabelTemplate) -> None:
        self._loading = True
        self.l_name.setText(t.name)
        self.l_w.setValue(t.width_mm)
        self.l_h.setValue(t.height_mm)
        self.l_gap.setValue(t.gap_mm)
        self.l_media.setCurrentIndex(max(0, self.l_media.findData(t.media)))
        self.l_margin.setValue(t.margin_mm)
        self.l_density.setValue(t.density)
        self.l_speed.setValue(t.speed)
        self.l_direction.setCurrentIndex(max(0, self.l_direction.findData(t.direction)))
        self.l_qr_mode.setCurrentIndex(max(0, self.l_qr_mode.findData(t.qr_mode)))
        self.l_text_mode.setCurrentIndex(max(0, self.l_text_mode.findData(t.text_mode)))
        self._loading = False

    # ========================================================= undo / redo

    def _reset_history(self) -> None:
        self._commit_timer.stop()
        self.undo_stack: list[LabelTemplate] = []
        self.redo_stack: list[LabelTemplate] = []
        self._snapshot = copy.deepcopy(self.template)

    def _commit_snapshot(self) -> None:
        """Record one undo step once a burst of edits (e.g. a drag) has settled."""
        self._commit_timer.stop()
        if self.template is None or self.template == self._snapshot:
            return
        self.undo_stack.append(self._snapshot)
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self._snapshot = copy.deepcopy(self.template)

    def _undo(self) -> None:
        self._commit_snapshot()
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.template))
        self._restore(self.undo_stack.pop())

    def _redo(self) -> None:
        self._commit_snapshot()
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.template))
        self._restore(self.redo_stack.pop())

    def _restore(self, t: LabelTemplate) -> None:
        self.template = copy.deepcopy(t)
        self._snapshot = copy.deepcopy(t)
        self._fill_label_form(t)
        self._rebuild_scene()
        self._set_dirty(self._saved_snapshot is None or self.template != self._saved_snapshot)

    # ===================================================== clipboard / select

    def _copy(self) -> None:
        sel = [i.el for i in self.items if i.isSelected()]
        if sel:
            self._clipboard = copy.deepcopy(sel)

    def _paste(self) -> None:
        if not self._clipboard or not self.template:
            return
        self.scene.clearSelection()
        t = self.template
        for src in self._clipboard:
            el = copy.deepcopy(src)
            fw, fh = footprint(el)
            el.x_mm = round(min(el.x_mm + 1.0, max(0.0, t.width_mm - fw)), 2)
            el.y_mm = round(min(el.y_mm + 1.0, max(0.0, t.height_mm - fh)), 2)
            t.elements.append(el)
            self._add_item(el).setSelected(True)
        self._clipboard = [copy.deepcopy(i.el) for i in self.items if i.isSelected()]  # next paste steps again
        self._refresh_layers()
        self._changed()

    def _duplicate_element(self) -> None:
        self._copy()
        self._paste()

    def _select_all(self) -> None:
        for item in self.items:
            item.setSelected(True)

    def _toggle_grid(self) -> None:
        self.grid_check.setChecked(not self.grid_check.isChecked())

    def _align_to(self, index: int) -> None:
        self.align_combo.setCurrentIndex(index)
        self._align()

    def _install_shortcuts(self) -> None:
        page_keys = [
            ("Ctrl+S", "Save template", self._save),
            ("Ctrl+N", "New template", self._new),
            ("Ctrl+Z", "Undo", self._undo),
            ("Ctrl+Y", "Redo", self._redo),
            ("Ctrl+Shift+Z", "Redo", self._redo),
            ("Ctrl+C", "Copy selected element(s)", self._copy),
            ("Ctrl+V", "Paste element(s)", self._paste),
            ("Ctrl+D", "Duplicate selected element(s)", self._duplicate_element),
            ("Ctrl+A", "Select all elements", self._select_all),
            ("Esc", "Clear selection", self.scene.clearSelection),
            ("Alt+1", "Add Field", lambda: self._add_element("field")),
            ("Alt+2", "Add Text", lambda: self._add_element("text")),
            ("Alt+3", "Add QR", lambda: self._add_element("qr")),
            ("Alt+4", "Add Box", lambda: self._add_element("rect")),
            ("Alt+5", "Add Line", lambda: self._add_element("line")),
            ("Alt+6", "Add Image", lambda: self._add_element("image")),
            ("Alt+H", "Center horizontally", lambda: self._align_to(1)),
            ("Alt+V", "Center vertically", lambda: self._align_to(2)),
            ("Ctrl+0", "Fit label to window", self.view.fit),
            ("Ctrl+=", "Zoom in", lambda: self.view.set_zoom(self.view.zoom * 1.25)),
            ("Ctrl++", "Zoom in", lambda: self.view.set_zoom(self.view.zoom * 1.25)),
            ("Ctrl+-", "Zoom out", lambda: self.view.set_zoom(self.view.zoom / 1.25)),
            ("Ctrl+G", "Show / hide grid", self._toggle_grid),
            ("Ctrl+]", "Bring layer forward", lambda: self._move_layers("up")),
            ("Ctrl+[", "Send layer backward", lambda: self._move_layers("down")),
            ("Ctrl+Shift+]", "Bring layer to front", lambda: self._move_layers("front")),
            ("Ctrl+}", "Bring layer to front", lambda: self._move_layers("front")),
            ("Ctrl+Shift+[", "Send layer to back", lambda: self._move_layers("back")),
            ("Ctrl+{", "Send layer to back", lambda: self._move_layers("back")),
            ("Ctrl+L", "Lock / unlock layer", self._toggle_lock),
            ("F1", "Show keyboard shortcuts", self._show_shortcuts),
        ]
        self._shortcuts = []
        for keys, _, fn in page_keys:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)
        hidden = ("Ctrl+Shift+Z", "Ctrl++", "Ctrl+}", "Ctrl+{")
        self.shortcut_help = [(k, d) for k, d, _ in page_keys if k not in hidden] + [
            ("Delete", "Delete selected element(s)"),
            ("Arrow keys", "Move 0.5 mm  (Shift = 0.1 mm, Ctrl = 1 mm)"),
            ("Ctrl + mouse wheel", "Zoom"),
        ]

    def _show_shortcuts(self) -> None:
        rows = "".join(
            f"<tr><td style='padding:3px 14px 3px 0'><b>{k}</b></td><td>{d}</td></tr>" for k, d in self.shortcut_help
        )
        box = QMessageBox(self)
        box.setWindowTitle("Label Designer shortcuts")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<table>{rows}</table>")
        box.exec()

    def _pick_profile(self) -> None:
        profiles = self.ctx.profiles.list_latest()
        t = self.template
        self.profile = next((p for p in profiles if t and p.template_id == t.id), profiles[0] if profiles else None)
        self.e_source.blockSignals(True)
        self.e_source.clear()
        self.e_source.addItem("Fixed text", STATIC_TEXT)
        for fd in self.profile.fields if self.profile else []:
            self.e_source.addItem(f"Field: {fd.label}", fd.column)
        self.e_source.blockSignals(False)

    def _build_values(self) -> None:
        self.values, self.qr_text = {}, None
        if not self.profile:
            return
        record = {}
        for i, fd in enumerate(self.profile.fields):
            record[fd.column.upper()] = self.sample_edit.text() if i == 0 else f"<{fd.label}>"
        self.values = build_label_values(self.profile, record)
        self.ecc = self.profile.qr.error_correction
        try:
            self.qr_text = self.ctx.payloads.build(record, self.profile).text
        except Exception:
            self.qr_text = self.sample_edit.text() or "SAMPLE"

    def _render_ctx(self):
        return self.template, self.values, self.qr_text, self.ecc, self.snap_step

    def _rebuild_scene(self) -> None:
        self.items = []  # forget old items before clear() fires selectionChanged
        self.scene.blockSignals(True)
        self.scene.clear()
        self.scene.blockSignals(False)
        self.scene.set_template(self.template)
        for el in self.template.elements:
            self._add_item(el)
        self._refresh_layers()
        self._on_selection()
        self._validate()

    def _add_item(self, el: LabelElement) -> ElementItem:
        item = ElementItem(el, self._render_ctx)
        item.changed.connect(self._on_item_changed)
        item.setZValue(len(self.items))
        self.scene.addItem(item)
        self.items.append(item)
        return item

    # ================================================================ layers

    @staticmethod
    def _layer_label(el: LabelElement, profile: DataProfile | None) -> str:
        if el.name:
            return el.name
        if el.kind == "text" and el.field:
            fd = profile.get_field(el.field) if profile else None
            return f"Field · {fd.label if fd else el.field}"
        if el.kind == "text":
            text = " ".join(el.text.split())
            return f"Text · {text[:24]}" if text else "Text"
        return {"qr": "QR code", "rect": "Box", "line": "Line", "image": "Image"}.get(el.kind, el.kind)

    def _refresh_layers(self) -> None:
        if not self.template:
            return
        self._syncing = True
        icons = {"qr": "qr", "rect": "layout", "line": "minus", "image": "image"}
        self.layers.clear()
        selected = {id(i.el) for i in self.items if i.isSelected()}
        for el in reversed(self.template.elements):  # top of the list = in front
            text = self._layer_label(el, self.profile) + ("   🔒" if el.locked else "")
            ic = icons.get(el.kind, "table" if el.field else "layout")
            it = QListWidgetItem(icon(ic, "#94A3B8" if el.locked else "#334155", size=16), text)
            it.setData(Qt.ItemDataRole.UserRole, id(el))
            it.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled
            )
            if el.locked:
                it.setForeground(QColor("#64748B"))
            self.layers.addItem(it)
            it.setSelected(id(el) in selected)
        self.layer_count.setText(str(len(self.template.elements)))
        self._syncing = False
        self._update_layer_buttons()

    def _update_layer_buttons(self) -> None:
        sel = [i for i in self.items if i.isSelected()]
        for key in ("front", "up", "down", "back", "lock"):
            self.layer_btns[key].setEnabled(bool(sel))
        self.layer_btns["lock"].setText("Unlock" if sel and all(i.el.locked for i in sel) else "Lock")

    def _sync_layers_from_canvas(self) -> None:
        self._syncing = True
        selected = {id(i.el) for i in self.items if i.isSelected()}
        for row in range(self.layers.count()):
            it = self.layers.item(row)
            it.setSelected(it.data(Qt.ItemDataRole.UserRole) in selected)
        self._syncing = False
        self._update_layer_buttons()

    def _on_layer_selection(self) -> None:
        if self._syncing:
            return
        ids = {it.data(Qt.ItemDataRole.UserRole) for it in self.layers.selectedItems()}
        self._syncing = True
        for item in self.items:
            item.setSelected(id(item.el) in ids)
        self._syncing = False
        self._on_selection()

    def _apply_z(self) -> None:
        order = {id(e): i for i, e in enumerate(self.template.elements)}
        self.items.sort(key=lambda it: order[id(it.el)])
        for item in self.items:
            item.setZValue(order[id(item.el)])

    def _on_layers_dragged(self) -> None:
        """The list was reordered by drag and drop: apply the new order to the template."""
        if self._syncing or not self.template:
            return
        by_id = {id(e): e for e in self.template.elements}
        top_to_bottom = [by_id[self.layers.item(r).data(Qt.ItemDataRole.UserRole)] for r in range(self.layers.count())]
        new = list(reversed(top_to_bottom))
        if [id(e) for e in new] == [id(e) for e in self.template.elements]:
            return
        self.template.elements[:] = new
        self._apply_z()
        self._changed()

    def _move_layers(self, mode: str) -> None:
        els = self.template.elements if self.template else []
        sel = {id(i.el) for i in self.items if i.isSelected()}
        if not sel:
            return
        new = list(els)
        if mode == "front":
            new = [e for e in els if id(e) not in sel] + [e for e in els if id(e) in sel]
        elif mode == "back":
            new = [e for e in els if id(e) in sel] + [e for e in els if id(e) not in sel]
        elif mode == "up":
            for i in range(len(new) - 2, -1, -1):
                if id(new[i]) in sel and id(new[i + 1]) not in sel:
                    new[i], new[i + 1] = new[i + 1], new[i]
        elif mode == "down":
            for i in range(1, len(new)):
                if id(new[i]) in sel and id(new[i - 1]) not in sel:
                    new[i], new[i - 1] = new[i - 1], new[i]
        if [id(e) for e in new] == [id(e) for e in els]:
            return
        els[:] = new
        self._apply_z()
        self._refresh_layers()
        self._changed()

    def _toggle_lock(self) -> None:
        sel = [i for i in self.items if i.isSelected()]
        if not sel:
            return
        lock = not all(i.el.locked for i in sel)
        for i in sel:
            i.el.locked = lock
            i.apply_lock()
        self._refresh_layers()
        if self.selected_item():
            self._fill_element_form(self.selected_item().el)
        self._changed()

    def _on_layer_renamed(self, it: QListWidgetItem) -> None:
        if self._syncing:
            return
        el = next((e for e in self.template.elements if id(e) == it.data(Qt.ItemDataRole.UserRole)), None)
        if el is None:
            return
        new = it.text().replace("🔒", "").strip()
        auto = self._layer_label(LabelElement(**{**el.__dict__, "name": ""}), self.profile)
        el.name = "" if new in ("", auto) else new[:60]
        QTimer.singleShot(0, self._refresh_layers)
        if self.selected_item() and self.selected_item().el is el:
            self._fill_element_form(el)
        self._changed()

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        t = self.template
        if not t:
            return
        if dirty:
            self.state_chip.setObjectName("Chip")
            self.state_chip.setText("● Unsaved changes")
        else:
            self.state_chip.setObjectName("ChipGray")
            self.state_chip.setText(f"Saved · v{self.saved_version}" if self.saved_version else "New")
        self.state_chip.style().unpolish(self.state_chip)
        self.state_chip.style().polish(self.state_chip)
        self.revert_btn.setEnabled(dirty and self.saved_version > 0)
        self._update_used_by()

    def _new(self) -> None:
        if not self._confirm_discard():
            return
        t = default_asset_template()
        t.id, t.name = new_id(), "New label"
        if self.template:
            t.width_mm, t.height_mm, t.gap_mm = self.template.width_mm, self.template.height_mm, self.template.gap_mm
            t.elements = []
        self._load(t, saved_version=0)
        self._fill_combo(select=t.id)
        self._set_dirty(True)

    def _duplicate(self) -> None:
        if not self.template:
            return
        t = duplicate_template(self.template)
        self._load(t, saved_version=0)
        self._fill_combo(select=t.id)
        self._set_dirty(True)
        self.banner.show_message("Copy created. Press Save to keep it.", "info")

    def _import(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import label template", "", "Label template (*.json)")
        if not path:
            return
        try:
            t = import_template(Path(path))
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self._load(t, saved_version=0)
        self._fill_combo(select=t.id)
        self._set_dirty(True)
        self.banner.show_message(f"Imported '{t.name}'. Press Save to keep it.", "info")

    def _export(self) -> None:
        if not self.template:
            return
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in self.template.name).strip() or "label"
        path, _ = QFileDialog.getSaveFileName(self, "Export label template", f"{safe}.json", "Label template (*.json)")
        if not path:
            return
        try:
            export_template(self.template, Path(path))
            self.banner.show_message(f"Exported to {path}", "success")
        except Exception as e:
            self.banner.show_message(error_text(e), "error")

    def _revert(self) -> None:
        if self.template and self.saved_version:
            self._open(self.template.id)
            self.banner.clear_message()

    # ======================================================= profile binding

    def _profiles_using(self) -> list[DataProfile]:
        if not self.template:
            return []
        return [p for p in self.ctx.profiles.list_latest() if p.allows_template(self.template.id)]

    def _update_used_by(self) -> None:
        if not self.template:
            return
        if not self.saved_version:
            self.used_by.setText("Save first, then choose profiles")
            self.used_by.setEnabled(False)
            return
        names = [p.name for p in self._profiles_using()]
        self.used_by.setEnabled(True)
        self.used_by.setText(
            ("Used by: " + ", ".join(names) if names else "Not used by any profile") + "   ·   Use with profiles..."
        )
        warnings = [i for p in self._profiles_using() for i in template_issues(self.template, p)]
        self.used_by.setStyleSheet("QPushButton { color: #B45309; }" if warnings else "")
        self.used_by.setToolTip("\n".join(warnings) or "Data profiles that may use this label. Click to change.")

    def _edit_profiles(self) -> None:
        """Tick the data profiles that may use this label (saves a new version of each changed profile)."""
        t = self.template
        if not t or not self.saved_version:
            return
        profiles = self.ctx.profiles.list_latest()
        dlg = QDialog(self)
        dlg.setWindowTitle("Use this label with...")
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)
        info = QLabel(f"Data profiles that may print <b>{t.name}</b>:")
        info.setWordWrap(True)
        lay.addWidget(info)
        lst = QListWidget()
        for p in profiles:
            it = QListWidgetItem(icon("table", "#64748B"), f"{p.name}  (v{p.version})")
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if p.allows_template(t.id) else Qt.CheckState.Unchecked)
            issues = template_issues(t, p)
            if issues:
                it.setToolTip("\n".join(issues))
                it.setForeground(QColor("#B45309"))
            lst.addItem(it)
        lay.addWidget(lst)
        note = QLabel("Orange = this label prints fields the profile does not have (hover for details).")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        all_ids = [x.id for x in self.ctx.templates.list_latest()]
        changed = []
        for i, p in enumerate(profiles):
            want = lst.item(i).checkState() == Qt.CheckState.Checked
            if want == p.allows_template(t.id):
                continue
            p2 = copy.deepcopy(p)
            ids = list(p2.template_ids) or list(all_ids)  # older profile = all labels: make the list explicit
            if want and t.id not in ids:
                ids.append(t.id)
            if not want:
                ids = [x for x in ids if x != t.id]
                if p2.template_id == t.id:
                    p2.template_id = ids[0] if ids else ""
            if want and not p2.template_id:
                p2.template_id = t.id
            p2.template_ids = ids
            self.ctx.profiles.save(p2)
            changed.append(p2.name)
        self._update_used_by()
        if changed:
            self.banner.show_message(f"Updated profile(s): {', '.join(changed)} (saved as new versions).", "success")

    def _save(self) -> None:
        if not self.template:
            return
        if not self.dirty:
            self.banner.show_message("No changes to save.", "info")
            return
        problems = validate_template(self.template)
        if problems:
            self.banner.show_message("Fix these before saving:\n• " + "\n• ".join(problems), "error")
            return
        try:
            saved = self.ctx.templates.save(copy.deepcopy(self.template))
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self.template.version = saved.version
        self.saved_version = saved.version
        self._saved_snapshot = copy.deepcopy(self.template)
        self._commit_snapshot()
        self._fill_combo(select=saved.id)
        self._set_dirty(False)
        self.banner.show_message(f"Saved '{saved.name}' as version {saved.version}. New prints use this version.", "success")

    # ============================================================= elements

    def selected_item(self) -> ElementItem | None:
        sel = [i for i in self.items if i.isSelected()]
        return sel[0] if len(sel) == 1 else None

    def _fill_qr_sizes(self, el: LabelElement) -> None:
        """Options for a fixed QR size, with the printed size for this box and how much data fits."""
        dpi = self.template.dpi if self.template else 203
        box = min(mm_to_dots(el.w_mm, dpi), mm_to_dots(el.h_mm, dpi))
        current = self.qr_text and len(qr_matrix(self.qr_text, self.ecc))
        self.e_qr_size.blockSignals(True)
        self.e_qr_size.clear()
        self.e_qr_size.addItem("Auto - grows with the data", 0)
        for v in range(1, 41):
            modules = 17 + 4 * v
            cell = box // modules
            if cell < 1:
                break
            size_mm = modules * cell * 25.4 / dpi
            note = "  (small dots)" if cell < 3 else ""
            self.e_qr_size.addItem(
                f"Fixed v{v} · {size_mm:.1f} mm · up to {qr_byte_capacity(v, self.ecc)} bytes{note}", v)
        self.e_qr_size.setCurrentIndex(max(0, self.e_qr_size.findData(el.qr_version)))
        self.e_qr_size.blockSignals(False)
        if current:
            self.e_qr_size.setToolTip(
                f"The sample data needs version {(current - 17) // 4}. "
                "Choose a fixed version that fits your longest data so every label looks the same."
            )

    def _pick_image(self) -> tuple[str, int, int] | None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture or logo", "", f"Images ({SUPPORTED_IMAGES})")
        if not path:
            return None
        try:
            return load_image_file(Path(path))
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return None

    def _replace_image(self) -> None:
        item = self.selected_item()
        if not item or item.el.kind != "image":
            return
        picked = self._pick_image()
        if not picked:
            return
        item.el.image_data = picked[0]
        item.refresh()
        self._changed()

    def _add_element(self, kind: str) -> None:
        t = self.template
        if not t:
            return
        m = t.margin_mm
        inner_w = max(1.0, t.width_mm - 2 * m)
        if kind == "field":
            col = self.profile.fields[0].column if self.profile and self.profile.fields else ""
            el = LabelElement(kind="text", field=col, x_mm=m, y_mm=m, w_mm=inner_w, h_mm=5, font_mm=3, bold=True, align="center")
        elif kind == "text":
            el = LabelElement(kind="text", text="Text", x_mm=m, y_mm=m, w_mm=min(20.0, inner_w), h_mm=5, font_mm=3)
        elif kind == "qr":
            s = min(15.0, inner_w, t.height_mm - 2 * m)
            el = LabelElement(kind="qr", x_mm=m, y_mm=m, w_mm=s, h_mm=s)
        elif kind == "rect":
            el = LabelElement(kind="rect", x_mm=m, y_mm=m, w_mm=inner_w, h_mm=max(1.0, t.height_mm - 2 * m), thickness_mm=0.3)
        elif kind == "image":
            picked = self._pick_image()
            if not picked:
                return
            data, pw, ph = picked
            inner_h = max(1.0, t.height_mm - 2 * m)
            w = min(12.0, inner_w)
            h = min(inner_h, w * ph / pw)
            w = round(h * pw / ph, 1)  # keep the picture's shape
            el = LabelElement(kind="image", x_mm=m, y_mm=m, w_mm=w, h_mm=round(h, 1), image_data=data)
        else:
            el = LabelElement(kind="line", x_mm=m, y_mm=t.height_mm / 2, w_mm=inner_w, h_mm=0, thickness_mm=0.3)
        t.elements.append(el)
        item = self._add_item(el)
        self.scene.clearSelection()
        item.setSelected(True)
        self._refresh_layers()
        self._changed()

    def _delete_selected(self) -> None:
        doomed = [i for i in self.items if i.isSelected()]
        if not doomed:
            return
        ids = {id(i.el) for i in doomed}
        self.template.elements[:] = [e for e in self.template.elements if id(e) not in ids]  # by identity
        for item in doomed:
            self.items.remove(item)
            self.scene.removeItem(item)
        self._refresh_layers()
        self._on_selection()
        self._changed()

    def _nudge(self, dx: float, dy: float) -> None:
        for item in [i for i in self.items if i.isSelected() and not i.el.locked]:
            item.move_exact(item.pos().x() + dx, item.pos().y() + dy)

    def _align(self, *_) -> None:
        choice = self.align_combo.currentIndex()
        self.align_combo.setCurrentIndex(0)
        if choice == 0:
            return
        item = self.selected_item()
        t = self.template
        if not item or not t:
            self.banner.show_message("Select one element to align.", "info")
            return
        if item.el.locked:
            self.banner.show_message("This layer is locked. Unlock it first (Ctrl+L).", "info")
            return
        fw, fh = footprint(item.el)
        x, y = item.pos().x(), item.pos().y()
        if choice == 1:
            x = (t.width_mm - fw) / 2
        elif choice == 2:
            y = (t.height_mm - fh) / 2
        elif choice == 3:
            x = t.margin_mm
        elif choice == 4:
            x = t.width_mm - t.margin_mm - fw
        elif choice == 5:
            y = t.margin_mm
        else:
            y = t.height_mm - t.margin_mm - fh
        item.move_exact(round(x, 2), round(y, 2))

    def _on_item_changed(self, item: ElementItem) -> None:
        if item is self.selected_item():
            self._fill_element_form(item.el)
        self._changed()

    def _on_selection(self) -> None:
        if not self._syncing:
            self._sync_layers_from_canvas()
        item = self.selected_item()
        self.el_form_w.setVisible(item is not None)
        self.el_empty.setVisible(item is None)
        self.delete_btn.setEnabled(any(i.isSelected() for i in self.items))
        if item is None:
            n = sum(i.isSelected() for i in self.items)
            self.el_empty.setText(f"{n} elements selected." if n > 1 else "Click an element on the canvas to edit it.")
            self.el_kind_chip.setText("")
            self.el_kind_chip.hide()
            return
        self._fill_element_form(item.el)

    def _fill_element_form(self, el: LabelElement) -> None:
        self._loading = True
        kinds = {"text": "Field" if el.field else "Text", "qr": "QR code", "rect": "Box", "line": "Line", "image": "Image"}
        self.el_kind_chip.setText(kinds.get(el.kind, el.kind))
        self.el_kind_chip.show()
        self.e_x.setValue(el.x_mm)
        self.e_y.setValue(el.y_mm)
        self.e_w.setValue(el.w_mm)
        self.e_h.setValue(el.h_mm)
        self.e_rot.setCurrentIndex(max(0, self.e_rot.findData(el.rotation)))
        self.e_source.setCurrentIndex(max(0, self.e_source.findData(el.field or STATIC_TEXT)))
        self.e_text.setText(el.text)
        self.e_font.setValue(el.font_mm)
        self.e_bold.setChecked(el.bold)
        self.e_fit.setChecked(el.auto_fit)
        self.e_wrap.setChecked(el.wrap)
        self.e_align.setCurrentIndex(max(0, self.e_align.findData(el.align)))
        self.e_thick.setValue(el.thickness_mm)
        self.e_name.setText(el.name)
        self.e_lock.setChecked(el.locked)
        self.e_dither.setChecked(el.dither)
        if el.kind == "qr":
            self._fill_qr_sizes(el)
        self._show_rows_for(el)
        self._loading = False

    def _show_rows_for(self, el: LabelElement) -> None:
        self.el_form.setRowVisible(self.QR_SIZE_ROW, el.kind == "qr")
        is_text, is_shape = el.kind == "text", el.kind in ("rect", "line")
        self.el_form.setRowVisible(self.IMAGE_ROW, el.kind == "image")
        self.el_form.setRowVisible(self.DITHER_ROW, el.kind == "image")
        self.el_form.setRowVisible(self.e_source, is_text)
        self.el_form.setRowVisible(self.e_text, is_text and not el.field)
        self.el_form.setRowVisible(self.FONT_ROW, is_text)
        self.el_form.setRowVisible(self.e_fit, is_text)
        self.el_form.setRowVisible(self.e_wrap, is_text)
        self.el_form.setRowVisible(self.e_align, is_text)
        self.el_form.setRowVisible(self.e_thick, is_shape)

    def _reserve_element_height(self) -> None:
        """Measure the form for every kind of element once and keep the tallest height."""
        if self._el_height_reserved:
            return
        tallest = 0
        for kind in ("text", "qr", "image", "rect", "line"):
            self._show_rows_for(LabelElement(kind=kind, x_mm=0, y_mm=0, w_mm=1, h_mm=1))
            self.el_form.activate()
            tallest = max(tallest, self.el_form.sizeHint().height())
        item = self.selected_item()
        if item is not None:
            self._show_rows_for(item.el)
        if tallest > 0:
            self.el_area.setMinimumHeight(tallest)
            self._el_height_reserved = True

    def _on_element_edit(self, *_):
        if self._loading or not self.isVisible():
            return
        item = self.selected_item()
        if not item:
            return
        el = item.el

        def changed(spin, current: float) -> bool:  # only what the user changed; never re-round the rest
            return abs(spin.value() - round(current, spin.decimals())) > 1e-9

        if changed(self.e_w, el.w_mm):
            el.w_mm = self.e_w.value()
        if changed(self.e_h, el.h_mm):
            el.h_mm = self.e_h.value()
        el.rotation = self.e_rot.currentData()
        src = self.e_source.currentData()
        el.field = "" if src in (None, STATIC_TEXT) else src
        el.text = self.e_text.text()
        el.font_mm = self.e_font.value()
        el.bold = self.e_bold.isChecked()
        el.auto_fit = self.e_fit.isChecked()
        el.wrap = self.e_wrap.isChecked()
        el.align = self.e_align.currentData()
        el.thickness_mm = self.e_thick.value()
        el.dither = self.e_dither.isChecked()
        if el.kind == "qr" and self.e_qr_size.currentData() is not None:
            el.qr_version = int(self.e_qr_size.currentData())
        renamed =el.name != self.e_name.text().strip() or el.locked != self.e_lock.isChecked()
        el.name = self.e_name.text().strip()
        el.locked = self.e_lock.isChecked()
        item.apply_lock()
        item.refresh()
        if changed(self.e_x, item.pos().x()) or changed(self.e_y, item.pos().y()):
            item.move_exact(self.e_x.value(), self.e_y.value())
        self._fill_element_form(el)
        if renamed or el.kind == "text":
            self._refresh_layers()
        self._changed()

    # ================================================================ label

    def _on_label_edit(self, *_):
        if self._loading or not self.template or not self.isVisible():
            return  # also ignores editingFinished fired while the window closes
        try:
            self._apply_label_form()
        except RuntimeError:  # widgets already destroyed during shutdown
            return

    def _apply_label_form(self) -> None:
        t = self.template
        t.name = self.l_name.text().strip() or t.name
        t.width_mm, t.height_mm = self.l_w.value(), self.l_h.value()
        t.gap_mm, t.margin_mm = self.l_gap.value(), self.l_margin.value()
        t.media = self.l_media.currentData()
        t.density, t.speed = self.l_density.value(), self.l_speed.value()
        t.direction = self.l_direction.currentData()
        t.qr_mode, t.text_mode = self.l_qr_mode.currentData(), self.l_text_mode.currentData()
        self.scene.set_template(t)
        for item in self.items:
            item.refresh()
        self._changed()

    def _on_grid(self, on: bool) -> None:
        self.scene.show_grid = on
        self.scene.update()

    def _on_snap(self, *_):
        self.snap_step = self.snap_combo.currentData()
        self.scene.grid_step = self.snap_step if self.snap_step >= 0.5 else 1.0
        self.scene.update()

    def _refresh_sample(self) -> None:
        self._build_values()
        for item in self.items:
            item.refresh()
        self._validate()

    def _changed(self) -> None:
        self._set_dirty(True)
        self._validate()
        self._commit_timer.start()

    def _validate(self) -> None:
        if not self.template:
            return
        problems = validate_template(self.template)
        warnings = [w for item in self.items for w in item.warnings]
        if not problems and not warnings:
            self.issues.setStyleSheet("color: #047857;")
            self.issues.setText("✓ Layout OK")
            return
        lines = [f"✕ {p}" for p in problems] + [f"⚠ {w}" for w in warnings]
        self.issues.setStyleSheet("color: #B91C1C;" if problems else "color: #B45309;")
        self.issues.setText("\n".join(lines))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.view.fit)
        QTimer.singleShot(0, self._reserve_element_height)
