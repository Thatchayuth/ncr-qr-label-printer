"""Printer Settings: choose destination, test connection, test print."""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app import paths
from ...app.context import AppContext
from ...domain.models import new_id
from ...infrastructure.printing.adapters import (
    MockPrinterAdapter,
    TcpPrinterAdapter,
    WindowsSharedPrinterAdapter,
    WindowsSpoolerAdapter,
)
from ..printer_picker import PrinterPicker
from ..widgets import Banner, Card, page_header
from ..workers import error_text, run_async

ADAPTERS = [
    ("Sample printer - save .prn files (no printer needed)", "mock"),
    ("Label printer on this PC (TSC on USB)", "spooler"),
    ("Shared printer on another PC (\\\\HOST\\Share)", "shared"),
    ("Network print server - RAW TCP 9100 (optional)", "tcp"),
]

CALIBRATION_TEXT = (
    "<b>Before the first print</b><ol style='margin-left:-20px'>"
    "<li>Install the TSC Windows driver (TE200 / TE210) on the PC the printer is plugged into.</li>"
    "<li>Load the sticker roll and run the printer's gap-sensor calibration "
    "(TSC Diagnostic Tool &rarr; Calibrate Sensor, or the procedure in the printer user manual).</li>"
    "<li>Set the label size in the Label Designer to the measured sticker size and gap.</li>"
    "<li>Use <b>Test print</b> here and scan the QR code with a phone or scanner.</li>"
    "</ol>"
    "<b>Other PCs</b> print through the main PC: share the TSC printer in Windows on the main PC, "
    "then choose <i>Shared printer</i> here and enter <code>\\\\MAIN-PC\\ShareName</code>."
)


class PrinterPage(QWidget):
    def __init__(self, ctx: AppContext, on_saved=None) -> None:
        super().__init__()
        self.ctx = ctx
        self.on_saved = on_saved
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)
        root.addWidget(page_header("Printer Settings", "TSC TE200 / TE210 - 203 dpi - TSPL. Data is sent RAW (no driver rendering)."))

        row = QHBoxLayout()
        row.setSpacing(16)
        root.addLayout(row)

        card = Card("Destination")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.adapter = QComboBox()
        for label, key in ADAPTERS:
            self.adapter.addItem(label, key)
        self.printer_row_w = PrinterPicker()
        self.shared = QLineEdit()
        self.shared.setPlaceholderText(r"\\MAIN-PC\TSC_TE200")
        self.tcp_host = QLineEdit()
        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.mock_info = QLabel(f"Files are written to:\n{paths.mock_output_dir()}")
        self.mock_info.setObjectName("Muted")
        self.mock_info.setWordWrap(True)
        form.addRow("Print to", self.adapter)
        form.addRow("Printer", self.printer_row_w)
        form.addRow("Shared path", self.shared)
        form.addRow("Print server host", self.tcp_host)
        form.addRow("Port", self.tcp_port)
        form.addRow("", self.mock_info)
        self.form = form
        card.body.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.test_btn = QPushButton("Test connection")
        self.test_print_btn = QPushButton("Test print")
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("Primary")
        for b in (self.test_btn, self.test_print_btn, self.save_btn):
            buttons.addWidget(b)
        card.body.addLayout(buttons)
        self.banner = Banner()
        card.body.addWidget(self.banner)
        card.body.addStretch(1)
        row.addWidget(card, 3)

        help_card = Card("Setup & calibration")
        help_text = QLabel(CALIBRATION_TEXT)
        help_text.setWordWrap(True)
        help_card.body.addWidget(help_text)
        help_card.body.addStretch(1)
        row.addWidget(help_card, 2)
        root.addStretch(1)

        self.adapter.currentIndexChanged.connect(self._update_rows)
        self.test_btn.clicked.connect(self._test)
        self.test_print_btn.clicked.connect(self._test_print)
        self.save_btn.clicked.connect(self._save)
        self.load()

    def load(self) -> None:
        p = self.ctx.config["printer"]
        self.adapter.setCurrentIndex(max(0, self.adapter.findData(p["adapter"])))
        self.printer_row_w.refresh(p.get("printer_name", ""))
        self.shared.setText(p.get("shared_path", ""))
        self.tcp_host.setText(p.get("tcp_host", ""))
        self.tcp_port.setValue(int(p.get("tcp_port", 9100)))
        self._update_rows()

    def reload(self) -> None:
        """Called when the page is opened: pick up printers plugged in since the last visit."""
        self.printer_row_w.refresh(self.printer_row_w.current_name() or self.ctx.config["printer"].get("printer_name", ""))

    def _update_rows(self) -> None:
        kind = self.adapter.currentData()
        visible = {
            self.printer_row_w: kind == "spooler",
            self.shared: kind == "shared",
            self.tcp_host: kind == "tcp",
            self.tcp_port: kind == "tcp",
            self.mock_info: kind == "mock",
        }
        for w, show in visible.items():
            self.form.setRowVisible(w, show)

    def _form_printer(self) -> dict:
        p = copy.deepcopy(self.ctx.config["printer"])
        p.update(
            adapter=self.adapter.currentData(), printer_name=self.printer_row_w.current_name(),
            shared_path=self.shared.text().strip(), tcp_host=self.tcp_host.text().strip(), tcp_port=self.tcp_port.value(),
        )
        return p

    def _build_adapter(self):
        p = self._form_printer()
        if p["adapter"] == "spooler":
            return WindowsSpoolerAdapter(p["printer_name"])
        if p["adapter"] == "shared":
            return WindowsSharedPrinterAdapter(p["shared_path"])
        if p["adapter"] == "tcp":
            return TcpPrinterAdapter(p["tcp_host"], p["tcp_port"])
        return MockPrinterAdapter(paths.mock_output_dir())

    def _busy(self, busy: bool) -> None:
        for b in (self.test_btn, self.test_print_btn, self.save_btn):
            b.setEnabled(not busy)

    def _test(self) -> None:
        try:
            adapter = self._build_adapter()
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self._busy(True)
        self.banner.show_message("Checking printer...", "info")
        run_async(adapter.test_connection, self._ok, self._fail)

    def _test_print(self) -> None:
        try:
            adapter = self._build_adapter()
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        profiles = self.ctx.profiles.list_latest()
        if not profiles:
            self.banner.show_message("No data profile exists.", "error")
            return
        profile = profiles[0]
        template = self.ctx.templates.get(profile.template_id) or self.ctx.templates.list_latest()[0]
        record = {f.column.upper(): "TEST-0001" for f in profile.fields}

        def work():
            jobs = self.ctx.print_service.print_records(
                records=[record], profile=profile, template=template, adapter=adapter,
                copies=1, correlation_id=new_id(), reason="Test print",
            )
            j = jobs[0]
            return f"Test label: {j.status.value}" + (f" - {j.error_message}" if j.error_message else "")

        self._busy(True)
        self.banner.show_message("Sending test label...", "info")
        run_async(work, self._ok, self._fail)

    def _ok(self, msg: str) -> None:
        self._busy(False)
        level = "success" if "Failed" not in msg and "Unknown" not in msg else "error"
        self.banner.show_message(msg, level)

    def _fail(self, e: Exception) -> None:
        self._busy(False)
        self.banner.show_message(error_text(e), "error")

    def _save(self) -> None:
        new = copy.deepcopy(self.ctx.config)
        new["printer"] = self._form_printer()
        try:
            self._build_adapter()  # validates the selection
            self.ctx.config_service.save(new)
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        self.ctx.config = new
        self.banner.show_message("Printer settings saved.", "success")
        if self.on_saved:
            self.on_saved()
