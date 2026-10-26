"""Application Settings: AX database connection."""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...infrastructure.ax.sql_server import SqlServerDataSource
from ..widgets import Banner, Card, page_header
from ..workers import error_text, run_async


def _installed_sql_drivers() -> list[str]:
    try:
        import pyodbc

        return [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:
        return []


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, on_saved=None) -> None:
        super().__init__()
        self.ctx = ctx
        self.on_saved = on_saved
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)
        root.addWidget(page_header("Application Settings", "Connection to the Dynamics AX 4.0 SQL Server (read-only)."))

        card = Card("AX database connection",
                    "Use a SQL login that can only read (db_datareader). The password is encrypted with Windows DPAPI "
                    "for the current Windows user and is never written to logs.")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.mock = QCheckBox("Use sample data (development - no database needed)")
        self.server = QLineEdit()
        self.server.setPlaceholderText(r"SERVER or SERVER\INSTANCE or SERVER,PORT")
        self.database = QLineEdit()
        self.driver = QComboBox()
        self.driver.setEditable(True)
        self.driver.addItems(_installed_sql_drivers())
        self.auth = QComboBox()
        self.auth.addItem("SQL Server Authentication", "sql")
        self.auth.addItem("Windows Integrated Authentication", "windows")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.encrypt = QCheckBox("Encrypt connection")
        self.trust = QCheckBox("Trust server certificate")
        self.connect_timeout = QSpinBox()
        self.connect_timeout.setRange(1, 120)
        self.connect_timeout.setSuffix(" s")
        self.query_timeout = QSpinBox()
        self.query_timeout.setRange(1, 600)
        self.query_timeout.setSuffix(" s")
        self.company = QLineEdit()
        self.company.setMaxLength(8)
        self.sources = QLineEdit()
        self.sources.setToolTip("Comma-separated list of tables/views operators may query.")

        form.addRow("", self.mock)
        form.addRow("SQL Server", self.server)
        form.addRow("Database", self.database)
        form.addRow("ODBC driver", self.driver)
        form.addRow("Authentication", self.auth)
        form.addRow("User name", self.username)
        form.addRow("Password", self.password)
        form.addRow("", self.encrypt)
        form.addRow("", self.trust)
        form.addRow("Connect timeout", self.connect_timeout)
        form.addRow("Query timeout", self.query_timeout)
        form.addRow("Default company", self.company)
        form.addRow("Approved sources", self.sources)
        card.body.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.test_btn = QPushButton("Test connection")
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("Primary")
        buttons.addWidget(self.test_btn)
        buttons.addWidget(self.save_btn)
        card.body.addLayout(buttons)
        self.banner = Banner()
        card.body.addWidget(self.banner)
        card.setMaximumWidth(760)
        root.addWidget(card)
        root.addStretch(1)

        self.mock.toggled.connect(self._update_enabled)
        self.auth.currentIndexChanged.connect(self._update_enabled)
        self.test_btn.clicked.connect(self._test)
        self.save_btn.clicked.connect(self._save)
        self.load()

    def load(self) -> None:
        d = self.ctx.config["database"]
        self.mock.setChecked(d["use_mock"])
        self.server.setText(d["server"])
        self.database.setText(d["database"])
        self.driver.setCurrentText(d["driver"])
        self.auth.setCurrentIndex(max(0, self.auth.findData(d["auth"])))
        self.username.setText(d["username"])
        self.password.clear()
        self.password.setPlaceholderText("(saved - leave blank to keep)" if d.get("password_dpapi") else "")
        self.encrypt.setChecked(d.get("encrypt", False))
        self.trust.setChecked(d.get("trust_server_certificate", True))
        self.connect_timeout.setValue(d.get("connect_timeout", 10))
        self.query_timeout.setValue(d.get("query_timeout", 30))
        self.company.setText(d.get("company", ""))
        self.sources.setText(", ".join(self.ctx.config["approved_sources"]))
        self._update_enabled()

    def _update_enabled(self) -> None:
        live = not self.mock.isChecked()
        for w in (self.server, self.database, self.driver, self.auth, self.encrypt, self.trust,
                  self.connect_timeout, self.query_timeout):
            w.setEnabled(live)
        sql_auth = live and self.auth.currentData() == "sql"
        self.username.setEnabled(sql_auth)
        self.password.setEnabled(sql_auth)

    def _form_database(self) -> dict:
        d = copy.deepcopy(self.ctx.config["database"])
        d.update(
            use_mock=self.mock.isChecked(), server=self.server.text().strip(), database=self.database.text().strip(),
            driver=self.driver.currentText().strip(), auth=self.auth.currentData(), username=self.username.text().strip(),
            encrypt=self.encrypt.isChecked(), trust_server_certificate=self.trust.isChecked(),
            connect_timeout=self.connect_timeout.value(), query_timeout=self.query_timeout.value(),
            company=self.company.text().strip(),
        )
        return d

    def _sources(self) -> list[str]:
        return [s.strip() for s in self.sources.text().split(",") if s.strip()]

    def _test(self) -> None:
        if self.mock.isChecked():
            self.banner.show_message("Sample data mode is on - no database connection is used.", "info")
            return
        settings = self._form_database()
        typed = self.password.text()
        saved = self.ctx.config
        src = SqlServerDataSource(settings, lambda: typed or self.ctx.config_service.get_password(saved), self._sources())

        def work():
            info = src.test_connection()
            cols = src.list_columns(self._sources()[0]) if self._sources() else []
            return info, cols

        self.test_btn.setEnabled(False)
        self.banner.show_message("Connecting...", "info")
        run_async(work, self._on_test_ok, self._on_test_error)

    def _on_test_ok(self, result) -> None:
        self.test_btn.setEnabled(True)
        info, cols = result
        msg = info
        if cols:
            msg += f"\n{self._sources()[0]}: {len(cols)} columns found ({', '.join(c for c, _ in cols[:12])}{'...' if len(cols) > 12 else ''})"
        self.banner.show_message(msg, "success")

    def _on_test_error(self, e: Exception) -> None:
        self.test_btn.setEnabled(True)
        self.banner.show_message(error_text(e), "error")

    def _save(self) -> None:
        new = copy.deepcopy(self.ctx.config)
        new["database"] = self._form_database()
        new["approved_sources"] = self._sources()
        try:
            if self.password.text():
                self.ctx.config_service.set_password(new, self.password.text())
            if new["database"]["auth"] == "windows":
                new["database"]["password_dpapi"] = ""
            self.ctx.config_service.save(new)
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self.ctx.config = new
        self.load()
        self.banner.show_message("Settings saved.", "success")
        if self.on_saved:
            self.on_saved()
