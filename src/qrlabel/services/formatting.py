"""Turn raw AX values into display/label strings."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..domain.models import DataProfile, FieldDef

# AX stores "no date" as 1900-01-01.
AX_EMPTY_DATE = date(1900, 1, 1)


def record_get(record: dict[str, Any], column: str) -> Any:
    if column in record:
        return record[column]
    return record.get(column.upper())


def is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, datetime):
        return value.date() <= AX_EMPTY_DATE
    if isinstance(value, date):
        return value <= AX_EMPTY_DATE
    return False


def format_value(value: Any, fd: FieldDef | None = None) -> str:
    if is_null(value):
        return fd.default if fd else ""
    if isinstance(value, (datetime, date)):
        pattern = (fd.fmt if fd and fd.fmt else "%Y-%m-%d")
        return value.strftime(pattern)
    if isinstance(value, (Decimal, float)) and not isinstance(value, bool):
        places = int(fd.fmt) if fd and fd.fmt.isdigit() else None
        try:
            d = Decimal(str(value))
            if places is not None:
                return f"{d:.{places}f}"
            # drop trailing zeros, but never use exponent notation
            text = format(d.normalize(), "f")
            return text
        except InvalidOperation:
            return str(value)
    return str(value).strip()


def build_label_values(profile: DataProfile, record: dict[str, Any]) -> dict[str, str]:
    """Formatted strings for every column in the record (keys UPPER CASE)."""
    out: dict[str, str] = {}
    for key, value in record.items():
        out[key.upper()] = format_value(value, profile.get_field(key))
    for fd in profile.fields:  # ensure defaults for columns missing from the record
        out.setdefault(fd.column.upper(), fd.default)
    return out


def document_ref(profile: DataProfile, values: dict[str, str]) -> str:
    """Business reference stored in history (first profile field, e.g. ASSETID)."""
    if not profile.fields:
        return ""
    return values.get(profile.fields[0].column.upper(), "")
