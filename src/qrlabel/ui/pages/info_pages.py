"""Diagnostics plus read-only views for features scheduled in later phases."""
from __future__ import annotations

import json
import os
import platform
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ...app import paths
from ...app.context import AppContext
from ...domain.layout import validate_template
from ..widgets import Card, page_header


def _mono_box() -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setReadOnly(True)
    f = QFont("Consolas")
    f.setPointSize(9)
    box.setFont(f)
    return box


class ReadOnlyJsonPage(QWidget):
    """Shows the current configuration objects until the editor for them is built."""

    def __init__(self, ctx: AppContext, title: str, subtitle: str, kind: str) -> None:
        super().__init__()
        self.ctx, self.kind = ctx, kind
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)
        root.addWidget(page_header(title, subtitle))
        card = Card("Current configuration (read-only)")
        self.box = _mono_box()
        card.body.addWidget(self.box, 1)
        root.addWidget(card, 1)
        self.reload()

    def reload(self) -> None:
        if self.kind == "profiles":
            data = [p.to_dict() for p in self.ctx.profiles.list_latest()]
        elif self.kind == "qr":
            data = [{"profile": p.name, "version": p.version, "qr": p.to_dict()["qr"]} for p in self.ctx.profiles.list_latest()]
        else:
            data = []
            for t in self.ctx.templates.list_latest():
                d = t.to_dict()
                d["validation"] = validate_template(t) or "OK"
                data.append(d)
        self.box.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))


class DiagnosticsPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)
        root.addWidget(page_header("Diagnostics", "Information to share with IT support. No passwords are shown."))
        card = Card()
        self.box = _mono_box()
        card.body.addWidget(self.box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        open_btn = QPushButton("Open data folder")
        refresh = QPushButton("Refresh")
        row.addWidget(open_btn)
        row.addWidget(refresh)
        card.body.addLayout(row)
        root.addWidget(card, 1)
        open_btn.clicked.connect(lambda: os.startfile(paths.app_data_dir()))
        refresh.clicked.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        lines = [
            f"Application      : NCR Print Label {self.ctx.version}",
            f"Python           : {sys.version.split()[0]} ({platform.architecture()[0]})",
            f"Windows          : {platform.platform()}",
            f"Data folder      : {paths.app_data_dir()}",
            f"Database file    : {paths.database_path()}",
            f"Log folder       : {paths.log_dir()}",
            f"Data mode        : {'SAMPLE DATA (mock)' if self.ctx.using_mock_data else 'AX SQL Server'}",
        ]
        db = self.ctx.config["database"]
        if not self.ctx.using_mock_data:
            lines += [
                f"SQL server       : {db['server']}",
                f"SQL database     : {db['database']}",
                f"ODBC driver      : {db['driver']}",
                f"Authentication   : {db['auth']}  (password saved: {'yes' if db.get('password_dpapi') else 'no'})",
            ]
        try:
            import pyodbc

            lines.append(f"ODBC drivers     : {', '.join(pyodbc.drivers())}")
        except Exception as e:
            lines.append(f"ODBC drivers     : unavailable ({e})")
        p = self.ctx.config["printer"]
        lines.append(f"Printer adapter  : {p['adapter']}")
        try:
            lines.append(f"Printer target   : {self.ctx.printer_adapter().target}")
        except Exception as e:
            lines.append(f"Printer target   : not configured ({e})")
        try:
            from ...infrastructure.printing.adapters import list_windows_printers

            lines.append("Windows printers :")
            lines += [f"  - {n}" for n in list_windows_printers()]
        except Exception as e:
            lines.append(f"Windows printers : unavailable ({e})")
        lines.append(f"Profiles         : {', '.join(f'{x.id} v{x.version}' for x in self.ctx.profiles.list_latest())}")
        lines.append(f"Templates        : {', '.join(f'{x.id} v{x.version}' for x in self.ctx.templates.list_latest())}")
        self.box.setPlainText("\n".join(lines))
