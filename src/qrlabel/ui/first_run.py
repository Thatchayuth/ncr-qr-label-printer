"""First-run setup wizard: admin check -> AX connection -> printer -> done."""
from __future__ import annotations

import copy
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..app import paths
from ..app.context import AppContext
from ..domain.models import new_id
from ..infrastructure.ax.sql_server import SqlServerDataSource
from ..infrastructure.printing.adapters import (
    MockPrinterAdapter,
    WindowsSharedPrinterAdapter,
    WindowsSpoolerAdapter,
)
from .pages.settings_page import driver_from_combo, fill_driver_combo
from .printer_picker import PrinterPicker
from .widgets import Banner
from .workers import error_text, run_async

log = logging.getLogger(__name__)


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


class WelcomePage(QWizardPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setTitle("Welcome to NCR Print Label")
        self.setSubTitle("This short setup connects the program to Dynamics AX and to the label printer.")
        lay = QVBoxLayout(self)
        lay.addWidget(_muted(
            "You need the admin password to change these settings. You can run this setup later "
            "from Application Settings and Printer Settings."
        ))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Admin password")
        lay.addWidget(self.password)
        self.banner = Banner()
        lay.addWidget(self.banner)
        lay.addStretch(1)

    def validatePage(self) -> bool:
        try:
            ok = self.ctx.admin.verify(self.password.text())
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return False
        if not ok:
            self.banner.show_message("Wrong password.", "error")
            self.password.clear()
            return False
        return True


class DatabasePage(QWizardPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._tested_ok = False
        self.setTitle("Dynamics AX connection")
        self.setSubTitle("Use a SQL login that can only read the AX database.")
        lay = QVBoxLayout(self)
        self.sample = QRadioButton("Use sample data for now (no database)")
        self.live = QRadioButton("Connect to the AX SQL Server")
        group = QButtonGroup(self)
        group.addButton(self.sample)
        group.addButton(self.live)
        lay.addWidget(self.live)
        lay.addWidget(self.sample)

        d = ctx.config["database"]
        self.form_w = QWidget()
        f = QFormLayout(self.form_w)
        f.setContentsMargins(24, 4, 0, 0)
        self.server = QLineEdit(d["server"])
        self.server.setPlaceholderText(r"SERVER or SERVER\INSTANCE")
        self.database = QLineEdit(d["database"])
        self.driver = QComboBox()
        self.driver.setEditable(True)
        fill_driver_combo(self.driver, d["driver"])
        self.username = QLineEdit(d["username"])
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.company = QLineEdit(d.get("company", ""))
        self.company.setMaxLength(8)
        self.company.setPlaceholderText("DATAAREAID, e.g. db1")
        f.addRow("SQL Server", self.server)
        f.addRow("Database", self.database)
        f.addRow("ODBC driver", self.driver)
        f.addRow("SQL user", self.username)
        f.addRow("Password", self.password)
        f.addRow("Company", self.company)
        lay.addWidget(self.form_w)
        row = QHBoxLayout()
        row.addStretch(1)
        self.test_btn = QPushButton("Test connection")
        row.addWidget(self.test_btn)
        lay.addLayout(row)
        self.banner = Banner()
        lay.addWidget(self.banner)
        lay.addStretch(1)

        (self.sample if d["use_mock"] else self.live).setChecked(True)
        self.sample.toggled.connect(self._mode_changed)
        for e in (self.server, self.database, self.username, self.password, self.company):
            e.textChanged.connect(self._edited)
        self.driver.currentTextChanged.connect(self._edited)
        self.test_btn.clicked.connect(self._test)
        self._mode_changed()

    def _settings(self) -> dict:
        d = copy.deepcopy(self.ctx.config["database"])
        d.update(
            use_mock=self.sample.isChecked(), server=self.server.text().strip(), database=self.database.text().strip(),
            driver=driver_from_combo(self.driver), auth="sql", username=self.username.text().strip(),
            company=self.company.text().strip(),
        )
        return d

    def _mode_changed(self, *_) -> None:
        live = self.live.isChecked()
        self.form_w.setEnabled(live)
        self.test_btn.setEnabled(live)
        self.banner.clear_message()
        self.completeChanged.emit()

    def _edited(self, *_) -> None:
        self._tested_ok = False
        self.completeChanged.emit()

    def _test(self) -> None:
        settings = self._settings()
        typed = self.password.text()
        saved = self.ctx.config
        src = SqlServerDataSource(settings, lambda: typed or self.ctx.config_service.get_password(saved), self.ctx.config["approved_sources"])
        self.test_btn.setEnabled(False)
        self.banner.show_message("Connecting...", "info")

        def work():
            info = src.test_connection()
            cols = src.list_columns(self.ctx.config["approved_sources"][0])
            return f"{info}\n{self.ctx.config['approved_sources'][0]}: {len(cols)} columns found."

        run_async(work, self._ok, self._fail)

    def _ok(self, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self._tested_ok = True
        self.banner.show_message(msg, "success")
        self.completeChanged.emit()

    def _fail(self, e: Exception) -> None:
        self.test_btn.setEnabled(True)
        self._tested_ok = False
        self.banner.show_message(error_text(e), "error")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        if self.sample.isChecked():
            return True
        return self._tested_ok and bool(self.company.text().strip())

    def validatePage(self) -> bool:
        self.ctx.config["database"] = self._settings()
        if self.live.isChecked() and self.password.text():
            self.ctx.config_service.set_password(self.ctx.config, self.password.text())
        return True


class PrinterPage(QWizardPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setTitle("Label printer")
        self.setSubTitle("TSC label printer on USB at the main PC, or the printer shared from the main PC.")
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.adapter = QComboBox()
        self.adapter.addItem("Label printer on this PC (TSC on USB)", "spooler")
        self.adapter.addItem("Shared printer on the main PC", "shared")
        self.adapter.addItem("No printer yet - save .prn files", "mock")
        self.printer = PrinterPicker()
        self.printer.refresh(ctx.config["printer"].get("printer_name", ""))
        tsc = next((p.name for p in self.printer.printers if p.is_label_printer), "")
        self.shared = QLineEdit(ctx.config["printer"].get("shared_path", ""))
        self.shared.setPlaceholderText(r"\\MAIN-PC\TSC_TE210")
        f.addRow("Print to", self.adapter)
        f.addRow("Printer", self.printer)
        f.addRow("Shared path", self.shared)
        self.form = f
        lay.addLayout(f)
        lay.addWidget(_muted(
            "Install the TSC driver and calibrate the gap sensor first. A test label shows a QR code with TEST-0001."
        ))
        row = QHBoxLayout()
        row.addStretch(1)
        self.test_btn = QPushButton("Print test label")
        row.addWidget(self.test_btn)
        lay.addLayout(row)
        self.banner = Banner()
        lay.addWidget(self.banner)
        lay.addStretch(1)
        current = ctx.config["printer"]["adapter"]
        self.adapter.setCurrentIndex(max(0, self.adapter.findData(current if current != "tcp" else "spooler")))
        if current == "mock" and tsc:
            self.adapter.setCurrentIndex(self.adapter.findData("spooler"))
        self.adapter.currentIndexChanged.connect(self._rows)
        self.test_btn.clicked.connect(self._test_print)
        self._rows()

    def _rows(self, *_) -> None:
        kind = self.adapter.currentData()
        self.form.setRowVisible(self.printer, kind == "spooler")
        self.form.setRowVisible(self.shared, kind == "shared")
        self.banner.clear_message()

    def _build(self):
        kind = self.adapter.currentData()
        if kind == "spooler":
            return WindowsSpoolerAdapter(self.printer.current_name())
        if kind == "shared":
            return WindowsSharedPrinterAdapter(self.shared.text().strip())
        return MockPrinterAdapter(paths.mock_output_dir())

    def _test_print(self) -> None:
        try:
            adapter = self._build()
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        profile = self.ctx.profiles.list_latest()[0]
        template = self.ctx.templates.get(profile.template_id) or self.ctx.templates.list_latest()[0]
        record = {f.column.upper(): "TEST-0001" for f in profile.fields}
        self.test_btn.setEnabled(False)
        self.banner.show_message("Sending test label...", "info")

        def work():
            job = self.ctx.print_service.print_records(
                records=[record], profile=profile, template=template, adapter=adapter, copies=1,
                correlation_id=new_id(), reason="Setup test print",
            )[0]
            return job

        run_async(work, self._printed, self._failed)

    def _printed(self, job) -> None:
        self.test_btn.setEnabled(True)
        ok = job.status.value in ("SpoolerAccepted", "SubmittedToDevice")
        msg = f"Test label: {job.status.value}." + (f" {job.error_message}" if job.error_message else "")
        if ok and job.adapter == "mock":
            msg = "Test label saved as a .prn file (no printer selected - nothing was printed)."
        elif ok:
            msg += " Check that the sticker printed and the QR code scans."
        self.banner.show_message(msg, "success" if ok else "error")

    def _failed(self, e: Exception) -> None:
        self.test_btn.setEnabled(True)
        self.banner.show_message(error_text(e), "error")

    def validatePage(self) -> bool:
        try:
            self._build()
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return False
        p = self.ctx.config["printer"]
        p.update(adapter=self.adapter.currentData(), printer_name=self.printer.current_name(),
                 shared_path=self.shared.text().strip())
        return True


class DonePage(QWizardPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setTitle("Ready")
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.summary)
        lay.addStretch(1)

    def initializePage(self) -> None:
        d, p = self.ctx.config["database"], self.ctx.config["printer"]
        data = "Sample data" if d["use_mock"] else f"{d['server']} / {d['database']} (company {d.get('company', '')})"
        printer = {"spooler": p.get("printer_name"), "shared": p.get("shared_path"), "mock": "Sample printer (.prn files)"}.get(p["adapter"], p["adapter"])
        self.summary.setText(
            f"<p><b>Data:</b> {data}<br><b>Printer:</b> {printer}</p>"
            "<p>Press <b>Finish</b> to save. You can change these later in Application Settings and Printer Settings "
            "(admin password required).</p>"
            "<p style='color:#B45309'><b>Recommended:</b> change the admin password in Application Settings.</p>"
        )


class FirstRunWizard(QWizard):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._original = copy.deepcopy(ctx.config)
        self.setWindowTitle("NCR Print Label - Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setMinimumSize(640, 520)
        self.setStyleSheet("QWizard, QWizardPage { background: #FFFFFF; }")
        for page in (WelcomePage(ctx), DatabasePage(ctx), PrinterPage(ctx), DonePage(ctx)):
            self.addPage(page)
        self.currentIdChanged.connect(lambda _: self._hide_aero_back_button())

    def _hide_aero_back_button(self) -> None:
        """QWizard starts in Aero style on Windows and leaves its round back-arrow button
        (top-left) visible after switching to Modern style. The normal Back button is used instead."""
        for b in self.findChildren(QAbstractButton):
            if type(b) is QAbstractButton and not b.text():
                b.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._hide_aero_back_button()

    def accept(self) -> None:
        try:
            self.ctx.save_config()
        except Exception as e:
            self.currentPage().layout().addWidget(QLabel(f"Could not save settings: {error_text(e)}"))
            return
        log.info("First-run setup completed (mock=%s, printer=%s)", self.ctx.config["database"]["use_mock"], self.ctx.config["printer"]["adapter"])
        super().accept()

    def reject(self) -> None:
        self.ctx.config = self._original  # nothing saved; the wizard opens again next time
        super().reject()
