"""Print History (read-only in Phase 1; reprint comes in Phase 4)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QTableView, QVBoxLayout, QWidget

from ...app.context import AppContext
from ..theme import STATUS_COLORS
from ..widgets import Card, page_header

COLUMNS = ["Time", "Document", "Status", "Copies", "Printer", "User", "Template", "Message", "Job ID"]


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


class HistoryPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)
        root.addWidget(page_header(
            "Print History",
            "SpoolerAccepted means Windows accepted the job - it does not prove the sticker printed. "
            "UnknownDelivery must be checked at the printer before printing again.",
        ))
        card = Card()
        top = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        refresh = QPushButton("Refresh")
        top.addWidget(self.count, 1)
        top.addWidget(refresh)
        card.body.addLayout(top)
        self.model = QStandardItemModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        card.body.addWidget(self.table, 1)
        root.addWidget(card, 1)
        refresh.clicked.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        jobs = self.ctx.jobs.list_recent(1000)
        self.model.clear()
        self.model.setHorizontalHeaderLabels(COLUMNS)
        for j in jobs:
            status = QStandardItem(j.status.value)
            status.setForeground(QColor(STATUS_COLORS.get(j.status.value, "#111827")))
            msg = j.error_message or j.reason
            self.model.appendRow([
                QStandardItem(_local_time(j.created_at)), QStandardItem(j.document_ref), status,
                QStandardItem(str(j.copies)), QStandardItem(j.printer_name), QStandardItem(j.username),
                QStandardItem(f"{j.template_id} v{j.template_version}"), QStandardItem(msg), QStandardItem(j.id),
            ])
        self.table.resizeColumnsToContents()
        self.count.setText(f"{len(jobs)} most recent job(s)")
