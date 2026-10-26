"""SQLite repositories. Profiles and templates are versioned (append-only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Generic, TypeVar

from ...domain.models import DataProfile, LabelTemplate, PrintJob, PrintStatus
from .database import Database

T = TypeVar("T", DataProfile, LabelTemplate)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class _VersionedRepository(Generic[T]):
    table: str
    model: type

    def __init__(self, db: Database, username: str = "") -> None:
        self.db = db
        self.username = username

    def _load(self, row) -> T:
        obj = self.model.from_dict(json.loads(row["body"]))
        obj.version = row["version"]
        return obj

    def list_latest(self) -> list[T]:
        with self.db.connect() as c:
            rows = c.execute(
                f"SELECT t.* FROM {self.table} t JOIN (SELECT id, MAX(version) v FROM {self.table} GROUP BY id) m "
                "ON t.id = m.id AND t.version = m.v ORDER BY t.name"
            ).fetchall()
        return [self._load(r) for r in rows]

    def get(self, item_id: str, version: int | None = None) -> T | None:
        with self.db.connect() as c:
            if version is None:
                row = c.execute(
                    f"SELECT * FROM {self.table} WHERE id = ? ORDER BY version DESC LIMIT 1", (item_id,)
                ).fetchone()
            else:
                row = c.execute(f"SELECT * FROM {self.table} WHERE id = ? AND version = ?", (item_id, version)).fetchone()
        return self._load(row) if row else None

    def save(self, item: T) -> T:
        """Store as a new version; returns the item with its new version number."""
        with self.db.connect() as c:
            current = c.execute(f"SELECT MAX(version) FROM {self.table} WHERE id = ?", (item.id,)).fetchone()[0]
            item.version = (current or 0) + 1
            c.execute(
                f"INSERT INTO {self.table} (id, version, name, body, created_by) VALUES (?, ?, ?, ?, ?)",
                (item.id, item.version, item.name, json.dumps(item.to_dict(), ensure_ascii=False), self.username),
            )
        return item


class SqliteProfileRepository(_VersionedRepository[DataProfile]):
    table = "data_profiles"
    model = DataProfile


class SqliteTemplateRepository(_VersionedRepository[LabelTemplate]):
    table = "label_templates"
    model = LabelTemplate


_JOB_COLUMNS = [
    "id", "correlation_id", "parent_job_id", "document_ref", "printer_name", "adapter", "copies",
    "profile_id", "profile_version", "template_id", "template_version", "status", "username",
    "app_version", "reason", "spool_job_id", "error_code", "error_message", "created_at", "updated_at",
    "record_json",
]


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class SqlitePrintJobRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, job: PrintJob) -> None:
        now = utc_now()
        job.created_at = job.created_at or now
        job.updated_at = now
        values = [getattr(job, c) for c in _JOB_COLUMNS]
        values[_JOB_COLUMNS.index("status")] = job.status.value
        with self.db.connect() as c:
            c.execute(
                f"INSERT INTO print_jobs ({', '.join(_JOB_COLUMNS)}) VALUES ({', '.join('?' * len(_JOB_COLUMNS))})",
                values,
            )
            c.execute(
                "INSERT INTO print_events (job_id, at, status, message) VALUES (?, ?, ?, ?)",
                (job.id, now, job.status.value, job.reason),
            )

    def update_status(
        self, job_id: str, status: PrintStatus, *, message: str = "", spool_job_id: int | None = None, error_code: str = ""
    ) -> None:
        now = utc_now()
        with self.db.connect() as c:
            c.execute(
                "UPDATE print_jobs SET status = ?, updated_at = ?, spool_job_id = COALESCE(?, spool_job_id), "
                "error_code = ?, error_message = ? WHERE id = ?",
                (status.value, now, spool_job_id, error_code, message if error_code else "", job_id),
            )
            c.execute(
                "INSERT INTO print_events (job_id, at, status, message) VALUES (?, ?, ?, ?)",
                (job_id, now, status.value, message),
            )

    def correlation_exists(self, correlation_id: str) -> bool:
        with self.db.connect() as c:
            return c.execute("SELECT 1 FROM print_jobs WHERE correlation_id = ? LIMIT 1", (correlation_id,)).fetchone() is not None

    def get(self, job_id: str) -> PrintJob | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._to_job(row) if row else None

    def list_recent(self, limit: int = 500) -> list[PrintJob]:
        return self.list_filtered(limit=limit)

    def list_filtered(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        statuses: list[PrintStatus] | None = None,
        text: str = "",
        limit: int = 1000,
    ) -> list[PrintJob]:
        """Newest first. start/end are timezone-aware (end exclusive); text matches document, printer, user or reason."""
        where, params = [], []
        if start:
            where.append("created_at >= ?")
            params.append(_utc_iso(start))
        if end:
            where.append("created_at < ?")
            params.append(_utc_iso(end))
        if statuses:
            where.append(f"status IN ({', '.join('?' * len(statuses))})")
            params.extend(s.value for s in statuses)
        if text.strip():
            like = "%" + text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(
                "(document_ref LIKE ? ESCAPE '\\' OR printer_name LIKE ? ESCAPE '\\' "
                "OR username LIKE ? ESCAPE '\\' OR reason LIKE ? ESCAPE '\\')"
            )
            params.extend([like] * 4)
        sql = "SELECT * FROM print_jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with self.db.connect() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._to_job(r) for r in rows]

    def children(self, job_id: str) -> list[PrintJob]:
        """Reprints made from this job."""
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM print_jobs WHERE parent_job_id = ? ORDER BY created_at", (job_id,)).fetchall()
        return [self._to_job(r) for r in rows]

    def events(self, job_id: str) -> list[tuple[str, str, str]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT at, status, message FROM print_events WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        return [(r["at"], r["status"], r["message"]) for r in rows]

    @staticmethod
    def _to_job(row) -> PrintJob:
        d = {c: row[c] for c in _JOB_COLUMNS}
        d["status"] = PrintStatus(d["status"])
        return PrintJob(**d)
