"""Compile a Data Profile + operator criteria into a safe, read-only SELECT.

Identifiers are validated against a strict pattern and (when known) against the
columns discovered from the database. All values are bound as parameters.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

DateRange = tuple[date | None, date | None]

from ..domain.errors import ValidationError
from ..domain.models import DataProfile

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
HARD_ROW_LIMIT = 5000
MAX_CRITERIA_LENGTH = 5000  # whole search box (lists pasted from Excel can be long)
MAX_TERM_LENGTH = 100
MAX_TERMS = 200

_SPLIT_RE = re.compile(r"[,;\r\n\t]+")
_RANGE_RE = re.compile(r"\s*\.{2,}\s*")


@dataclass(frozen=True)
class TextFilter:
    """Parsed search box.

    "abc"            -> contains "abc" (or starts with / equals it, depending on the field's search mode)
    "A..B"           -> A <= value <= B
    "A, B; C" / lines -> exact values (each piece may also be a range)
    """

    contains: str | None = None
    prefix: str | None = None
    exact: tuple[str, ...] = ()
    ranges: tuple[tuple[str, str], ...] = ()

    def matches(self, value: Any) -> bool:
        """Python equivalent of the SQL filter (case-insensitive, like the AX collation)."""
        v = str(value if value is not None else "").strip().upper()
        if self.contains is not None:
            return self.contains.upper() in v
        if self.prefix is not None:
            return v.startswith(self.prefix.upper())
        if v in {e.upper() for e in self.exact}:
            return True
        return any(a.upper() <= v <= b.upper() for a, b in self.ranges)


SEARCH_MODES = {"contains": "Contains", "starts": "Starts with", "exact": "Exact"}


def parse_text_filter(text: str, label: str = "Search", mode: str = "contains") -> TextFilter | None:
    if mode not in SEARCH_MODES:
        raise ValidationError(f"'{label}': unknown search mode {mode!r}.")
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > MAX_CRITERIA_LENGTH:
        raise ValidationError(f"Search text for '{label}' is too long.")
    pieces = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if len(pieces) > MAX_TERMS:
        raise ValidationError(f"'{label}': at most {MAX_TERMS} values can be searched at once.")
    exact: list[str] = []
    ranges: list[tuple[str, str]] = []
    for p in pieces:
        if len(p) > MAX_TERM_LENGTH:
            raise ValidationError(f"'{label}': value '{p[:20]}...' is too long.")
        if _RANGE_RE.search(p):
            parts = _RANGE_RE.split(p)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValidationError(f"'{label}': a range must look like FROM..TO (got '{p}').")
            a, b = parts
            if a.upper() > b.upper():
                a, b = b, a
            ranges.append((a, b))
        else:
            exact.append(p)
    if len(pieces) == 1 and exact and mode == "contains":
        return TextFilter(contains=exact[0])
    if len(pieces) == 1 and exact and mode == "starts":
        return TextFilter(prefix=exact[0])
    return TextFilter(exact=tuple(dict.fromkeys(exact)), ranges=tuple(ranges))


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


VIRTUAL_COMPANY = "@VIRTUAL"
MAX_FIXED_VALUE = 60


def fixed_pairs(pairs, label: str) -> list[tuple[str, str]]:
    """[[COLUMN, value], ...] -> validated (COLUMN, value); value is always bound as a parameter."""
    out = []
    for pair in pairs or []:
        if len(pair) != 2:
            raise ValidationError(f"{label}: each fixed value needs a column and a value.")
        col, value = str(pair[0]).strip(), str(pair[1]).strip()
        quote_ident(col)
        if not value or len(value) > MAX_FIXED_VALUE:
            raise ValidationError(f"{label}: value for {col} must be 1-{MAX_FIXED_VALUE} characters.")
        out.append((col, value))
    return out


def parse_pairs(text: str, label: str = "Fixed values") -> list[list[str]]:
    """'MODULETYPE=0, DATAAREAID=@VIRTUAL' -> [["MODULETYPE", "0"], ["DATAAREAID", "@VIRTUAL"]]."""
    out = []
    for part in [p.strip() for p in (text or "").split(",") if p.strip()]:
        if "=" not in part:
            raise ValidationError(f"{label}: '{part}' must look like COLUMN=value.")
        col, value = (x.strip() for x in part.split("=", 1))
        out.append([col.upper(), value.upper() if value.upper() == VIRTUAL_COMPANY else value])
    fixed_pairs(out, label)
    return out


def format_pairs(pairs) -> str:
    return ", ".join(f"{c}={v}" for c, v in pairs or [])


def parse_replace(rule: str) -> list[tuple[str, str]]:
    """'+>_ ;>,' -> [('+', '_'), (';', ',')]. Each part is FROM>TO, separated by spaces."""
    out = []
    for part in (rule or "").split():
        if part.count(">") != 1 or part.startswith(">"):
            raise ValidationError(f"Replace '{part}' must look like FROM>TO, e.g. +>_")
        a, b = part.split(">")
        out.append((a, b))
    return out


def apply_replace(text: str, rule: str) -> str:
    for a, b in parse_replace(rule):
        text = text.replace(a, b)
    return text


def uses_virtual_company(profile: DataProfile) -> bool:
    return any(str(v).strip().upper() == VIRTUAL_COMPANY for lk in profile.lookups for _, v in (lk.conditions or []))


VIRTUAL_COMPANY_SQL = (
    "SELECT TOP 1 VIRTUALDATAAREA FROM [dbo].[VIRTUALDATAAREALIST] WHERE ID = ? ORDER BY VIRTUALDATAAREA"
)


def has_criteria(criteria: dict[str, str] | None, ranges: dict[str, DateRange] | None = None) -> bool:
    return any((t or "").strip() for t in (criteria or {}).values()) or any(
        a is not None or b is not None for a, b in (ranges or {}).values()
    )


def check_required_criteria(profile: DataProfile, criteria, ranges=None) -> None:
    if profile.require_criteria and not has_criteria(criteria, ranges):
        names = ", ".join(f.label for f in profile.searchable_fields + profile.range_fields) or "a search box"
        raise ValidationError(f"Enter at least one search value ({names}).")


def in_range(value: Any, rng: DateRange) -> bool:
    """Python equivalent of the SQL range filter (used by the sample data source)."""
    start, end = rng
    if value is None:
        return start is None and end is None
    d = value.date() if isinstance(value, datetime) else value
    return (start is None or d >= start) and (end is None or d <= end)


def split_ref(ref: str) -> tuple[str, str]:
    """'TABLE.COLUMN' -> (TABLE, COLUMN); 'COLUMN' -> ('', COLUMN) meaning the main source."""
    parts = ref.split(".")
    if len(parts) == 1:
        return "", parts[0]
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValidationError(f"Invalid column reference: {ref!r}")


def split_order(entry: str) -> tuple[str, str]:
    parts = entry.split()
    if len(parts) == 1:
        return parts[0], "ASC"
    if len(parts) == 2 and parts[1].upper() in ("ASC", "DESC"):
        return parts[0], parts[1].upper()
    raise ValidationError(f"Invalid sort entry: {entry!r}")


def build_select(
    profile: DataProfile,
    criteria: dict[str, str],
    company: str,
    *,
    approved_sources: Iterable[str],
    allowed_columns: dict[str, Iterable[str]] | Iterable[str] | None = None,
    ranges: dict[str, DateRange] | None = None,
    virtual_company: str | None = None,
) -> tuple[str, list[Any]]:
    """allowed_columns: {table: columns} discovered from the database (or just the main table's columns).

    virtual_company: AX virtual company of `company` (DB1 -> VIR), used for @VIRTUAL; the data source
    looks it up first (see uses_virtual_company). None = the company itself.
    """
    approved = {s.upper() for s in approved_sources}
    main = profile.source.upper()
    if main not in approved:
        raise ValidationError(f"Source '{profile.source}' is not in the approved source list.")

    aliases = {main: "a"}
    for i, lk in enumerate(profile.lookups, start=1):
        t = lk.table.upper()
        if t not in approved:
            raise ValidationError(f"Related table '{lk.table}' is not in the approved source list.")
        if t in aliases:
            raise ValidationError(f"Table '{lk.table}' is used twice in the data profile.")
        aliases[t] = f"l{i}"

    if allowed_columns is None:
        allowed = None
    elif isinstance(allowed_columns, dict):
        allowed = {k.upper(): {c.upper() for c in v} for k, v in allowed_columns.items()}
    else:
        allowed = {main: {c.upper() for c in allowed_columns}}

    used: dict[str, set[str]] = {t: set() for t in aliases}  # columns each lookup must return

    def col_ref(table: str, col: str) -> str:
        t = (table or profile.source).upper()
        if t not in aliases:
            raise ValidationError(f"Table '{table}' is not part of this data profile.")
        q = quote_ident(col)
        if allowed is not None and t in allowed and col.upper() not in allowed[t]:
            raise ValidationError(f"Column '{col}' does not exist in {table or profile.source}.")
        used[t].add(col.upper())
        return f"{aliases[t]}.{q}"

    def expr(fd) -> str:
        base = col_ref(fd.table, fd.source)
        if fd.fallback:
            ft, fc = split_ref(fd.fallback)
            return f"COALESCE(NULLIF({base}, ''), {col_ref(ft, fc)})"
        return base

    if not profile.fields:
        raise ValidationError("Data profile has no fields.")
    keys = [f.column.upper() for f in profile.fields]
    if len(keys) != len(set(keys)):
        raise ValidationError("Two fields in the data profile have the same name.")

    select_cols = [f"{expr(f)} AS {quote_ident(f.column)}" for f in profile.fields]
    where: list[str] = []
    params: list[Any] = []
    check_required_criteria(profile, criteria, ranges)

    if profile.dataarea_column:
        company = (company or "").strip()
        if not company:
            raise ValidationError("Company (DATAAREAID) is required for this profile.")
        if len(company) > 8:
            raise ValidationError("Company (DATAAREAID) is too long.")
        where.append(f"{col_ref('', profile.dataarea_column)} = ?")
        params.append(company)

    for col, value in fixed_pairs(profile.filters, "Fixed filter"):  # e.g. JOURNALTYPE = 2 (Transfer)
        if value.upper() == VIRTUAL_COMPANY:
            raise ValidationError(f"Fixed filter {col}: {VIRTUAL_COMPANY} can only be used for related tables.")
        where.append(f"{col_ref('', col)} = ?")
        params.append(value)

    for column, text in criteria.items():
        if not (text or "").strip():
            continue
        fd = profile.get_field(column)
        if fd is None or not fd.searchable:
            raise ValidationError(f"Field '{column}' is not searchable in this profile.")
        flt = parse_text_filter(apply_replace(text, fd.replace), fd.label, fd.search_mode)
        q = expr(fd)
        if flt.contains is not None:
            where.append(f"{q} LIKE ? ESCAPE '\\'")
            params.append(f"%{escape_like(flt.contains)}%")
            continue
        if flt.prefix is not None:  # "starts with" can use an index, much faster on big tables
            where.append(f"{q} LIKE ? ESCAPE '\\'")
            params.append(f"{escape_like(flt.prefix)}%")
            continue
        alternatives: list[str] = []
        if flt.exact:
            alternatives.append(f"{q} IN ({', '.join('?' * len(flt.exact))})")
            params.extend(flt.exact)
        for a, b in flt.ranges:
            alternatives.append(f"({q} >= ? AND {q} <= ?)")
            params.extend([a, b])
        where.append("(" + " OR ".join(alternatives) + ")")

    for column, (start, end) in (ranges or {}).items():
        if start is None and end is None:
            continue
        fd = check_range_field(profile, column)
        q = expr(fd)
        if start and end and start > end:
            raise ValidationError(f"{fd.label}: 'From' date is after 'To' date.")
        if start:
            where.append(f"{q} >= ?")
            params.append(datetime.combine(start, time.min))
        if end:  # inclusive: everything before the next day
            where.append(f"{q} < ?")
            params.append(datetime.combine(end + timedelta(days=1), time.min))

    order_parts = []
    for entry in profile.order_by or [profile.fields[0].column]:
        col, direction = split_order(entry)
        fd = profile.get_field(col)
        order_parts.append(f"{expr(fd) if fd else col_ref('', col)} {direction}")
    order_sql = ", ".join(order_parts)

    limit = int(profile.row_limit)
    if not 1 <= limit <= HARD_ROW_LIMIT:
        raise ValidationError(f"Row limit must be between 1 and {HARD_ROW_LIMIT}.")

    sql = (
        f"SELECT TOP ({limit}) {', '.join(select_cols)} "
        f"FROM {quote_ident(profile.schema)}.{quote_ident(profile.source)} AS a"
    )
    join_params: list[Any] = []  # placeholders in OUTER APPLY come before the WHERE ones
    for i, lk in enumerate(profile.lookups, start=1):
        outer, inner, t = f"l{i}", f"x{i}", lk.table.upper()
        if not lk.join:
            raise ValidationError(f"Related table '{lk.table}' has no join columns.")

        def inner_col(col: str, t=t, inner=inner) -> str:
            if allowed is not None and t in allowed and col.upper() not in allowed[t]:
                raise ValidationError(f"Column '{col}' does not exist in {lk.table}.")
            return f"{inner}.{quote_ident(col)}"

        conds = [f"{inner_col(lc)} = {col_ref('', mc)}" for lc, mc in lk.join]
        for col, value in fixed_pairs(lk.conditions, f"Related table {lk.table}"):
            if value.upper() == VIRTUAL_COMPANY:
                # AX virtual company of the row's company (DB1 -> VIR), or the company itself when it has none
                if not profile.dataarea_column:
                    raise ValidationError(f"Related table {lk.table}: {VIRTUAL_COMPANY} needs a company column.")
                # Resolved before the query: a subquery here made SQL Server scan (38 s instead of 0.2 s).
                conds.append(f"{inner_col(col)} = ?")
                join_params.append((virtual_company or company).strip())
            else:
                conds.append(f"{inner_col(col)} = ?")
                join_params.append(value)
        join_sql = " AND ".join(conds)
        lk_order = [split_order(o) for o in lk.order_by] or [(lk.join[0][0], "ASC")]
        cols = sorted(used[t]) or [lk.join[0][0].upper()]
        sql += (
            f" OUTER APPLY (SELECT TOP 1 {', '.join(inner_col(c) for c in cols)}"
            f" FROM {quote_ident(lk.schema)}.{quote_ident(lk.table)} AS {inner}"
            f" WHERE {join_sql}"
            f" ORDER BY {', '.join(f'{inner_col(c)} {d}' for c, d in lk_order)}) AS {outer}"
        )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_sql}"
    return sql, join_params + params
