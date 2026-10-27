"""Rules for data profiles built in the Data Profiles editor."""
from __future__ import annotations

import re

from ..domain.models import DataProfile, FieldDef
from .query_builder import HARD_ROW_LIMIT, IDENT_RE, split_order, split_ref

# SQL Server types that cannot be compared with = / IN or used in ORDER BY
UNSORTABLE_TYPES = {"ntext", "text", "image", "xml", "varbinary", "binary", "timestamp", "geography", "geometry"}

ColumnMap = dict[str, dict[str, str]]  # TABLE (upper) -> {COLUMN (upper): sql type}


def suggest_type(sql_type: str) -> str:
    t = (sql_type or "").lower()
    if t in ("date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        return "date"
    if t in ("decimal", "numeric", "money", "smallmoney", "float", "real"):
        return "decimal"
    if t in ("int", "bigint", "smallint", "tinyint", "bit"):
        return "int"
    return "string"


def suggest_format(data_type: str) -> str:
    return {"date": "%d/%m/%Y", "decimal": ",2"}.get(data_type, "")


def pretty_label(column: str) -> str:
    """ACQUISITIONDATE -> Acquisitiondate, TECH_INFO -> Tech info (a starting point the admin can edit)."""
    text = re.sub(r"_+$", "", column).replace("_", " ").strip()
    return text[:1].upper() + text[1:].lower() if text else column


def new_field(column: str, sql_type: str, table: str, existing_keys: set[str]) -> FieldDef:
    """Field for a discovered column; the key gets a table prefix if the name is already used."""
    key = column.upper()
    if key in existing_keys:
        key = f"{table.upper()}_{column.upper()}"[:128]
    data_type = suggest_type(sql_type)
    searchable = data_type == "string" and sql_type.lower() not in UNSORTABLE_TYPES
    return FieldDef(
        column=key, source_column=column.upper() if key != column.upper() else "", table=table.upper(),
        alias=pretty_label(column), data_type=data_type, fmt=suggest_format(data_type),
        searchable=searchable, display=True,
    )


def validate_profile(p: DataProfile, columns: ColumnMap | None = None, template_ids: set[str] | None = None) -> list[str]:
    """Human-readable problems; empty list = OK. `columns` comes from the database (None = not checked)."""
    issues: list[str] = []
    main = p.source.upper()
    tables = {"": main, main: main}
    if not p.name.strip():
        issues.append("Enter a profile name.")
    if not IDENT_RE.match(p.source or ""):
        issues.append("Choose a table or view.")
    if not IDENT_RE.match(p.schema or ""):
        issues.append("Schema name is not valid.")
    if not 1 <= int(p.row_limit) <= HARD_ROW_LIMIT:
        issues.append(f"Row limit must be between 1 and {HARD_ROW_LIMIT}.")

    def col_type(table: str, column: str) -> str | None:
        t = tables.get(table.upper(), table.upper())
        if columns is None or t not in columns:
            return ""  # unknown: not checked
        return columns[t].get(column.upper())

    for lk in p.lookups:
        t = lk.table.upper()
        if not IDENT_RE.match(lk.table or ""):
            issues.append(f"Related table '{lk.table}' is not a valid name.")
            continue
        if t == main or t in tables and t != "":
            issues.append(f"Table {lk.table} is used twice.")
        tables[t] = t
        if not lk.join:
            issues.append(f"Related table {lk.table}: choose the columns that link it to {p.source}.")
        for pair in lk.join:
            if len(pair) != 2:
                issues.append(f"Related table {lk.table}: each link needs two columns.")
                continue
            lc, mc = pair
            if col_type(t, lc) is None:
                issues.append(f"Related table {lk.table}: column {lc} does not exist.")
            if col_type(main, mc) is None:
                issues.append(f"Related table {lk.table}: column {mc} does not exist in {p.source}.")
        for entry in lk.order_by:
            try:
                c, _ = split_order(entry)
            except Exception:
                issues.append(f"Related table {lk.table}: sort '{entry}' is not valid (use COLUMN or COLUMN DESC).")
                continue
            typ = col_type(t, c)
            if typ is None:
                issues.append(f"Related table {lk.table}: sort column {c} does not exist.")
            elif typ in UNSORTABLE_TYPES:
                issues.append(f"Related table {lk.table}: cannot sort by {c} ({typ}).")

    if p.dataarea_column and col_type(main, p.dataarea_column) is None:
        issues.append(f"Company column {p.dataarea_column} does not exist in {p.source}.")

    if not p.fields:
        issues.append("Add at least one field.")
    keys: set[str] = set()
    for f in p.fields:
        key = f.column.upper()
        if not IDENT_RE.match(f.column or ""):
            issues.append(f"Field name '{f.column}' is not valid (letters, digits and _ only).")
        if key in keys:
            issues.append(f"Field {f.column} is listed twice.")
        keys.add(key)
        if f.table and f.table.upper() not in tables:
            issues.append(f"{f.label}: table {f.table} is not the main table or a related table.")
            continue
        typ = col_type(f.table, f.source)
        if typ is None:
            issues.append(f"{f.label}: column {f.source} does not exist in {f.table or p.source}.")
        elif typ in UNSORTABLE_TYPES and (f.searchable or f.range_search):
            issues.append(f"{f.label}: {typ} columns cannot be searched. Turn off Search for this field.")
        if f.range_search and f.data_type != "date":
            issues.append(f"{f.label}: date range search needs type 'date'.")
        if f.fallback:
            try:
                ft, fc = split_ref(f.fallback)
            except Exception:
                issues.append(f"{f.label}: fallback must be COLUMN or TABLE.COLUMN.")
            else:
                if ft and ft.upper() not in tables:
                    issues.append(f"{f.label}: fallback table {ft} is not part of the profile.")
                elif col_type(ft, fc) is None:
                    issues.append(f"{f.label}: fallback column {f.fallback} does not exist.")
    if p.fields and not any(f.display for f in p.fields):
        issues.append("Show at least one field in the results.")

    for entry in p.order_by:
        try:
            c, _ = split_order(entry)
        except Exception:
            issues.append(f"Sort '{entry}' is not valid.")
            continue
        fd = p.get_field(c)
        typ = col_type(fd.table, fd.source) if fd else col_type("", c)
        if typ is None:
            issues.append(f"Sort column {c} does not exist.")
        elif typ in UNSORTABLE_TYPES:
            issues.append(f"Cannot sort by {c} ({typ}).")

    missing_qr = [c for c in p.qr.fields if c.upper() not in keys]
    if missing_qr:
        issues.append(f"QR uses fields that are no longer in the profile: {', '.join(missing_qr)}.")
    if template_ids is not None and p.template_id and p.template_id not in template_ids:
        issues.append("The default label template no longer exists.")
    if p.template_ids:
        if p.template_id and p.template_id not in p.template_ids:
            issues.append("The default label must be one of the labels ticked for this profile.")
        if template_ids is not None:
            gone = [t for t in p.template_ids if t not in template_ids]
            if gone:
                issues.append(f"{len(gone)} ticked label(s) no longer exist. Untick them.")
    return issues


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def template_fields(template) -> set[str]:
    """Data fields a label template prints (dynamic text and {COLUMN} placeholders), upper case."""
    used: set[str] = set()
    for el in template.elements:
        if el.kind != "text":
            continue
        if el.field:
            used.add(el.field.upper())
        used.update(m.upper() for m in _PLACEHOLDER_RE.findall(el.text or ""))
    return used


def template_issues(template, profile: DataProfile) -> list[str]:
    """Warnings when a label needs data the profile does not provide (printing still works: blank text)."""
    keys = {f.column.upper() for f in profile.fields}
    missing = sorted(template_fields(template) - keys)
    issues = []
    if missing:
        issues.append(f"'{template.name}' prints field(s) not in '{profile.name}': {', '.join(missing)} (would print empty).")
    if any(e.kind == "qr" for e in template.elements) and not profile.qr.fields:
        issues.append(f"'{template.name}' has a QR code but '{profile.name}' has no QR fields.")
    return issues
