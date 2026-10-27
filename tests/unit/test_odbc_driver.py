"""PCs without "ODBC Driver 17 for SQL Server" fall back to an installed driver (Windows always has "SQL Server")."""
import pytest

from qrlabel.infrastructure.ax import sql_server
from qrlabel.infrastructure.ax.sql_server import AUTO_DRIVER, SqlServerDataSource, choose_driver

WINDOWS_ONLY = ["SQL Server"]  # a fresh Windows PC
DEV_PC = ["SQL Server", "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]


@pytest.mark.parametrize("configured, installed, expected", [
    ("ODBC Driver 17 for SQL Server", DEV_PC, "ODBC Driver 17 for SQL Server"),  # installed: keep it
    ("ODBC Driver 17 for SQL Server", WINDOWS_ONLY, "SQL Server"),  # the reported problem
    (AUTO_DRIVER, DEV_PC, "ODBC Driver 18 for SQL Server"),  # automatic: newest
    (AUTO_DRIVER, WINDOWS_ONLY, "SQL Server"),
    ("ODBC Driver 17 for SQL Server", ["SQL Server Native Client 11.0", "SQL Server"], "SQL Server Native Client 11.0"),
    ("Some Vendor SQL Server Driver", ["Some Vendor SQL Server Driver"], "Some Vendor SQL Server Driver"),
    (AUTO_DRIVER, [], "SQL Server"),  # nothing found (pyodbc failed): still try the built-in one
])
def test_choose_driver(configured, installed, expected):
    assert choose_driver(configured, installed) == expected


def _source(driver, monkeypatch, installed):
    monkeypatch.setattr(sql_server, "installed_sql_drivers", lambda: installed)
    settings = {"server": "NCR612", "database": "AX40DB_SP1", "driver": driver, "auth": "sql",
                "username": "reader", "encrypt": False, "trust_server_certificate": True}
    return SqlServerDataSource(settings, lambda: "secret", ["AssetTable"])


def test_connection_string_uses_installed_driver(monkeypatch):
    src = _source("ODBC Driver 17 for SQL Server", monkeypatch, WINDOWS_ONLY)
    cs = src.connection_string(include_secret=False)
    assert cs.startswith("DRIVER={SQL Server};") and "PWD=***" in cs and "secret" not in cs
    assert src.s["driver"] == "ODBC Driver 17 for SQL Server"  # the setting itself is not changed


def test_new_config_uses_automatic(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext

    assert AppContext().config["database"]["driver"] == AUTO_DRIVER


def test_driver_combo(monkeypatch):
    from PySide6.QtWidgets import QApplication, QComboBox

    QApplication.instance() or QApplication([])
    from qrlabel.ui.pages import settings_page

    monkeypatch.setattr(settings_page, "installed_sql_drivers", lambda: WINDOWS_ONLY)
    monkeypatch.setattr(sql_server, "installed_sql_drivers", lambda: WINDOWS_ONLY)
    combo = QComboBox()
    combo.setEditable(True)
    settings_page.fill_driver_combo(combo, "ODBC Driver 17 for SQL Server")  # not on this PC
    assert combo.currentText() == settings_page.AUTO_LABEL and settings_page.driver_from_combo(combo) == AUTO_DRIVER
    assert "In use now: SQL Server" in combo.toolTip()
    combo.setCurrentIndex(combo.findData("SQL Server"))
    assert settings_page.driver_from_combo(combo) == "SQL Server"
