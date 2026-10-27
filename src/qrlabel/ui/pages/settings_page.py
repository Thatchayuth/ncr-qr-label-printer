"""Application Settings: AX database connection and who sees which menus."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...infrastructure.ax.sql_server import SqlServerDataSource
from ...services.access import ALWAYS_VISIBLE, MENUS, Access
from ..widgets import Banner, Card, page_header
from ..workers import error_text, run_async


def _installed_sql_drivers() -> list[str]:
    try:
        import pyodbc

        return [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:
        return []


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, on_saved=None, on_access_changed=None) -> None:
        super().__init__()
        self.ctx = ctx
        self.on_saved = on_saved
        self.on_access_changed = on_access_changed
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
        root.addWidget(self._build_access_card())
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
        self._load_access()

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

    # ------------------------------------------------------------ access

    def _build_access_card(self) -> Card:
        card = Card("Who sees which menus",
                    "Based on the Windows (Active Directory) account. Members of an admin group see every menu "
                    "without the admin password. Everyone else sees the menus ticked below; the Admin button in "
                    "the sidebar shows every menu after the admin password.")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.me = QLabel()
        self.me.setWordWrap(True)
        self.admin_groups = QLineEdit()
        self.admin_groups.setPlaceholderText("e.g. ICT-RY  (several: comma-separated; DOMAIN\\group also works)")
        menus = QWidget()
        grid = QGridLayout(menus)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        self.menu_checks: dict[str, QCheckBox] = {}
        for i, (key, name) in enumerate(MENUS.items()):
            box = QCheckBox(name.replace("&", "&&"))  # a single & would be a shortcut key
            if key == ALWAYS_VISIBLE:
                box.setChecked(True)
                box.setEnabled(False)
                box.setToolTip("Always shown")
            self.menu_checks[key] = box
            grid.addWidget(box, i // 2, i % 2)
        self.my_groups = QLabel()
        self.my_groups.setObjectName("Muted")
        self.my_groups.setWordWrap(True)
        self.my_groups.setTextInteractionFlags(self.my_groups.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("You", self.me)
        form.addRow("Admin groups", self.admin_groups)
        form.addRow("Other users see", menus)
        form.addRow("Your groups", self.my_groups)
        card.body.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        self.access_save_btn = QPushButton("Save access")
        self.access_save_btn.setObjectName("Primary")
        row.addWidget(self.access_save_btn)
        card.body.addLayout(row)
        self.access_banner = Banner()
        card.body.addWidget(self.access_banner)
        card.setMaximumWidth(760)
        self.access_save_btn.clicked.connect(self._save_access)
        return card

    def _load_access(self) -> None:
        a = self.ctx.config.get("access", {})
        self.admin_groups.setText(", ".join(a.get("admin_groups", [])))
        menus = set(a.get("user_menus", [])) | {ALWAYS_VISIBLE}
        for key, box in self.menu_checks.items():
            box.setChecked(key in menus)
        ident = self.ctx.identity
        self.me.setText(f"<b>{ident.user or 'unknown'}</b> &nbsp;·&nbsp; {self.ctx.access.describe()}")
        names = sorted({g.rsplit("\\", 1)[-1] for g in ident.groups if "\\" in g and not g.upper().startswith(("NT AUTHORITY", "BUILTIN", "MANDATORY LABEL"))})
        self.my_groups.setText(", ".join(names) if names else "No Active Directory groups found (not a domain account?).")

    def _access_form(self) -> dict:
        groups = [g.strip() for g in self.admin_groups.text().split(",") if g.strip()]
        menus = [k for k, box in self.menu_checks.items() if box.isChecked()]
        return {"admin_groups": groups, "user_menus": menus}

    def _save_access(self) -> None:
        access = self._access_form()
        after = Access(self.ctx.identity.user, self.ctx.identity.groups, access)
        if self.ctx.access.is_ad_admin and not after.is_ad_admin:
            answer = QMessageBox.question(
                self, "Save access",
                "Your own Windows account will no longer be in an admin group, so the admin menus will be hidden "
                "(the admin password can still show them). Save anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        new = copy.deepcopy(self.ctx.config)
        new["access"] = access
        try:
            self.ctx.config_service.save(new)
        except Exception as e:
            self.access_banner.show_message(error_text(e), "error")
            return
        self.ctx.config = new
        self.ctx.reload_access()
        self._load_access()
        self.access_banner.show_message("Access saved.", "success")
        if self.on_access_changed:
            self.on_access_changed()
