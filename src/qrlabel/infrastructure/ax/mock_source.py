"""Simulated AX data source for development without database access.

All values are fake and prefixed with SAMPLE so they cannot be mistaken for real assets.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ...domain.errors import ValidationError
from ...domain.models import DataProfile
from ...services.query_builder import HARD_ROW_LIMIT, check_range_field, in_range, parse_text_filter

MOCK_COMPANY = "smp"


def _sample_rows() -> list[dict[str, Any]]:
    rows = []
    for i in range(1, 61):
        rows.append({
            "ASSETID": f"SAMPLE-FA-{i:05d}",
            "NAME": f"Sample asset {i}" if i % 7 else f"ทรัพย์สินตัวอย่าง {i}",
            "TECHINFO1": f"PU{i:04d}" if i % 3 else "",
            "TECHINFO2": f"{100000 + i}_018" if i % 4 else "",
            "CREATEDDATE": datetime(2026, 1, 1) + timedelta(days=i * 3),
            "DATAAREAID": MOCK_COMPANY,
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
        return [("ASSETID", "nvarchar"), ("NAME", "nvarchar"), ("TECHINFO1", "nvarchar"),
                ("TECHINFO2", "nvarchar"), ("CREATEDDATE", "datetime"), ("DATAAREAID", "nvarchar")]

    def search(self, profile: DataProfile, criteria: dict[str, str], company: str, ranges=None) -> list[dict[str, Any]]:
        if profile.source.upper() not in self.approved:
            raise ValidationError(f"Source '{profile.source}' is not approved.")
        rows = self.rows
        if profile.dataarea_column:
            if not company.strip():
                raise ValidationError("Company (DATAAREAID) is required for this profile.")
            rows = [r for r in rows if str(r.get(profile.dataarea_column.upper(), "")).lower() == company.strip().lower()]
        for column, text in criteria.items():
            if (text or "").strip():
                fd = profile.get_field(column)
                if fd is None or not fd.searchable:
                    raise ValidationError(f"Field '{column}' is not searchable in this profile.")
                flt = parse_text_filter(text, fd.label)
                rows = [r for r in rows if flt.matches(r.get(column.upper()))]
        for column, rng in (ranges or {}).items():
            if rng[0] is None and rng[1] is None:
                continue
            fd = check_range_field(profile, column)
            if rng[0] and rng[1] and rng[0] > rng[1]:
                raise ValidationError(f"{fd.label}: 'From' date is after 'To' date.")
            rows = [r for r in rows if in_range(r.get(column.upper()), rng)]
        keys = [c.upper() for c in (profile.order_by or [profile.fields[0].column])]
        rows = sorted(rows, key=lambda r: tuple(str(r.get(k, "")) for k in keys))
        cols = [f.column.upper() for f in profile.fields]
        limit = min(profile.row_limit, HARD_ROW_LIMIT)
        return [{c: r.get(c) for c in cols} for r in rows[:limit]]
