"""Compile a Data Profile + operator criteria into a safe, read-only SELECT.

Identifiers are validated against a strict pattern and (when known) against the
columns discovered from the database. All values are bound as parameters.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

DateRange = tuple[date | None, date | None]

from ..domain.errors import ValidationError
from ..domain.models import DataProfile

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
HARD_ROW_LIMIT = 5000
MAX_CRITERIA_LENGTH = 100


def quote_ident(name: str) -> str:
    if not isinstance(name, str) or not IDENT_RE.match(name):
        raise ValidationError(f"Invalid identifier: {name!r}")
    return f"[{name}]"


def escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("[", "\\[")
    )


def check_range_field(profile: DataProfile, column: str):
    fd = profile.get_field(column)
    if fd is None or not fd.range_search or fd.data_type != "date":
        raise ValidationError(f"Field '{column}' does not allow date-range search in this profile.")
    return fd


def in_range(value: Any, rng: DateRange) -> bool:
    """Python equivalent of the SQL range filter (used by the sample data source)."""
    start, end = rng
    if value is None:
        return start is None and end is None
    d = value.date() if isinstance(value, datetime) else value
    return (start is None or d >= start) and (end is None or d <= end)


def build_select(
    profile: DataProfile,
    criteria: dict[str, str],
    company: str,
    *,
    approved_sources: Iterable[str],
    allowed_columns: Iterable[str] | None = None,
    ranges: dict[str, DateRange] | None = None,
) -> tuple[str, list[Any]]:
    approved = {s.upper() for s in approved_sources}
    if profile.source.upper() not in approved:
        raise ValidationError(f"Source '{profile.source}' is not in the approved source list.")

    allowed = {c.upper() for c in allowed_columns} if allowed_columns is not None else None

    def check_col(col: str) -> str:
        q = quote_ident(col)
        if allowed is not None and col.upper() not in allowed:
            raise ValidationError(f"Column '{col}' does not exist in {profile.source}.")
        return q

    if not profile.fields:
        raise ValidationError("Data profile has no fields.")

    select_cols = [check_col(f.column) for f in profile.fields]
    where: list[str] = []
    params: list[Any] = []

    if profile.dataarea_column:
        company = (company or "").strip()
        if not company:
            raise ValidationError("Company (DATAAREAID) is required for this profile.")
        if len(company) > 8:
            raise ValidationError("Company (DATAAREAID) is too long.")
        where.append(f"{check_col(profile.dataarea_column)} = ?")
        params.append(company)

    for column, text in criteria.items():
        text = (text or "").strip()
        if not text:
            continue
        fd = profile.get_field(column)
        if fd is None or not fd.searchable:
            raise ValidationError(f"Field '{column}' is not searchable in this profile.")
        if len(text) > MAX_CRITERIA_LENGTH:
            raise ValidationError(f"Search text for '{fd.label}' is too long.")
        where.append(f"{check_col(fd.column)} LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(text)}%")

    for column, (start, end) in (ranges or {}).items():
        if start is None and end is None:
            continue
        fd = check_range_field(profile, column)
        q = check_col(fd.column)
        if start and end and start > end:
            raise ValidationError(f"{fd.label}: 'From' date is after 'To' date.")
        if start:
            where.append(f"{q} >= ?")
            params.append(datetime.combine(start, time.min))
        if end:  # inclusive: everything before the next day
            where.append(f"{q} < ?")
            params.append(datetime.combine(end + timedelta(days=1), time.min))

    order_cols = profile.order_by or [profile.fields[0].column]
    order_sql = ", ".join(check_col(c) for c in order_cols)

    limit = int(profile.row_limit)
    if not 1 <= limit <= HARD_ROW_LIMIT:
        raise ValidationError(f"Row limit must be between 1 and {HARD_ROW_LIMIT}.")

    sql = (
        f"SELECT TOP ({limit}) {', '.join(select_cols)} "
        f"FROM {quote_ident(profile.schema)}.{quote_ident(profile.source)}"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_sql}"
    return sql, params
