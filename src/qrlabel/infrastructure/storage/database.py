"""Local SQLite database (profiles, templates, print history).

A new connection is opened per unit of work so worker threads never share one.
"""
from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE data_profiles (
        id TEXT NOT NULL,
        version INTEGER NOT NULL,
        name TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        created_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id, version)
    );
    CREATE TABLE label_templates (
        id TEXT NOT NULL,
        version INTEGER NOT NULL,
        name TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        created_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id, version)
    );
    CREATE TABLE print_jobs (
        id TEXT PRIMARY KEY,
        correlation_id TEXT NOT NULL,
        parent_job_id TEXT NOT NULL DEFAULT '',
        document_ref TEXT NOT NULL,
        printer_name TEXT NOT NULL,
        adapter TEXT NOT NULL,
        copies INTEGER NOT NULL,
        profile_id TEXT NOT NULL,
        profile_version INTEGER NOT NULL,
        template_id TEXT NOT NULL,
        template_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        username TEXT NOT NULL,
        app_version TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        spool_job_id INTEGER,
        error_code TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX ix_print_jobs_created ON print_jobs(created_at);
    CREATE INDEX ix_print_jobs_correlation ON print_jobs(correlation_id);
    CREATE TABLE print_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL REFERENCES print_jobs(id),
        at TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT ''
    );
    """,
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= SCHEMA_VERSION:
            return
        if current > 0 and self.path.exists():
            shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak-v{current}"))
        for version in range(current + 1, SCHEMA_VERSION + 1):
            with self.connect() as conn:
                conn.executescript("BEGIN;" + _MIGRATIONS[version] + f"PRAGMA user_version = {version}; COMMIT;")
