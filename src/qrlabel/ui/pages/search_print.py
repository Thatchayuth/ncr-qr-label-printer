"""Search & Print: the operator's main workflow."""
from __future__ import annotations

from typing import Any

import time

from PySide6.QtCore import QDate, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...domain.models import DataProfile, LabelTemplate, PrintStatus, new_id
from ...rendering.raster import render_label_image
from ...services.formatting import build_label_values, format_value
from ...services.query_builder import apply_replace, has_criteria, parse_replace
from ..icons import icon, pixmap
from ..widgets import Banner, Card, chip, labeled, nice_calendar, page_header, pil_to_pixmap, sticker_pixmap
from ..workers import error_text, run_async

PREVIEW_W, PREVIEW_H = 360, 270



SEARCH_HINTS = {
    "contains": "contains…  ·  A..B  ·  A, B, C",
    "starts": "starts with…  ·  A..B  ·  A, B, C",
    "exact": "exact value  ·  A..B  ·  A, B, C",
}


# Examples shown before the first search (afterwards real values from the results are used).
FIELD_EXAMPLES: dict[str, tuple[str, str]] = {
    "ASSETID": ("FA-IT-5-26-0001", "FA-IT-5-26-0010"),
    "NAME": ("Computer Set", "Notebook"),
    "TECHINFO1": ("PU2024-001", "PU2024-010"),
    "PURCHID": ("PO24-00125", "PO24-00130"),
    "DIMENSION": ("FPRO_MOLD", "FPRO_MIX"),
    "JOURNALID": ("90959F_072", "90960F_072"),
    "VOUCHER": ("1901597_074", "1901600_074"),
    "ITEMID": ("MCAB-BA00", "MCAB-BA09"),
}


def field_examples(fd, values: list[str] | None = None) -> tuple[str, str]:
    """Two example values for a search field: from search results when known, else built-in or generic."""
    seen = sorted({str(v).strip() for v in (values or []) if str(v or "").strip()})
    if len(seen) >= 2:
        return seen[0], seen[-1]
    if len(seen) == 1:
        return seen[0], FIELD_EXAMPLES.get(fd.column.upper(), (seen[0], seen[0]))[1]
    return FIELD_EXAMPLES.get(fd.column.upper(), ("ABC-001", "ABC-010"))


def _part(text: str, mode: str) -> str:
    """Shortened example for 'starts with' / 'contains'."""
    keep = max(3, (len(text) * 2) // 3)
    if mode == "contains" and len(text) > 4:
        return text[1:keep]
    return text[:keep]


def search_tooltip(fd, values: list[str] | None = None) -> str:
    from html import escape

    a, b = field_examples(fd, values)
    lo, hi = sorted([a, b])
    mode = fd.search_mode
    one = {
        "contains": f"<code>{escape(_part(a, mode))}</code> &nbsp;contains this text",
        "starts": f"<code>{escape(_part(a, mode))}</code> &nbsp;starts with this text",
        "exact": f"<code>{escape(a)}</code> &nbsp;exactly this value",
    }.get(mode, "")
    lines = [f"<b>Search {escape(fd.label)}</b>"]
    if fd.barcode:
        rule = ", ".join(f"{escape(x)} becomes {escape(y)}" for x, y in parse_replace(fd.replace))
        lines.append("Scan the barcode: the search starts by itself." + (f" ({rule})" if rule else ""))
    lines += [
        one,
        f"<code>{escape(lo)}..{escape(hi)}</code> &nbsp;range (use full values)",
        f"<code>{escape(a)}, {escape(b)}</code> &nbsp;exactly these",
        "Separate values with comma, semicolon or new line (paste a column from Excel).",
    ]
    return "<br>".join(lines)


def _replace_live(edit: QLineEdit, text: str, rule: str) -> None:
    """Show the corrected value while typing/scanning, e.g. 90959F+072 -> 90959F_072."""
    fixed = apply_replace(text, rule)
    if fixed != text:
        pos = edit.cursorPosition() + len(fixed) - len(text)
        edit.setText(fixed)
        edit.setCursorPosition(max(0, pos))


class ScanWatcher(QObject):
    """Runs a search when a barcode scanner has finished typing into a box.

    Scanners type a character every few milliseconds; people need 100 ms or more. When at least
    MIN_CHARS characters arrived quickly and nothing follows for IDLE_MS, the scan is complete.
    Scanners that send Enter at the end search through returnPressed instead (only once).
    """

    MAX_GAP_MS = 50
    IDLE_MS = 150
    MIN_CHARS = 4

    def __init__(self, edit: QLineEdit, on_scan) -> None:
        super().__init__(edit)
        self.edit, self.on_scan = edit, on_scan
        self.fast = 0
        self.last = 0.0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._idle)
        edit.textEdited.connect(self._typed)
        edit.returnPressed.connect(self._enter)

    def _typed(self, _text: str) -> None:
        now = time.monotonic()
        self.fast = self.fast + 1 if (now - self.last) * 1000 <= self.MAX_GAP_MS else 1
        self.last = now
        self.timer.start(self.IDLE_MS)

    def _enter(self) -> None:
        self.timer.stop()
        self.fast = 0

    def _idle(self) -> None:
        scanned = self.fast >= self.MIN_CHARS and len(self.edit.text().strip()) >= self.MIN_CHARS
        self.fast = 0
        if scanned:
            self.on_scan()

class TickDelegate(QStyledItemDelegate):
    """Ticked rows get a light green background; column 0 shows the tick box.

    Ticks (labels to print) are separate from the highlighted row (label preview).
    """

    TINT = QColor("#ECFDF5")

    def __init__(self, view, is_ticked) -> None:
        super().__init__(view)
        self._is_ticked = is_ticked

    def paint(self, painter: QPainter, option, index) -> None:
        ticked = self._is_ticked(index.row())
        if ticked:
            painter.fillRect(option.rect, self.TINT)
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        r = option.rect
        box = QRectF(r.center().x() - 8, r.center().y() - 8, 16, 16)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if ticked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2563EB"))
            painter.drawRoundedRect(box, 4, 4)
            pen = QPen(QColor("#FFFFFF"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            tick = QPainterPath(QPointF(box.left() + 4, box.center().y()))
            tick.lineTo(box.left() + 7, box.bottom() - 4.5)
            tick.lineTo(box.right() - 3.5, box.top() + 4.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tick)
        else:
            painter.setPen(QPen(QColor("#94A3B8"), 1.4))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        painter.restore()


class SearchPrintPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.profiles: list[DataProfile] = []
        self.templates: list[LabelTemplate] = []
        self.records: list[dict[str, Any]] = []
        self.search_inputs: dict[str, QLineEdit] = {}
        self.range_inputs: dict[str, tuple[QCheckBox, QDateEdit, QDateEdit]] = {}
        self.scan_watchers: list[ScanWatcher] = []
        self.scan_edit: QLineEdit | None = None  # first barcode field of the profile
        self._printing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header("Search & Print", "Find records in AX, tick the rows, check the label preview and print."))

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(18)
        body.addLayout(left, 1)
        left.addWidget(self._build_search_card())
        left.addWidget(self._build_results_card(), 1)

        right_w = QWidget()
        right_w.setFixedWidth(420)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(18)
        right.addWidget(self._build_label_card())
        right.addWidget(self._build_print_card())
        right.addStretch(1)
        body.addWidget(right_w)

        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.template_combo.currentIndexChanged.connect(lambda _: self._update_preview())
        self.search_btn.clicked.connect(self._search)
        self.clear_btn.clicked.connect(self._clear_criteria)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        self.select_all_btn.clicked.connect(lambda: self._set_ticks(set(range(len(self.records)))))
        self.clear_sel_btn.clicked.connect(lambda: self._set_ticks(set()))
        tick_key = QShortcut(QKeySequence(Qt.Key.Key_Space), self.table)
        tick_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        tick_key.activated.connect(lambda: self._toggle_tick(self.table.currentIndex().row()))
        self.print_btn.clicked.connect(self._print)
        self.reload()

    # ------------------------------------------------------------- build UI

    def _build_search_card(self) -> Card:
        card = Card("Search")
        self.profile_combo = QComboBox()
        # the company (DATAAREAID) is chosen in the sidebar, not here
        card.body.addWidget(labeled("Data profile", self.profile_combo))

        self.criteria_grid = QGridLayout()
        self.criteria_grid.setHorizontalSpacing(14)
        self.criteria_grid.setVerticalSpacing(12)
        self.criteria_grid.setColumnStretch(0, 1)
        self.criteria_grid.setColumnStretch(1, 1)
        card.body.addLayout(self.criteria_grid)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.result_label = QLabel("")
        self.result_label.setObjectName("Muted")
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Ghost")
        self.search_btn = QPushButton("  Search")
        self.search_btn.setObjectName("Primary")
        self.search_btn.setIcon(icon("search", "#FFFFFF"))
        self.search_btn.setIconSize(QSize(16, 16))
        self.search_btn.setDefault(True)
        self.search_btn.setMinimumWidth(130)
        row.addWidget(self.result_label, 1)
        row.addWidget(self.clear_btn)
        row.addWidget(self.search_btn)
        card.body.addLayout(row)
        self.search_banner = Banner()
        card.body.addWidget(self.search_banner)
        return card

    def _build_results_card(self) -> Card:
        card = Card("Results")
        self.count_chip = chip("0")
        self.count_chip.hide()
        card.header.insertWidget(1, self.count_chip)
        self.select_all_btn = QPushButton("Tick all")
        self.select_all_btn.setObjectName("Ghost")
        self.clear_sel_btn = QPushButton("Untick all")
        self.clear_sel_btn.setObjectName("Ghost")
        card.header.addWidget(self.select_all_btn)
        card.header.addWidget(self.clear_sel_btn)

        self.model = QStandardItemModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Clicking a row only highlights it for the preview; only the tick box decides what is printed
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setItemDelegate(TickDelegate(self.table, lambda row: row in self.ticked))
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.clicked.connect(self._on_cell_clicked)
        self.ticked: set[int] = set()  # row numbers ticked for printing
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setMinimumHeight(260)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        ic = QLabel()
        ic.setPixmap(pixmap("inbox", "#94A3B8", 44, 1.5))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel("No results yet")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint = QLabel("Enter search criteria above and press Search.")
        self.empty_hint.setObjectName("Muted")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (ic, self.empty_title, self.empty_hint):
            el.addWidget(w)
        el.addStretch(1)

        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(empty)
        self.results_stack.addWidget(self.table)
        card.body.addWidget(self.results_stack, 1)

        self.selection_label = QLabel("No rows selected")
        self.selection_label.setObjectName("Muted")
        card.body.addWidget(self.selection_label)
        return card

    def _build_label_card(self) -> Card:
        card = Card("Label preview")
        self.size_chip = chip("", gray=True)
        card.header.addWidget(self.size_chip)
        self.template_combo = QComboBox()
        card.body.addWidget(labeled("Template", self.template_combo))

        stage = QFrame()
        stage.setObjectName("PreviewStage")
        stage.setFixedHeight(PREVIEW_H + 16)
        sl = QVBoxLayout(stage)
        sl.setContentsMargins(8, 8, 8, 8)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: transparent;")
        sl.addWidget(self.preview)
        card.body.addWidget(stage)

        self.payload_label = QLabel("QR: -")
        self.payload_label.setObjectName("Mono")
        self.payload_label.setWordWrap(True)
        card.body.addWidget(self.payload_label)
        self.preview_banner = Banner()
        card.body.addWidget(self.preview_banner)
        return card

    def _build_print_card(self) -> Card:
        card = Card("Print")
        steps = QHBoxLayout()
        steps.setSpacing(6)
        minus = QPushButton()
        minus.setObjectName("Stepper")
        minus.setIcon(icon("minus", "#334155"))
        plus = QPushButton()
        plus.setObjectName("Stepper")
        plus.setIcon(icon("plus", "#334155"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setObjectName("Copies")
        self.copies_spin.setRange(1, 999)
        self.copies_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copies_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.copies_spin.setFixedWidth(80)
        minus.clicked.connect(self.copies_spin.stepDown)
        plus.clicked.connect(self.copies_spin.stepUp)
        steps.addWidget(minus)
        steps.addWidget(self.copies_spin)
        steps.addWidget(plus)
        steps.addStretch(1)
        copies_w = QWidget()
        copies_w.setLayout(steps)
        steps.setContentsMargins(0, 0, 0, 0)
        card.body.addWidget(labeled("Copies per label", copies_w))

        box = QFrame()
        box.setObjectName("PrinterBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(10)
        pic = QLabel()
        pic.setPixmap(pixmap("printer", "#2563EB", 20))
        self.printer_label = QLabel("")
        self.printer_label.setWordWrap(True)
        bl.addWidget(pic)
        bl.addWidget(self.printer_label, 1)
        card.body.addWidget(labeled("Printer", box))

        self.print_btn = QPushButton("Print selected")
        self.print_btn.setObjectName("PrintButton")
        self.print_btn.setIcon(icon("printer", "#FFFFFF", size=20))
        self.print_btn.setIconSize(QSize(20, 20))
        self.print_btn.setEnabled(False)
        self.print_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body.addWidget(self.print_btn)
        self.print_banner = Banner()
        card.body.addWidget(self.print_banner)
        return card

    # ------------------------------------------------------------------ state

    def _offered_profiles(self) -> list[DataProfile]:
        """Profiles of the parts chosen at install (Application Settings); own profiles always."""
        from ...app.modules import hidden_profile_ids

        hidden = hidden_profile_ids(self.ctx)
        return [p for p in self.ctx.profiles.list_latest() if p.id not in hidden]

    def reload(self) -> None:
        """Re-read profiles/templates/settings (called when the page is shown)."""
        ui = self.ctx.config["ui"]
        self.profiles = self._offered_profiles()
        self.templates = self.ctx.templates.list_latest()

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(icon("table", "#64748B"), f"{p.name}  (v{p.version})", p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(ui.get("last_profile_id"))))
        self.profile_combo.blockSignals(False)

        self.copies_spin.setValue(int(ui.get("copies", 1)))
        self._refresh_printer_label()
        self._on_profile_changed()  # also fills the label list for the profile
        self._fill_templates(ui.get("last_template_id"))

    def _fill_templates(self, prefer: str | None = None) -> None:
        """Labels allowed for the current profile; keeps `prefer` if allowed, else the profile's default."""
        profile = self.current_profile()
        allowed = [t for t in self.templates if profile is None or profile.allows_template(t.id)]
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for t in allowed:
            star = "  ★ default" if profile and t.id == profile.template_id else ""
            self.template_combo.addItem(icon("qr", "#64748B"), f"{t.name}  (v{t.version}){star}", t.id)
        idx = self.template_combo.findData(prefer) if prefer else -1
        if idx < 0 and profile:
            idx = self.template_combo.findData(profile.template_id)
        self.template_combo.setCurrentIndex(max(0, idx))
        self.template_combo.setEnabled(bool(allowed))
        if not allowed:
            self.template_combo.addItem("No label assigned to this profile (Data Profiles)", "")
        self.template_combo.blockSignals(False)
        self._update_preview()

    def refresh_definitions(self) -> None:
        """Pick up newly saved profile/template versions without clearing the search or results."""
        pid, tid = self.profile_combo.currentData(), self.template_combo.currentData()
        old = self.current_profile()
        self.profiles = self._offered_profiles()
        self.templates = self.ctx.templates.list_latest()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:  # new profiles appear, renamed ones update
            self.profile_combo.addItem(icon("table", "#64748B"), f"{p.name}  (v{p.version})", p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(pid)))
        self.profile_combo.blockSignals(False)
        new = self.current_profile()
        if old is None or new is None or old.id != new.id or old.fields != new.fields:
            self._on_profile_changed()  # search boxes and columns changed: rebuild them
        if old is not None and new is not None and old.template_id != new.template_id:
            tid = new.template_id  # the admin chose a new default label
        self._fill_templates(tid)

    def _refresh_printer_label(self) -> None:
        try:
            self.printer_label.setText(self.ctx.printer_adapter().target)
        except Exception as e:
            self.printer_label.setText(f"Not configured - {error_text(e)}")

    def current_profile(self) -> DataProfile | None:
        pid = self.profile_combo.currentData()
        return next((p for p in self.profiles if p.id == pid), None)

    def current_template(self) -> LabelTemplate | None:
        tid = self.template_combo.currentData()
        return next((t for t in self.templates if t.id == tid), None)

    def on_company_changed(self, cid: str, name: str = "") -> None:
        """Results belong to the previous company: clear them."""
        had_results = bool(self.records)
        self._set_records([], searched=False)
        label = cid.upper() + (f" ({name})" if name else "")
        msg = f"Company changed to {label}." + (" Press Search to load its assets." if had_results else "")
        self.search_banner.show_message(msg, "info")

    def _on_header_clicked(self, section: int) -> None:
        if section != 0 or not self.records:
            return
        everything = set(range(len(self.records)))
        self._set_ticks(set() if self.ticked == everything else everything)

    def _on_cell_clicked(self, index) -> None:
        if index.column() == 0:  # only the tick box column ticks
            self._toggle_tick(index.row())

    def _toggle_tick(self, row: int) -> None:
        if 0 <= row < len(self.records):
            self._set_ticks(self.ticked ^ {row})

    def _set_ticks(self, rows: set[int]) -> None:
        self.ticked = {r for r in rows if 0 <= r < len(self.records)}
        self.table.viewport().update()  # TickDelegate repaints boxes and row tint
        self._on_selection()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        QTimer.singleShot(0, self._ready_for_scan)  # open the page and scan straight away

    def selected_records(self) -> list[dict[str, Any]]:
        """Rows ticked for printing (in table order)."""
        return [self.records[r] for r in sorted(self.ticked) if r < len(self.records)]

    # ----------------------------------------------------------------- search

    def _clear_grid(self) -> None:
        while self.criteria_grid.count():
            item = self.criteria_grid.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _on_profile_changed(self, *_: Any) -> None:
        self._clear_grid()
        self.search_inputs.clear()
        self.range_inputs.clear()
        self.scan_watchers = []
        self.scan_edit = None
        profile = self.current_profile()
        if not profile:
            return
        i = 0
        for fd in profile.searchable_fields:
            edit = QLineEdit()
            edit.setMaxLength(5000)
            edit.setPlaceholderText(SEARCH_HINTS.get(fd.search_mode, SEARCH_HINTS["contains"]))
            edit.setToolTip(search_tooltip(fd))
            edit.setClearButtonEnabled(True)
            if fd.replace:
                edit.textEdited.connect(lambda text, e=edit, rule=fd.replace: _replace_live(e, text, rule))
            if fd.barcode:
                edit.setPlaceholderText("scan barcode or type…")
                self.scan_watchers.append(ScanWatcher(edit, self._search))
                if self.scan_edit is None:
                    self.scan_edit = edit
            edit.returnPressed.connect(self._search)
            self.criteria_grid.addWidget(labeled(fd.label + ("  (scan)" if fd.barcode else ""), edit), i // 2, i % 2)
            self.search_inputs[fd.column] = edit
            i += 1
        row = (i + 1) // 2
        for fd in profile.range_fields:
            self.criteria_grid.addWidget(labeled(fd.label, self._date_range_row(fd.column)), row, 0, 1, 2)
            row += 1
        self._fill_templates(profile.template_id)
        self._set_records([], searched=False)
        self._ready_for_scan()

    def _update_tooltips(self, rows: list[dict[str, Any]]) -> None:
        """Use values from the results as examples in each box's tooltip."""
        profile = self.current_profile()
        if not profile or not rows:
            return
        for fd in profile.searchable_fields:
            edit = self.search_inputs.get(fd.column)
            if edit is not None:
                values = [r.get(fd.column.upper()) for r in rows[:200]]
                edit.setToolTip(search_tooltip(fd, [v for v in values if isinstance(v, str)]))

    def _ready_for_scan(self) -> None:
        """Barcode field focused with its text selected, so the next scan replaces it."""
        if self.scan_edit is not None and self.isVisible():
            self.scan_edit.setFocus()
            self.scan_edit.selectAll()

    def _date_range_row(self, column: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        use = QCheckBox("Filter from")
        today = QDate.currentDate()
        start, end = QDateEdit(QDate(today.year(), today.month(), 1)), QDateEdit(today)
        for d in (start, end):
            nice_calendar(d)
            d.setDisplayFormat("dd/MM/yyyy")
            d.setEnabled(False)
            d.setMinimumWidth(140)
        use.toggled.connect(start.setEnabled)
        use.toggled.connect(end.setEnabled)
        to = QLabel("to")
        to.setObjectName("Muted")
        row.addWidget(use)
        row.addWidget(start)
        row.addWidget(to)
        row.addWidget(end)
        row.addStretch(1)
        self.range_inputs[column] = (use, start, end)
        return w

    def _ranges(self) -> dict:
        return {
            col: (start.date().toPython(), end.date().toPython())
            for col, (use, start, end) in self.range_inputs.items()
            if use.isChecked()
        }

    def _clear_criteria(self) -> None:
        for e in self.search_inputs.values():
            e.clear()
        for use, _, _ in self.range_inputs.values():
            use.setChecked(False)
        self.search_banner.clear_message()

    def _search(self) -> None:
        profile = self.current_profile()
        if not profile or not self.search_btn.isEnabled():
            return
        criteria = {col: e.text() for col, e in self.search_inputs.items()}
        ranges = self._ranges()
        if profile.require_criteria and not has_criteria(criteria, ranges):
            self.search_banner.show_message("Enter at least one search value. This table is too large to list everything.", "warning")
            next(iter(self.search_inputs.values()), self).setFocus()
            return
        company = self.ctx.company
        self.search_btn.setEnabled(False)
        self.search_btn.setText("  Searching...")
        self.search_banner.clear_message()
        run_async(lambda: self.ctx.data_source().search(profile, criteria, company, ranges), self._on_results, self._on_search_error)

    def _search_done(self) -> None:
        self.search_btn.setEnabled(True)
        self.search_btn.setText("  Search")

    def _on_results(self, rows: list[dict[str, Any]]) -> None:
        self._search_done()
        self._set_records(rows, searched=True)
        self._update_tooltips(rows)
        self._ready_for_scan()
        profile = self.current_profile()
        if profile and rows and len(rows) >= profile.row_limit:
            self.search_banner.show_message(f"Showing the first {len(rows)} rows. Narrow the search to see others.", "warning")

    def _on_search_error(self, e: Exception) -> None:
        self._search_done()
        self.search_banner.show_message(error_text(e), "error")

    def _set_records(self, rows: list[dict[str, Any]], searched: bool) -> None:
        self.records = rows
        self.ticked = set()  # a new search starts with nothing ticked
        profile = self.current_profile()
        self.model.clear()
        if profile:
            fields = profile.display_fields
            self.model.setHorizontalHeaderLabels(["✓"] + [f.label for f in fields])
            self.model.setHeaderData(0, Qt.Orientation.Horizontal, "Tick all / untick all", Qt.ItemDataRole.ToolTipRole)
            for rec in rows:
                tick = QStandardItem("")  # drawn by TickDelegate from the row's selection state
                items = [tick]
                for f in fields:
                    text = format_value(rec.get(f.column.upper()), f)
                    item = QStandardItem(" ".join(text.split()))  # multi-line AX text on one row
                    item.setToolTip(text)
                    items.append(item)
                self.model.appendRow(items)
            header = self.table.horizontalHeader()
            header.setStretchLastSection(True)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(0, 40)
            for col, f in enumerate(fields, start=1):
                if f.column.upper() == "NAME":  # long text: fixed width the user can drag; full text in tooltip
                    header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
                    self.table.setColumnWidth(col, 260)
                else:
                    header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
                if f.data_type in ("decimal", "int"):
                    for row in range(self.model.rowCount()):
                        self.model.item(row, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.results_stack.setCurrentIndex(1 if rows else 0)
        if searched and not rows:
            self.empty_title.setText("No matching assets")
            self.empty_hint.setText(f"Check the search text and date range. Company: {self.ctx.company.upper() or '-'} (change it in the sidebar).")
        elif not searched:
            self.empty_title.setText("No results yet")
            self.empty_hint.setText("Enter search criteria above and press Search.")
        self.count_chip.setText(f"{len(rows)} found")
        self.count_chip.setVisible(searched)
        self.result_label.setText("")
        self._on_selection()

    # ---------------------------------------------------------------- preview

    def _on_selection(self) -> None:
        n = len(self.selected_records())
        self.selection_label.setText(
            f"{n} of {len(self.records)} ticked for printing  ·  click a row to preview it" if n
            else "Tick the boxes ☐ of the labels to print (Space ticks the highlighted row) · click a row to preview it"
        )
        self.print_btn.setEnabled(n > 0 and not self._printing)
        if not self._printing:
            self.print_btn.setText(f"  Print {n} label(s)" if n else "  Print selected")
        self.select_all_btn.setEnabled(bool(self.records))
        self.clear_sel_btn.setEnabled(n > 0)
        self._update_preview()

    def _update_preview(self) -> None:
        profile, template = self.current_profile(), self.current_template()
        if not template:
            self.preview.setText("No template")
            return
        self.size_chip.setText(f"{template.width_mm:g} × {template.height_mm:g} mm")
        self.size_chip.setToolTip(f"Gap {template.gap_mm:g} mm, {template.dpi} dpi")
        selected = self.selected_records()
        current = self.table.currentIndex().row()
        if 0 <= current < len(self.records):
            record = self.records[current]  # the highlighted row (clicked last)
        else:
            record = selected[0] if selected else None
        self.preview_banner.clear_message()
        values: dict[str, str] = {}
        qr_text = None
        if profile and record:
            values = build_label_values(profile, record)
            try:
                payload = self.ctx.payloads.build(record, profile)
                qr_text = payload.text
                self.payload_label.setText(f"QR · {payload.byte_length} bytes · {payload.text}")
            except Exception as e:
                self.payload_label.setText("QR: -")
                self.preview_banner.show_message(error_text(e), "error")
        else:
            self.payload_label.setText("Select a row to preview its label")
        img, warnings = render_label_image(template, values, qr_text, profile.qr.error_correction if profile else "M")
        if warnings and record:
            self.preview_banner.show_message("\n".join(warnings), "warning")
        self.preview.setPixmap(sticker_pixmap(pil_to_pixmap(img), PREVIEW_W, PREVIEW_H))

    # ------------------------------------------------------------------ print

    def _print(self) -> None:
        if self._printing:
            return
        records = self.selected_records()
        profile, template = self.current_profile(), self.current_template()
        if not records or not profile or not template:
            return
        try:
            adapter = self.ctx.printer_adapter()
        except Exception as e:
            self.print_banner.show_message(error_text(e), "error")
            return
        copies = self.copies_spin.value()
        total = len(records) * copies
        if total > 1:
            answer = QMessageBox.question(
                self, "Confirm print",
                f"Print {len(records)} label(s) × {copies} copies = {total} sticker(s)\nto {adapter.target}?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        ui = self.ctx.config["ui"]
        ui.update(last_profile_id=profile.id, last_template_id=template.id, copies=copies)
        try:
            self.ctx.save_config()
        except Exception:
            pass  # remembering UI choices must never block printing

        self._printing = True
        self.print_btn.setEnabled(False)
        self.print_btn.setText("  Sending...")
        self.print_banner.show_message("Sending to printer...", "info")
        run_async(
            lambda: self.ctx.print_service.print_records(
                records=records, profile=profile, template=template, adapter=adapter,
                copies=copies, correlation_id=new_id(),
            ),
            self._on_printed, self._on_print_error,
        )

    def _finish_print(self) -> None:
        self._printing = False
        self._on_selection()

    def _on_printed(self, jobs) -> None:
        self._finish_print()
        counts: dict[PrintStatus, int] = {}
        for j in jobs:
            counts[j.status] = counts.get(j.status, 0) + 1
        ok = counts.get(PrintStatus.SPOOLER_ACCEPTED, 0) + counts.get(PrintStatus.SUBMITTED_TO_DEVICE, 0)
        if ok == len(jobs):
            if jobs[0].adapter == "mock":
                self.print_banner.show_message(
                    f"{ok} label job(s) saved as .prn files by the sample printer. Nothing was printed.", "success")
                return
            where = "accepted by the Windows print queue" if jobs[0].status == PrintStatus.SPOOLER_ACCEPTED else "sent to the print server"
            self.print_banner.show_message(f"{ok} label job(s) {where}. Check the printed stickers.", "success")
            return
        failed = next((j for j in jobs if j.status in (PrintStatus.FAILED, PrintStatus.UNKNOWN_DELIVERY)), None)
        parts = [f"{n} {s.value}" for s, n in counts.items()]
        msg = "Printing stopped: " + ", ".join(parts) + "."
        if failed:
            msg += f"\n{failed.document_ref}: {failed.error_message}"
            if failed.status == PrintStatus.UNKNOWN_DELIVERY:
                msg += "\nIt is unknown whether this label printed. Check the printer before printing again."
        self.print_banner.show_message(msg, "error")

    def _on_print_error(self, e: Exception) -> None:
        self._finish_print()
        self.print_banner.show_message(error_text(e), "error")
