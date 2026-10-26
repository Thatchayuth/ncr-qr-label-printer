"""Print History: filter, inspect, reprint, confirm results, check the Windows queue, export."""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...domain.models import PrintJob, PrintStatus
from ..icons import icon
from ..theme import STATUS_COLORS
from ..widgets import Banner, Card, chip, labeled, page_header
from ..workers import error_text, run_async

COLUMNS = ["Time", "Asset", "Status", "Type", "Copies", "Printer", "User", "Template", "Note"]
REASONS = ["Sticker damaged", "Sticker lost", "Misprint / unreadable QR", "Printer jam", "Label replaced on asset"]
STATUS_HELP = {
    PrintStatus.PENDING: "Waiting to be sent.",
    PrintStatus.SUBMITTING: "Being sent to the printer.",
    PrintStatus.SPOOLER_ACCEPTED: "Windows accepted the job. This does not prove the sticker printed.",
    PrintStatus.SUBMITTED_TO_DEVICE: "Sent to the print server. This does not prove the sticker printed.",
    PrintStatus.CONFIRMED_PRINTED: "An operator confirmed the sticker printed.",
    PrintStatus.FAILED: "Not printed.",
    PrintStatus.CANCELLED: "Cancelled - not printed.",
    PrintStatus.UNKNOWN_DELIVERY: "Unknown whether it printed. Check the printer, then mark the result.",
}
ATTENTION = [PrintStatus.UNKNOWN_DELIVERY, PrintStatus.FAILED]


def local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso


class ReprintDialog(QDialog):
    def __init__(self, parent: QWidget, jobs: list[PrintJob], printer: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reprint labels")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        refs = ", ".join(j.document_ref for j in jobs[:6]) + (f" and {len(jobs) - 6} more" if len(jobs) > 6 else "")
        head = QLabel(f"<b>Reprint {len(jobs)} label job(s)</b><br>{refs}")
        head.setWordWrap(True)
        lay.addWidget(head)
        info = QLabel("Uses the same data, profile version and template version as the original print. "
                      "Each reprint is saved as a new job linked to the original.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        f = QFormLayout()
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(REASONS)
        self.reason.setCurrentText("")
        self.reason.lineEdit().setPlaceholderText("Why is this label printed again? (required)")
        self.same = QCheckBox("Same number of copies as the original")
        self.same.setChecked(True)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setEnabled(False)
        self.same.toggled.connect(lambda on: self.copies.setEnabled(not on))
        f.addRow("Reason", self.reason)
        f.addRow("", self.same)
        f.addRow("Copies", self.copies)
        f.addRow("Printer", QLabel(printer))
        lay.addLayout(f)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #B91C1C;")
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Reprint")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _accept(self) -> None:
        if len(self.reason.currentText().strip()) < 3:
            self.error.setText("Enter a reason (at least 3 characters).")
            return
        self.accept()

    def values(self) -> tuple[str, int | None]:
        return self.reason.currentText().strip(), None if self.same.isChecked() else self.copies.value()


class HistoryPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.jobs: list[PrintJob] = []
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header(
            "Print History",
            "Every print and reprint. 'SpoolerAccepted' means Windows took the job - it does not prove the sticker printed.",
        ))
        root.addWidget(self._build_filters())
        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)
        body.addWidget(self._build_table_card(), 1)
        body.addWidget(self._build_detail_card())
        self.reload()

    # ------------------------------------------------------------------ UI

    def _build_filters(self) -> Card:
        card = Card()
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        today = QDate.currentDate()
        self.date_on = QCheckBox("Date from")
        self.date_on.setChecked(True)
        self.d_from, self.d_to = QDateEdit(today.addDays(-6)), QDateEdit(today)
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
            d.setMinimumWidth(130)
        self.date_on.toggled.connect(self.d_from.setEnabled)
        self.date_on.toggled.connect(self.d_to.setEnabled)
        drow = QHBoxLayout()
        drow.setSpacing(8)
        drow.addWidget(self.date_on)
        drow.addWidget(self.d_from)
        to = QLabel("to")
        to.setObjectName("Muted")
        drow.addWidget(to)
        drow.addWidget(self.d_to)
        dw = QWidget()
        dw.setLayout(drow)
        drow.setContentsMargins(0, 0, 0, 0)
        self.status = QComboBox()
        self.status.addItem("All statuses", None)
        self.status.addItem("Needs attention (Unknown / Failed)", "attention")
        for s in PrintStatus:
            self.status.addItem(s.value, s.value)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Asset, printer, user or reason")
        self.text.setClearButtonEnabled(True)
        self.refresh_btn = QPushButton("  Refresh")
        self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.setIcon(icon("search", "#FFFFFF", size=16))
        self.export_btn = QPushButton("Export CSV...")
        g.addWidget(labeled("Created", dw), 0, 0)
        g.addWidget(labeled("Status", self.status), 0, 1)
        g.addWidget(labeled("Search", self.text), 0, 2)
        btns = QHBoxLayout()
        btns.addWidget(self.export_btn)
        btns.addWidget(self.refresh_btn)
        bw = QWidget()
        bw.setLayout(btns)
        btns.setContentsMargins(0, 0, 0, 0)
        g.addWidget(bw, 0, 3, Qt.AlignmentFlag.AlignBottom)
        g.setColumnStretch(2, 1)
        card.body.addLayout(g)

        self.refresh_btn.clicked.connect(self.reload)
        self.export_btn.clicked.connect(self._export)
        self.text.returnPressed.connect(self.reload)
        self.status.currentIndexChanged.connect(self.reload)
        return card

    def _build_table_card(self) -> Card:
        card = Card("Jobs")
        self.count_chip = chip("")
        card.header.insertWidget(1, self.count_chip)
        self.attention_chip = chip("", gray=True)
        self.attention_chip.setStyleSheet("QLabel { background:#FFFBEB; color:#92400E; border-radius:10px; padding:3px 10px; font-weight:600; }")
        card.header.insertWidget(2, self.attention_chip)
        self.model = QStandardItemModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setMinimumHeight(360)
        card.body.addWidget(self.table, 1)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        return card

    def _build_detail_card(self) -> Card:
        card = Card("Details")
        card.setFixedWidth(380)
        self.detail = QLabel("Select a job to see its details.")
        self.detail.setObjectName("Muted")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.body.addWidget(self.detail)

        actions = QGridLayout()
        actions.setSpacing(8)
        self.reprint_btn = QPushButton("  Reprint...")
        self.reprint_btn.setObjectName("Primary")
        self.reprint_btn.setIcon(icon("printer", "#FFFFFF", size=16))
        self.reprint_btn.setIconSize(QSize(16, 16))
        self.printed_btn = QPushButton("Mark printed")
        self.failed_btn = QPushButton("Mark not printed")
        self.queue_btn = QPushButton("Check queue")
        self.cancel_btn = QPushButton("Cancel in queue")
        actions.addWidget(self.reprint_btn, 0, 0, 1, 2)
        actions.addWidget(self.printed_btn, 1, 0)
        actions.addWidget(self.failed_btn, 1, 1)
        actions.addWidget(self.queue_btn, 2, 0)
        actions.addWidget(self.cancel_btn, 2, 1)
        card.body.addLayout(actions)
        self.banner = Banner()
        card.body.addWidget(self.banner)
        card.body.addStretch(1)

        self.reprint_btn.setToolTip("Print the selected job(s) again with the same data and template version")
        self.printed_btn.setToolTip("You checked the printer and the sticker came out")
        self.failed_btn.setToolTip("You checked the printer and the sticker did not come out")
        self.queue_btn.setToolTip("Ask Windows whether the job is still waiting in the print queue")
        self.cancel_btn.setToolTip("Remove the job from the Windows print queue if it has not printed yet")
        self.reprint_btn.clicked.connect(self._reprint)
        self.printed_btn.clicked.connect(lambda: self._mark(PrintStatus.CONFIRMED_PRINTED))
        self.failed_btn.clicked.connect(lambda: self._mark(PrintStatus.FAILED))
        self.queue_btn.clicked.connect(self._check_queue)
        self.cancel_btn.clicked.connect(self._cancel_in_queue)
        return card

    # ---------------------------------------------------------------- data

    def _filters(self) -> dict:
        f: dict = {"text": self.text.text(), "limit": 2000}
        if self.date_on.isChecked():
            start = datetime.combine(self.d_from.date().toPython(), time.min).astimezone()
            end = datetime.combine(self.d_to.date().toPython() + timedelta(days=1), time.min).astimezone()
            f.update(start=start, end=end)
        s = self.status.currentData()
        if s == "attention":
            f["statuses"] = ATTENTION
        elif s:
            f["statuses"] = [PrintStatus(s)]
        return f

    def reload(self, *_, keep: list[str] | None = None) -> None:
        keep = keep if keep is not None else [j.id for j in self.selected_jobs()]
        self.jobs = self.ctx.jobs.list_filtered(**self._filters())
        self.model.clear()
        self.model.setHorizontalHeaderLabels(COLUMNS)
        attention_bg = QColor("#FFFBEB")
        for j in self.jobs:
            status = QStandardItem(j.status.value)
            status.setForeground(QColor(STATUS_COLORS.get(j.status.value, "#0F172A")))
            status.setToolTip(STATUS_HELP.get(j.status, ""))
            f = status.font()
            f.setBold(True)
            status.setFont(f)
            note = j.error_message or j.reason
            row = [
                QStandardItem(local_time(j.created_at)), QStandardItem(j.document_ref), status,
                QStandardItem("Reprint" if j.parent_job_id else "Print"), QStandardItem(str(j.copies)),
                QStandardItem(j.printer_name), QStandardItem(j.username),
                QStandardItem(f"v{j.template_version}"), QStandardItem(" ".join(note.split())),
            ]
            row[-1].setToolTip(note)
            if j.status in ATTENTION:
                for it in row:
                    it.setBackground(attention_bg)
            self.model.appendRow(row)
        header = self.table.horizontalHeader()
        for col in range(len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMNS.index("Note"), QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMNS.index("Printer"), QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COLUMNS.index("Printer"), 160)
        self.count_chip.setText(f"{len(self.jobs)} job(s)")
        unknown = sum(j.status == PrintStatus.UNKNOWN_DELIVERY for j in self.jobs)
        self.attention_chip.setText(f"⚠ {unknown} unknown")
        self.attention_chip.setVisible(unknown > 0)
        if keep:
            sel = self.table.selectionModel()
            for row, j in enumerate(self.jobs):
                if j.id in keep:
                    self.table.selectRow(row) if len(keep) == 1 else sel.select(
                        self.model.index(row, 0),
                        sel.SelectionFlag.Select | sel.SelectionFlag.Rows,
                    )
        self._on_selection()

    def selected_jobs(self) -> list[PrintJob]:
        if not hasattr(self, "table"):
            return []
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.jobs[r] for r in rows if r < len(self.jobs)]

    # -------------------------------------------------------------- detail

    def _on_selection(self) -> None:
        jobs = self.selected_jobs()
        one = jobs[0] if len(jobs) == 1 else None
        sent = {PrintStatus.SPOOLER_ACCEPTED, PrintStatus.SUBMITTED_TO_DEVICE, PrintStatus.UNKNOWN_DELIVERY}
        self.reprint_btn.setEnabled(bool(jobs) and not self._busy)
        self.reprint_btn.setText(f"  Reprint {len(jobs)} job(s)..." if len(jobs) > 1 else "  Reprint...")
        self.printed_btn.setEnabled(bool(one) and one.status in sent and not self._busy)
        self.failed_btn.setEnabled(bool(one) and one.status in sent | {PrintStatus.PENDING, PrintStatus.SUBMITTING} and not self._busy)
        queue_ok = bool(one) and one.adapter in ("spooler", "shared") and not self._busy
        self.queue_btn.setEnabled(queue_ok)
        self.cancel_btn.setEnabled(queue_ok and one.status == PrintStatus.SPOOLER_ACCEPTED and bool(one.spool_job_id))
        if not jobs:
            self.detail.setText("Select a job to see its details.")
            self.banner.clear_message()
            return
        if not one:
            self.detail.setText(f"<b>{len(jobs)} jobs selected.</b><br>You can reprint them together.")
            return
        self.detail.setText(self._detail_html(one))

    def _detail_html(self, j: PrintJob) -> str:
        color = STATUS_COLORS.get(j.status.value, "#0F172A")
        rows = [
            ("Asset", f"<b>{j.document_ref}</b>"),
            ("Status", f"<span style='color:{color}; font-weight:600'>{j.status.value}</span>"),
            ("", f"<span style='color:#64748B'>{STATUS_HELP.get(j.status, '')}</span>"),
            ("Copies", str(j.copies)),
            ("Printer", f"{j.printer_name} <span style='color:#64748B'>({j.adapter})</span>"),
            ("User", j.username),
            ("Profile", f"{j.profile_id} v{j.profile_version}"),
            ("Template", f"{j.template_id} v{j.template_version}"),
            ("Windows job", str(j.spool_job_id) if j.spool_job_id else "-"),
        ]
        if j.reason:
            rows.append(("Reason", j.reason))
        if j.error_message:
            rows.append(("Error", f"<span style='color:#B91C1C'>{j.error_code}: {j.error_message}</span>"))
        if j.parent_job_id:
            parent = self.ctx.jobs.get(j.parent_job_id)
            rows.append(("Reprint of", f"{local_time(parent.created_at)} ({parent.status.value})" if parent else j.parent_job_id))
        children = self.ctx.jobs.children(j.id)
        if children:
            rows.append(("Reprinted", f"{len(children)} time(s), last {local_time(children[-1].created_at)}"))
        table = "".join(
            f"<tr><td style='color:#64748B; padding:2px 12px 2px 0; white-space:nowrap'>{k}</td><td>{v}</td></tr>" for k, v in rows
        )
        events = "".join(
            f"<tr><td style='color:#64748B; padding:2px 10px 2px 0; white-space:nowrap'>{local_time(at)[11:]}</td>"
            f"<td style='color:{STATUS_COLORS.get(st, '#0F172A')}; padding-right:8px'>{st}</td><td>{msg}</td></tr>"
            for at, st, msg in self.ctx.jobs.events(j.id)
        )
        return (
            f"<table>{table}</table><br><b>Timeline</b><table style='margin-top:4px'>{events}</table>"
            f"<p style='color:#94A3B8; font-size:8pt'>Job {j.id}</p>"
        )

    # ------------------------------------------------------------- actions

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._on_selection()

    def _reprint(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            return
        try:
            adapter = self.ctx.printer_adapter()
            self.ctx.print_service.plan_reprint([j.id for j in jobs])
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        dlg = ReprintDialog(self, jobs, adapter.target)
        dlg.copies.setValue(jobs[0].copies)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        reason, copies = dlg.values()
        self._set_busy(True)
        self.banner.show_message("Sending reprint...", "info")
        ids = [j.id for j in jobs]
        run_async(
            lambda: self.ctx.print_service.reprint(job_ids=ids, reason=reason, adapter=adapter, copies=copies),
            self._on_reprinted, self._on_error,
        )

    def _on_reprinted(self, new_jobs: list[PrintJob]) -> None:
        self._set_busy(False)
        ok = [j for j in new_jobs if j.status in (PrintStatus.SPOOLER_ACCEPTED, PrintStatus.SUBMITTED_TO_DEVICE)]
        self.reload(keep=[j.id for j in new_jobs])
        if new_jobs and len(ok) == len(new_jobs):
            self.banner.show_message(f"{len(ok)} reprint job(s) sent ({new_jobs[0].status.value}).", "success")
        else:
            bad = next((j for j in new_jobs if j not in ok), None)
            self.banner.show_message(
                f"Reprint stopped after {len(new_jobs)} job(s)." + (f"\n{bad.document_ref}: {bad.status.value} {bad.error_message}" if bad else ""),
                "error",
            )

    def _mark(self, status: PrintStatus) -> None:
        jobs = self.selected_jobs()
        if len(jobs) != 1:
            return
        title = "Mark as printed" if status == PrintStatus.CONFIRMED_PRINTED else "Mark as NOT printed"
        note, ok = QInputDialog.getText(self, title, f"{jobs[0].document_ref}\nNote (optional):")
        if not ok:
            return
        try:
            self.ctx.print_service.confirm(jobs[0].id, status, note)
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self.reload(keep=[jobs[0].id])
        self.banner.show_message(f"Recorded: {status.value}.", "success")

    def _check_queue(self) -> None:
        jobs = self.selected_jobs()
        if len(jobs) != 1:
            return
        adapter = self.ctx.queue_adapter_for(jobs[0])
        self._set_busy(True)
        run_async(lambda: adapter.queue_state(jobs[0].spool_job_id), self._on_queue, self._on_error)

    def _on_queue(self, state) -> None:
        self._set_busy(False)
        self.banner.show_message(state.text, "warning" if state.problem else "info")

    def _cancel_in_queue(self) -> None:
        jobs = self.selected_jobs()
        if len(jobs) != 1:
            return
        adapter = self.ctx.queue_adapter_for(jobs[0])
        self._set_busy(True)
        run_async(lambda: self.ctx.print_service.cancel_in_queue(jobs[0].id, adapter), self._on_cancelled, self._on_error)

    def _on_cancelled(self, job: PrintJob) -> None:
        self._set_busy(False)
        self.reload(keep=[job.id])
        self.banner.show_message("Removed from the Windows print queue. Recorded as Cancelled.", "success")

    def _on_error(self, e: Exception) -> None:
        self._set_busy(False)
        self.reload()
        self.banner.show_message(error_text(e), "error")

    # -------------------------------------------------------------- export

    def _export(self) -> None:
        if not self.jobs:
            self.banner.show_message("Nothing to export.", "info")
            return
        default = f"print-history-{datetime.now():%Y%m%d-%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export print history", default, "CSV (*.csv)")
        if not path:
            return
        try:
            export_csv(self.jobs, Path(path))
        except OSError as e:
            self.banner.show_message(f"Cannot write file: {e}", "error")
            return
        self.banner.show_message(f"Exported {len(self.jobs)} job(s) to {path}", "success")


def export_csv(jobs: list[PrintJob], path: Path) -> None:
    """UTF-8 with BOM so Excel shows Thai correctly."""
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "Created", "Asset", "Status", "Type", "Copies", "Printer", "Adapter", "User", "Profile", "Profile version",
            "Template", "Template version", "Reason", "Error code", "Error message", "Windows job", "Job ID", "Reprint of",
        ])
        for j in jobs:
            w.writerow([
                local_time(j.created_at), j.document_ref, j.status.value, "Reprint" if j.parent_job_id else "Print",
                j.copies, j.printer_name, j.adapter, j.username, j.profile_id, j.profile_version, j.template_id,
                j.template_version, j.reason, j.error_code, j.error_message, j.spool_job_id or "", j.id, j.parent_job_id,
            ])
