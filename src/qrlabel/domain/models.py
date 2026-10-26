"""Domain models shared by services, storage, renderers and the UI.

All label geometry is stored in millimetres so it never depends on screen DPI.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any


def new_id() -> str:
    return uuid.uuid4().hex


def _pick(cls, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys the dataclass knows (tolerates older/newer JSON)."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


class PrintStatus(str, Enum):
    PENDING = "Pending"
    SUBMITTING = "Submitting"
    SPOOLER_ACCEPTED = "SpoolerAccepted"      # Windows spooler took the job
    SUBMITTED_TO_DEVICE = "SubmittedToDevice"  # bytes sent over TCP to the device
    FAILED = "Failed"                          # definitely not printed
    CANCELLED = "Cancelled"
    UNKNOWN_DELIVERY = "UnknownDelivery"      # may or may not have printed
    CONFIRMED_PRINTED = "ConfirmedPrinted"    # only set by reliable confirmation

    @property
    def is_final_failure(self) -> bool:
        return self in (PrintStatus.FAILED, PrintStatus.CANCELLED)


# --------------------------------------------------------------------------- data


@dataclass
class FieldDef:
    column: str
    alias: str = ""
    data_type: str = "string"  # string | int | decimal | date
    searchable: bool = False
    range_search: bool = False  # date fields: search by From - To
    display: bool = True
    required: bool = False
    default: str = ""
    fmt: str = ""  # strftime pattern for dates, number of places for decimals

    @property
    def label(self) -> str:
        return self.alias or self.column


@dataclass
class QrConfig:
    format: str = "plain"  # plain | delimited | json
    fields: list[str] = field(default_factory=list)
    delimiter: str = "|"
    prefix: str = ""
    suffix: str = ""
    null_policy: str = "error"  # error | empty
    error_correction: str = "M"  # L | M | Q | H
    max_bytes: int = 300


@dataclass
class DataProfile:
    id: str
    name: str
    source: str  # approved table or view name
    schema: str = "dbo"
    dataarea_column: str = "DATAAREAID"  # empty string = no company filter
    fields: list[FieldDef] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    row_limit: int = 200
    qr: QrConfig = field(default_factory=QrConfig)
    template_id: str = ""
    version: int = 1

    def get_field(self, column: str) -> FieldDef | None:
        col = column.upper()
        return next((f for f in self.fields if f.column.upper() == col), None)

    @property
    def searchable_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.searchable]

    @property
    def range_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.range_search]

    @property
    def display_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.display]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataProfile":
        d = _pick(cls, dict(data))
        d["fields"] = [FieldDef(**_pick(FieldDef, f)) for f in d.get("fields", [])]
        d["qr"] = QrConfig(**_pick(QrConfig, d.get("qr", {})))
        return cls(**d)


# -------------------------------------------------------------------------- label


@dataclass
class LabelElement:
    kind: str  # text | qr | rect | line
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    text: str = ""  # static text; may contain {COLUMN} placeholders
    field: str = ""  # dynamic text: column whose formatted value is printed
    font_mm: float = 3.0
    bold: bool = False
    align: str = "left"  # left | center | right
    rotation: int = 0  # 0 | 90 | 180 | 270 (clockwise)
    auto_fit: bool = True  # text: shrink font (down to min_font_mm) when it would overflow
    min_font_mm: float = 1.8
    thickness_mm: float = 0.3
    name: str = ""
    locked: bool = False  # designer only: cannot be moved / resized on the canvas


@dataclass
class LabelTemplate:
    id: str
    name: str
    width_mm: float
    height_mm: float
    gap_mm: float = 2.0
    media: str = "gap"  # gap | bline | continuous
    dpi: int = 203
    margin_mm: float = 1.0
    density: int = 8  # TSPL DENSITY 0-15
    speed: int = 4  # TSPL SPEED (ips)
    direction: int = 1  # TSPL DIRECTION 0|1
    qr_mode: str = "bitmap"  # bitmap | native  (see docs/phase0-discovery.md)
    text_mode: str = "bitmap"  # bitmap | native | auto
    elements: list[LabelElement] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabelTemplate":
        d = _pick(cls, dict(data))
        d["elements"] = [LabelElement(**_pick(LabelElement, e)) for e in d.get("elements", [])]
        return cls(**d)


# ---------------------------------------------------------------------- printing


@dataclass
class PrintJob:
    id: str
    correlation_id: str
    document_ref: str
    printer_name: str
    adapter: str
    copies: int
    profile_id: str = ""
    profile_version: int = 0
    template_id: str = ""
    template_version: int = 0
    status: PrintStatus = PrintStatus.PENDING
    username: str = ""
    app_version: str = ""
    parent_job_id: str = ""
    reason: str = ""
    spool_job_id: int | None = None
    error_code: str = ""
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""
    record_json: str = ""  # formatted label values used for this job (for identical reprints)


@dataclass
class SendResult:
    status: PrintStatus
    message: str = ""
    spool_job_id: int | None = None
    error_code: str = ""
