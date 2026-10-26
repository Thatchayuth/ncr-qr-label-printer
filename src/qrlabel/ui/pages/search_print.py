"""Search & Print: the operator's main workflow."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
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
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...domain.models import DataProfile, LabelTemplate, PrintStatus, new_id
from ...infrastructure.ax.mock_source import MOCK_COMPANY
from ...rendering.raster import render_label_image
from ...services.formatting import build_label_values, format_value
from ..icons import icon, pixmap
from ..widgets import Banner, Card, chip, labeled, page_header, pil_to_pixmap, sticker_pixmap
from ..workers import error_text, run_async

PREVIEW_W, PREVIEW_H = 360, 270


class SearchPrintPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.profiles: list[DataProfile] = []
        self.templates: list[LabelTemplate] = []
        self.records: list[dict[str, Any]] = []
        self.search_inputs: dict[str, QLineEdit] = {}
        self.range_inputs: dict[str, tuple[QCheckBox, QDateEdit, QDateEdit]] = {}
        self._printing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header("Search & Print", "Find assets in AX, select rows, check the label preview and print."))

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
        self.select_all_btn.clicked.connect(self.table.selectAll)
        self.clear_sel_btn.clicked.connect(self.table.clearSelection)
        self.print_btn.clicked.connect(self._print)
        self.reload()

    # ------------------------------------------------------------- build UI

    def _build_search_card(self) -> Card:
        card = Card("Search")
        self.profile_combo = QComboBox()
        self.company_edit = QLineEdit()
        self.company_edit.setMaxLength(8)
        self.company_edit.setPlaceholderText("e.g. db1")
        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.setVerticalSpacing(12)
        top.addWidget(labeled("Data profile", self.profile_combo), 0, 0)
        top.addWidget(labeled("Company (DATAAREAID)", self.company_edit), 0, 1)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        card.body.addLayout(top)

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
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.setObjectName("Ghost")
        self.clear_sel_btn = QPushButton("Clear selection")
        self.clear_sel_btn.setObjectName("Ghost")
        card.header.addWidget(self.select_all_btn)
        card.header.addWidget(self.clear_sel_btn)

        self.model = QStandardItemModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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

    def reload(self) -> None:
        """Re-read profiles/templates/settings (called when the page is shown)."""
        ui = self.ctx.config["ui"]
        self.profiles = self.ctx.profiles.list_latest()
        self.templates = self.ctx.templates.list_latest()

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(icon("table", "#64748B"), f"{p.name}  (v{p.version})", p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(ui.get("last_profile_id"))))
        self.profile_combo.blockSignals(False)

        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for t in self.templates:
            self.template_combo.addItem(icon("qr", "#64748B"), f"{t.name}  (v{t.version})", t.id)
        self.template_combo.blockSignals(False)

        company = self.ctx.config["database"].get("company", "")
        if self.ctx.using_mock_data and not company:
            company = MOCK_COMPANY
        if not self.company_edit.text():
            self.company_edit.setText(company)
        self.copies_spin.setValue(int(ui.get("copies", 1)))
        self._refresh_printer_label()
        self._on_profile_changed()
        last_t = self.template_combo.findData(ui.get("last_template_id"))
        if last_t >= 0:
            self.template_combo.setCurrentIndex(last_t)

    def refresh_definitions(self) -> None:
        """Pick up newly saved profile/template versions without clearing the search or results."""
        pid, tid = self.profile_combo.currentData(), self.template_combo.currentData()
        self.profiles = self.ctx.profiles.list_latest()
        self.templates = self.ctx.templates.list_latest()
        self.profile_combo.blockSignals(True)
        for i in range(self.profile_combo.count()):
            p = next((x for x in self.profiles if x.id == self.profile_combo.itemData(i)), None)
            if p:
                self.profile_combo.setItemText(i, f"{p.name}  (v{p.version})")
        self.profile_combo.blockSignals(False)
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for t in self.templates:
            self.template_combo.addItem(icon("qr", "#64748B"), f"{t.name}  (v{t.version})", t.id)
        self.template_combo.setCurrentIndex(max(0, self.template_combo.findData(tid)))
        self.template_combo.blockSignals(False)
        if self.profile_combo.findData(pid) >= 0:
            self._update_preview()

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

    def selected_records(self) -> list[dict[str, Any]]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.records[r] for r in rows if r < len(self.records)]

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
        profile = self.current_profile()
        if not profile:
            return
        i = 0
        for fd in profile.searchable_fields:
            edit = QLineEdit()
            edit.setMaxLength(100)
            edit.setPlaceholderText("contains...")
            edit.setClearButtonEnabled(True)
            edit.returnPressed.connect(self._search)
            self.criteria_grid.addWidget(labeled(fd.label, edit), i // 2, i % 2)
            self.search_inputs[fd.column] = edit
            i += 1
        row = (i + 1) // 2
        for fd in profile.range_fields:
            self.criteria_grid.addWidget(labeled(fd.label, self._date_range_row(fd.column)), row, 0, 1, 2)
            row += 1
        self.company_edit.setEnabled(bool(profile.dataarea_column))
        tidx = self.template_combo.findData(profile.template_id)
        if tidx >= 0:
            self.template_combo.setCurrentIndex(tidx)
        self._set_records([], searched=False)

    def _date_range_row(self, column: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        use = QCheckBox("Filter from")
        today = QDate.currentDate()
        start, end = QDateEdit(QDate(today.year(), today.month(), 1)), QDateEdit(today)
        for d in (start, end):
            d.setCalendarPopup(True)
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
        company = self.company_edit.text()
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
        profile = self.current_profile()
        if profile and rows and len(rows) >= profile.row_limit:
            self.search_banner.show_message(f"Showing the first {len(rows)} rows. Narrow the search to see others.", "warning")

    def _on_search_error(self, e: Exception) -> None:
        self._search_done()
        self.search_banner.show_message(error_text(e), "error")

    def _set_records(self, rows: list[dict[str, Any]], searched: bool) -> None:
        self.records = rows
        profile = self.current_profile()
        self.model.clear()
        if profile:
            fields = profile.display_fields
            self.model.setHorizontalHeaderLabels([f.label for f in fields])
            for rec in rows:
                items = []
                for f in fields:
                    text = format_value(rec.get(f.column.upper()), f)
                    item = QStandardItem(" ".join(text.split()))  # multi-line AX text on one row
                    item.setToolTip(text)
                    items.append(item)
                self.model.appendRow(items)
            header = self.table.horizontalHeader()
            for col, f in enumerate(fields):
                mode = QHeaderView.ResizeMode.Stretch if f.column.upper() == "NAME" else QHeaderView.ResizeMode.ResizeToContents
                header.setSectionResizeMode(col, mode)
        self.results_stack.setCurrentIndex(1 if rows else 0)
        if searched and not rows:
            self.empty_title.setText("No matching assets")
            self.empty_hint.setText("Check the search text, date range and company code.")
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
        self.selection_label.setText(f"{n} row(s) selected  ·  Ctrl/Shift + click to select several" if n else "Click a row to preview · Ctrl/Shift + click to select several")
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
