"""JSON configuration with schema validation, migration and atomic writes.

Secrets are never stored in plaintext: the SQL password is kept as a DPAPI blob.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema

from ..domain.errors import ValidationError
from .security import dpapi

log = logging.getLogger(__name__)

CONFIG_VERSION = 2

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "database": {
        "use_mock": True,
        "server": "",
        "database": "",
        "driver": "ODBC Driver 17 for SQL Server",
        "auth": "sql",  # sql | windows
        "username": "",
        "password_dpapi": "",
        "encrypt": False,
        "trust_server_certificate": True,
        "connect_timeout": 10,
        "query_timeout": 30,
        "company": "",
    },
    "approved_sources": ["AssetTable", "AssetBook"],
    "printer": {
        "adapter": "mock",  # mock | spooler | shared | tcp
        "printer_name": "",
        "shared_path": "",
        "tcp_host": "",
        "tcp_port": 9100,
    },
    "ui": {
        "last_profile_id": "",
        "last_template_id": "",
        "copies": 1,
    },
    "admin": {
        "password_hash": "",  # empty = built-in initial password (see services.admin_auth)
    },
    # Parts of the program (app.modules); "install_modules" = last choice taken over from the installer
    "modules": ["asset", "journal"],
    "install_modules": [],
    # Menus by Active Directory group of the Windows user (see services.access)
    "access": {
        "admin_groups": ["ICT-RY"],  # see every menu, no admin password needed
        "user_menus": ["search", "history", "printer"],  # everyone else
    },
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["config_version", "database", "approved_sources", "printer", "ui"],
    "properties": {
        "config_version": {"type": "integer", "minimum": 1},
        "database": {
            "type": "object",
            "required": ["use_mock", "server", "database", "driver", "auth", "username", "password_dpapi"],
            "properties": {
                "use_mock": {"type": "boolean"},
                "server": {"type": "string", "maxLength": 256},
                "database": {"type": "string", "maxLength": 128},
                "driver": {"type": "string", "maxLength": 128},
                "auth": {"enum": ["sql", "windows"]},
                "username": {"type": "string", "maxLength": 128},
                "password_dpapi": {"type": "string"},
                "encrypt": {"type": "boolean"},
                "trust_server_certificate": {"type": "boolean"},
                "connect_timeout": {"type": "integer", "minimum": 1, "maximum": 120},
                "query_timeout": {"type": "integer", "minimum": 1, "maximum": 600},
                "company": {"type": "string", "maxLength": 8},
            },
        },
        "approved_sources": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]{0,127}$"},
        },
        "printer": {
            "type": "object",
            "required": ["adapter"],
            "properties": {
                "adapter": {"enum": ["mock", "spooler", "shared", "tcp"]},
                "printer_name": {"type": "string"},
                "shared_path": {"type": "string"},
                "tcp_host": {"type": "string"},
                "tcp_port": {"type": "integer", "minimum": 1, "maximum": 65535},
            },
        },
        "ui": {"type": "object"},
        "admin": {
            "type": "object",
            "properties": {"password_hash": {"type": "string", "maxLength": 300}},
        },
        "modules": {"type": "array", "items": {"enum": ["asset", "journal"]}},
        "install_modules": {"type": "array", "items": {"enum": ["asset", "journal"]}},
        "access": {
            "type": "object",
            "properties": {
                "admin_groups": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 256}},
                "user_menus": {"type": "array", "items": {"type": "string", "maxLength": 40}},
            },
        },
    },
}

def _v1_to_v2(config: dict[str, Any]) -> dict[str, Any]:
    """AssetBook (PO, department, acquisition data) is read together with AssetTable."""
    sources = config.setdefault("approved_sources", ["AssetTable"])
    upper = {s.upper() for s in sources}
    if "ASSETTABLE" in upper and "ASSETBOOK" not in upper:
        sources.append("AssetBook")
    return config


# version N -> function that upgrades a config dict from N to N+1
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _v1_to_v2}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ConfigurationService:
    def __init__(self, path: Path, protect=dpapi.protect, unprotect=dpapi.unprotect) -> None:
        self.path = path
        self._protect = protect
        self._unprotect = unprotect

    @staticmethod
    def validate(config: dict[str, Any]) -> None:
        try:
            jsonschema.validate(config, SCHEMA)
        except jsonschema.ValidationError as e:
            where = "/".join(str(p) for p in e.absolute_path) or "(root)"
            raise ValidationError(f"Invalid configuration at {where}: {e.message}") from None

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_CONFIG)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            config = self._migrate(raw)
            config = _deep_merge(DEFAULT_CONFIG, config)
            self.validate(config)
            return config
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            bad = self.path.with_name(f"{self.path.name}.invalid-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(self.path, bad)
            log.warning("Config unreadable (%s); kept a copy at %s and using defaults", e, bad)
            return copy.deepcopy(DEFAULT_CONFIG)

    def _migrate(self, config: dict[str, Any]) -> dict[str, Any]:
        version = int(config.get("config_version", 1))
        if version > CONFIG_VERSION:
            raise ValidationError(f"Config version {version} is newer than this application supports.")
        if version < CONFIG_VERSION:
            backup = self.path.with_name(f"{self.path.name}.bak-v{version}")
            shutil.copy2(self.path, backup)
            while version < CONFIG_VERSION:
                config = MIGRATIONS[version](config)
                version += 1
                config["config_version"] = version
        return config

    def save(self, config: dict[str, Any]) -> None:
        self.validate(config)
        atomic_write_text(self.path, json.dumps(config, indent=2, ensure_ascii=False))

    def set_password(self, config: dict[str, Any], password: str) -> None:
        config["database"]["password_dpapi"] = self._protect(password) if password else ""

    def get_password(self, config: dict[str, Any]) -> str:
        return self._unprotect(config["database"].get("password_dpapi", ""))

    # Safe import/export: secrets are never exported.
    def export_config(self, config: dict[str, Any], target: Path) -> None:
        clean = copy.deepcopy(config)
        clean["database"]["password_dpapi"] = ""
        clean.pop("admin", None)
        atomic_write_text(target, json.dumps(clean, indent=2, ensure_ascii=False))

    def import_config(self, source: Path) -> dict[str, Any]:
        data = json.loads(source.read_text(encoding="utf-8"))
        data.get("database", {}).pop("password_dpapi", None)
        data.pop("admin", None)  # never take an admin password from an imported file
        merged = _deep_merge(DEFAULT_CONFIG, data)
        merged["config_version"] = CONFIG_VERSION
        self.validate(merged)
        return merged
