"""Per-user data locations under %LOCALAPPDATA%\\NCR\\QRLabelPrinter."""
from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    override = os.environ.get("QRLABEL_DATA_DIR")  # used by tests / portable runs
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "NCR" / "QRLabelPrinter"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return app_data_dir() / "config.json"


def database_path() -> Path:
    return app_data_dir() / "qrlabel.sqlite3"


def log_dir() -> Path:
    p = app_data_dir() / "logs"
    p.mkdir(exist_ok=True)
    return p


def mock_output_dir() -> Path:
    return app_data_dir() / "mock_prints"


def resource_path(name: str) -> Path:
    """File shipped with the app (works from source and from the PyInstaller build)."""
    return Path(__file__).resolve().parents[1] / "resources" / name
