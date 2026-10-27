"""Composition root: builds services from configuration. UI code only talks to this."""
from __future__ import annotations

import logging
from typing import Any

from .. import __version__
from ..domain.errors import PrinterError
from ..infrastructure.ax.mock_source import MockDataSource
from ..infrastructure.ax.sql_server import SqlServerDataSource
from ..infrastructure.config import ConfigurationService
from ..infrastructure.printing.adapters import (
    MockPrinterAdapter,
    TcpPrinterAdapter,
    WindowsSharedPrinterAdapter,
    WindowsSpoolerAdapter,
)
from ..infrastructure.storage.database import Database
from ..infrastructure.storage.repositories import (
    SqlitePrintJobRepository,
    SqliteProfileRepository,
    SqliteTemplateRepository,
)
from ..services.admin_auth import AdminAuth
from ..services.print_service import PrintService
from ..services.qr_payload import QrPayloadBuilder
from . import paths
from .defaults import bundled_templates, default_asset_profile, default_asset_template

log = logging.getLogger(__name__)


class AppContext:
    def __init__(self) -> None:
        self.version = __version__
        self.config_service = ConfigurationService(paths.config_path())
        self.first_run = not paths.config_path().exists()  # no settings saved yet -> show setup wizard
        self.config: dict[str, Any] = self.config_service.load()
        self.db = Database(paths.database_path())
        self.profiles = SqliteProfileRepository(self.db)
        self.templates = SqliteTemplateRepository(self.db)
        self.jobs = SqlitePrintJobRepository(self.db)
        self.payloads = QrPayloadBuilder()
        self.print_service = PrintService(
            self.jobs, __version__, payload_builder=self.payloads, profiles=self.profiles, templates=self.templates
        )
        self.admin = AdminAuth(lambda: self.config, self.save_config)
        self._seed()

    def _seed(self) -> None:
        """First run: install the label templates shipped with the app and the Asset data profile."""
        default_template_id = ""
        if not self.templates.list_latest():
            bundled, default_template_id = bundled_templates()
            for t in bundled:
                self.templates.save(t)
                log.info("Installed bundled label template '%s' (%s)", t.name, t.id)
            if not bundled:
                self.templates.save(default_asset_template())
                log.info("Seeded SAMPLE label template")
        if not self.profiles.list_latest():
            profile = default_asset_profile()
            if default_template_id:
                profile.template_id = default_template_id
            self.profiles.save(profile)
            log.info("Seeded default Asset data profile (template %s)", profile.template_id)

    def save_config(self) -> None:
        self.config_service.save(self.config)

    @property
    def using_mock_data(self) -> bool:
        return bool(self.config["database"]["use_mock"])

    def data_source(self):
        approved = self.config["approved_sources"]
        if self.using_mock_data:
            return MockDataSource(approved)
        return SqlServerDataSource(
            self.config["database"], lambda: self.config_service.get_password(self.config), approved
        )

    @staticmethod
    def queue_adapter_for(job):
        """Adapter that can inspect the Windows queue a past job was sent to (None for TCP / sample printer)."""
        if job.adapter == "spooler":
            return WindowsSpoolerAdapter(job.printer_name)
        if job.adapter == "shared":
            return WindowsSharedPrinterAdapter(job.printer_name)
        return None

    def printer_adapter(self):
        p = self.config["printer"]
        kind = p["adapter"]
        if kind == "spooler":
            return WindowsSpoolerAdapter(p.get("printer_name", ""))
        if kind == "shared":
            return WindowsSharedPrinterAdapter(p.get("shared_path", ""))
        if kind == "tcp":
            return TcpPrinterAdapter(p.get("tcp_host", ""), p.get("tcp_port", 9100))
        if kind == "mock":
            return MockPrinterAdapter(paths.mock_output_dir())
        raise PrinterError(f"Unknown printer adapter '{kind}'.")
