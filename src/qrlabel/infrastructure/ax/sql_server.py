"""Read-only access to the Dynamics AX 4.0 SQL Server database via pyodbc.

Only SELECT statements compiled by services.query_builder are executed, with all
values bound as parameters. Use a SQL login that has db_datareader only.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from ...domain.errors import DataSourceError, ValidationError
from ...domain.models import DataProfile
from ...services.query_builder import VIRTUAL_COMPANY_SQL, build_select, quote_ident, uses_virtual_company

log = logging.getLogger(__name__)

# SQLSTATE -> operator-friendly message
_FRIENDLY = {
    "28000": "Login failed. Check the SQL user name and password.",
    "08001": "Cannot reach the SQL Server. Check the server name, network and firewall.",
    "08S01": "The connection to SQL Server was lost.",
    "HYT00": "The database did not respond in time (timeout).",
    "HYT01": "Connecting to the database timed out.",
    "42S02": "The table or view does not exist, or the login cannot read it.",
    "42S22": "A configured column does not exist in the table.",
    "42000": "The database refused the request (permission or syntax).",
    "IM002": "No SQL Server ODBC driver could be used on this computer. Install 'ODBC Driver 17 for SQL Server' "
             "(or newer) from Microsoft, or ask ICT.",
}


# Best first. "SQL Server" is built into every Windows, so there is always one to fall back to;
# it was checked against the AX database (assets, journal, Thai text, companies) with the same results.
PREFERRED_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13.1 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "ODBC Driver 11 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server Native Client 10.0",
    "SQL Server",
]
AUTO_DRIVER = ""  # settings value meaning "best installed driver"


def installed_sql_drivers() -> list[str]:
    try:
        import pyodbc

        return [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:
        return []


def choose_driver(configured: str, installed: list[str] | None = None) -> str:
    """The configured driver when it is installed, otherwise the best installed one.

    A PC without "ODBC Driver 17" (the old default) then still connects, e.g. with the built-in
    "SQL Server" driver, instead of failing with "driver not installed".
    """
    installed = installed_sql_drivers() if installed is None else installed
    configured = (configured or "").strip()
    if configured and configured in installed:
        return configured
    for name in PREFERRED_DRIVERS:
        if name in installed:
            return name
    if installed:
        return installed[0]
    return configured or "SQL Server"


def _odbc_value(value: str) -> str:
    """Brace-quote a connection-string value so ; and = cannot inject options."""
    return "{" + value.replace("}", "}}") + "}"


def friendly_error(exc: Exception) -> DataSourceError:
    state = exc.args[0] if getattr(exc, "args", None) else ""
    detail = str(exc.args[1]) if len(getattr(exc, "args", ())) > 1 else str(exc)
    msg = _FRIENDLY.get(str(state), "Database error. See the log for details.")
    return DataSourceError(msg, code=f"SQL-{state or 'ERR'}", detail=detail)


class SqlServerDataSource:
    kind = "sqlserver"

    def __init__(self, settings: dict[str, Any], password_provider: Callable[[], str], approved_sources: list[str]) -> None:
        self.s = settings
        self._password = password_provider
        self.approved_sources = approved_sources
        self._columns_cache: dict[tuple[str, str], list[tuple[str, str]]] = {}

    @property
    def driver(self) -> str:
        chosen = choose_driver(self.s.get("driver", AUTO_DRIVER))
        if chosen != (self.s.get("driver") or "") and not getattr(self, "_driver_logged", False):
            log.info("ODBC driver '%s' is not installed; using '%s'", self.s.get("driver") or "(automatic)", chosen)
            self._driver_logged = True
        return chosen

    def connection_string(self, include_secret: bool = True) -> str:
        s = self.s
        if not s.get("server") or not s.get("database"):
            raise ValidationError("SQL Server name and database are required.")
        parts = [
            f"DRIVER={_odbc_value(self.driver)}",
            f"SERVER={_odbc_value(s['server'])}",
            f"DATABASE={_odbc_value(s['database'])}",
            "APP=NCR Print Label",
            "ApplicationIntent=ReadOnly",
        ]
        if s.get("auth") == "windows":
            parts.append("Trusted_Connection=yes")
        else:
            if not s.get("username"):
                raise ValidationError("SQL user name is required for SQL Authentication.")
            parts.append(f"UID={_odbc_value(s['username'])}")
            parts.append(f"PWD={_odbc_value(self._password()) if include_secret else '***'}")
        parts.append(f"Encrypt={'yes' if s.get('encrypt') else 'no'}")
        if s.get("trust_server_certificate", True):
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts)

    @contextmanager
    def _connect(self):
        import pyodbc

        try:
            conn = pyodbc.connect(
                self.connection_string(),
                timeout=int(self.s.get("connect_timeout", 10)),
                autocommit=True,
                readonly=True,
            )
        except pyodbc.Error as e:
            err = friendly_error(e)
            log.warning("AX connect failed code=%s detail=%s", err.code, err.detail)
            raise err from None
        try:
            conn.timeout = int(self.s.get("query_timeout", 30))
            yield conn
        except pyodbc.Error as e:
            err = friendly_error(e)
            log.warning("AX query failed code=%s detail=%s", err.code, err.detail)
            raise err from None
        finally:
            conn.close()

    def test_connection(self) -> str:
        with self._connect() as conn:
            row = conn.cursor().execute("SELECT @@SERVERNAME, DB_NAME(), SERVERPROPERTY('ProductVersion')").fetchone()
        return f"Connected to {row[0]} / {row[1]} (SQL Server {row[2]}) using '{self.driver}'"

    def list_sources(self) -> list[tuple[str, str, str]]:
        """All tables and views the login can see: (schema, name, 'TABLE' | 'VIEW'). Metadata only."""
        with self._connect() as conn:
            rows = conn.cursor().execute(
                "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                "ORDER BY TABLE_NAME"
            ).fetchall()
        return [(r[0], r[1], "VIEW" if r[2] == "VIEW" else "TABLE") for r in rows]

    def list_companies(self, profile: DataProfile | None = None) -> list[tuple[str, str, int | None]]:
        """Companies (DATAAREAID, name, rows in the profile's source). Virtual companies are left out."""
        names: dict[str, str] = {}
        counts: dict[str, int] = {}
        with self._connect() as conn:
            cur = conn.cursor()
            try:  # AX system table with company names (fixed read-only query, no user input)
                for cid, name in cur.execute("SELECT ID, NAME FROM dbo.DATAAREA WHERE ISVIRTUAL = 0 ORDER BY ID").fetchall():
                    names[str(cid).strip().lower()] = str(name or "").strip()
            except Exception as e:  # not an AX database or no read right: counts are enough
                log.info("DATAAREA not readable: %s", e)
            if profile is not None and profile.dataarea_column:
                if profile.source.upper() not in {s.upper() for s in self.approved_sources}:
                    raise ValidationError(f"Source '{profile.source}' is not in the approved source list.")
                col = quote_ident(profile.dataarea_column)
                sql = f"SELECT {col}, COUNT(*) FROM {quote_ident(profile.schema)}.{quote_ident(profile.source)} GROUP BY {col}"
                for cid, n in cur.execute(sql).fetchall():
                    counts[str(cid).strip().lower()] = int(n)
        ids = sorted(set(names) | set(counts))
        with_counts = profile is not None and bool(profile.dataarea_column)
        return [(cid, names.get(cid, ""), counts.get(cid, 0) if with_counts else None) for cid in ids]

    def forget_columns(self) -> None:
        self._columns_cache.clear()

    def list_columns(self, source: str, schema: str = "dbo") -> list[tuple[str, str]]:
        if source.upper() not in {s.upper() for s in self.approved_sources}:
            raise ValidationError(f"Source '{source}' is not in the approved source list.")
        key = (schema.upper(), source.upper())
        if key not in self._columns_cache:
            with self._connect() as conn:
                rows = conn.cursor().execute(
                    "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                    schema, source,
                ).fetchall()
            if not rows:
                raise DataSourceError(f"No columns found for {schema}.{source}. Check the name and read permission.")
            self._columns_cache[key] = [(r[0], r[1]) for r in rows]
        return self._columns_cache[key]

    def search(self, profile: DataProfile, criteria: dict[str, str], company: str, ranges=None) -> list[dict[str, Any]]:
        allowed = {profile.source: [c for c, _ in self.list_columns(profile.source, profile.schema)]}
        for lk in profile.lookups:
            allowed[lk.table] = [c for c, _ in self.list_columns(lk.table, lk.schema)]
        with self._connect() as conn:
            cur = conn.cursor()
            virtual = None
            if uses_virtual_company(profile):  # e.g. DB1 -> VIR for InventDim / InventTable
                row = cur.execute(VIRTUAL_COMPANY_SQL, (company or "").strip()).fetchone()
                virtual = row[0] if row else None
            sql, params = build_select(
                profile, criteria, company, approved_sources=self.approved_sources, allowed_columns=allowed,
                ranges=ranges, virtual_company=virtual,
            )
            cur.execute(sql, *params)
            names = [d[0].upper() for d in cur.description]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
        log.info("AX search profile=%s v%s rows=%d", profile.id, profile.version, len(rows))
        return rows
