"""Rotating, structured log file. Never log passwords or connection strings."""
from __future__ import annotations

import getpass
import logging
import logging.handlers
from pathlib import Path

from .. import __version__


class _ContextFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        try:
            self.user = getpass.getuser()
        except Exception:
            self.user = "unknown"

    def filter(self, record: logging.LogRecord) -> bool:
        record.user = self.user
        record.app_version = __version__
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_file = log_dir / "qrlabel.log"
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=10, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | v%(app_version)s | user=%(user)s | %(name)s | %(message)s"
    ))
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return log_file
