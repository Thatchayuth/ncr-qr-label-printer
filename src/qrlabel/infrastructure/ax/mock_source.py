"""Simulated AX data source for development without database access.

All values are fake and prefixed with SAMPLE so they cannot be mistaken for real assets.
Sample rows are flat: columns of related tables (e.g. ASSETBOOK.PURCHID) sit next to
the main columns, keyed as "TABLE.COLUMN".
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from ...domain.errors import ValidationError
from ...domain.models import DataProfile, FieldDef
from ...services.formatting import is_null
from ...services.query_builder import HARD_ROW_LIMIT, check_range_field, in_range, parse_text_filter, split_order, split_ref

MOCK_COMPANY = "smp"
_DEPARTMENTS = ["OADM", "FPRO_MOLD", "FPRO_LLH", "IT"]


def _sample_rows() -> list[dict[str, Any]]:
    rows = []
    for i in range(1, 61):
        rows.append({
            "ASSETID": f"SAMPLE-FA-{i:05d}",
            "NAME": f"Sample asset {i}" if i % 7 else f"ทรัพย์สินตัวอย่าง {i}",
            "TECHINFO1": f"PU{i:04d}" if i % 3 else "",
            "TECHINFO2": f"{900000 + i}_018" if i % 10 == 0 else "",
            "CREATEDDATE": datetime(2026, 1, 1) + timedelta(days=i * 3),
            "DATAAREAID": MOCK_COMPANY,
            "ASSETBOOK.PURCHID": f"{100000 + i}_018" if i % 4 else "",
            "ASSETBOOK.DIMENSION": _DEPARTMENTS[i % len(_DEPARTMENTS)],
            "ASSETBOOK.ACQUISITIONDATE": datetime(2025, 12, 1) + timedelta(days=i * 2),
            "ASSETBOOK.ACQUISITIONPRICE": Decimal(1250 * i) + Decimal("0.50"),
        })
    return rows


class MockDataSource:
    kind = "mock"

    def __init__(self, approved_sources: list[str], rows: list[dict[str, Any]] | None = None) -> None:
        self.approved = {s.upper() for s in approved_sources}
        self.rows = rows if rows is not None else _sample_rows()

    def test_connection(self) -> str:
        return f"Mock data source ({len(self.rows)} sample rows, company '{MOCK_COMPANY}')"

    def list_columns(self, source: str, schema: str = "dbo") -> list[tuple[str, str]]:
        if source.upper() not in self.approved:
            raise ValidationError(f"Source '{source}' is not approved.")
        prefix = "" if source.upper() == "ASSETTABLE" else f"{source.upper()}."
        sample = self.rows[0] if self.rows else {}
        cols = [k[len(prefix):] for k in sample if (k.startswith(prefix) if prefix else "." not in k)]
        return [(c, "nvarchar") for c in cols]

    def _value(self, row: dict[str, Any], profile: DataProfile, fd: FieldDef) -> Any:
        def get(table: str, col: str) -> Any:
            t = table.upper()
            key = col.upper() if not t or t == profile.source.upper() else f"{t}.{col.upper()}"
            return row.get(key)

        value = get(fd.table, fd.source)
        if fd.fallback and is_null(value):
            value = get(*split_ref(fd.fallback))
        return value

    def search(self, profile: DataProfile, criteria: dict[str, str], company: str, ranges=None) -> list[dict[str, Any]]:
        for t in [profile.source] + [lk.table for lk in profile.lookups]:
            if t.upper() not in self.approved:
                raise ValidationError(f"Source '{t}' is not approved.")
        rows = self.rows
        if profile.dataarea_column:
            if not company.strip():
                raise ValidationError("Company (DATAAREAID) is required for this profile.")
            rows = [r for r in rows if str(r.get(profile.dataarea_column.upper(), "")).lower() == company.strip().lower()]
        projected = [{f.column.upper(): self._value(r, profile, f) for f in profile.fields} for r in rows]
        for column, text in criteria.items():
            if (text or "").strip():
                fd = profile.get_field(column)
                if fd is None or not fd.searchable:
                    raise ValidationError(f"Field '{column}' is not searchable in this profile.")
                flt = parse_text_filter(text, fd.label)
                projected = [r for r in projected if flt.matches(r.get(fd.column.upper()))]
        for column, rng in (ranges or {}).items():
            if rng[0] is None and rng[1] is None:
                continue
            fd = check_range_field(profile, column)
            if rng[0] and rng[1] and rng[0] > rng[1]:
                raise ValidationError(f"{fd.label}: 'From' date is after 'To' date.")
            projected = [r for r in projected if in_range(r.get(fd.column.upper()), rng)]
        for entry in reversed(profile.order_by or [profile.fields[0].column]):
            col, direction = split_order(entry)
            projected.sort(key=lambda r: str(r.get(col.upper(), "")), reverse=direction == "DESC")
        return projected[: min(profile.row_limit, HARD_ROW_LIMIT)]
