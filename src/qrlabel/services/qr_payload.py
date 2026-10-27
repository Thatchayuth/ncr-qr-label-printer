"""QR payload engine: builds the exact text encoded in the QR code."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from ..domain.errors import PayloadError
from ..domain.models import DataProfile
from .formatting import format_value, is_null, record_get

LINE_SEPARATORS = ("\r\n", "\n")  # the only control characters allowed in a payload

# Byte-mode capacity of QR version 40 per error-correction level.
QR_BYTE_CAPACITY = {"L": 2953, "M": 2331, "Q": 1663, "H": 1273}


@dataclass(frozen=True)
class QrPayload:
    text: str
    byte_length: int
    error_correction: str


def _has_control_chars(text: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text)


class QrPayloadBuilder:
    def build(self, record: dict[str, Any], profile: DataProfile) -> QrPayload:
        cfg = profile.qr
        if not cfg.fields:
            raise PayloadError("QR configuration has no fields.")
        if cfg.error_correction not in QR_BYTE_CAPACITY:
            raise PayloadError(f"Unknown QR error correction level '{cfg.error_correction}'.")
        if cfg.format == "plain" and len(cfg.fields) != 1:
            raise PayloadError("Plain QR format uses exactly one field. Use delimited or JSON for more.")

        items: list[tuple[str, str]] = []
        for column in cfg.fields:
            fd = profile.get_field(column)
            raw = record_get(record, column)
            if is_null(raw) and not (fd and fd.default):
                if cfg.null_policy == "error" or (fd and fd.required):
                    raise PayloadError(f"QR field '{fd.label if fd else column}' is empty.")
            value = format_value(raw, fd)
            if cfg.format == "labeled":
                value = " ".join(value.split())  # AX text with line breaks stays on its own line
            if _has_control_chars(value):
                raise PayloadError(f"QR field '{column}' contains control characters.")
            if cfg.format == "delimited" and cfg.delimiter and cfg.delimiter in value:
                raise PayloadError(f"QR field '{column}' contains the delimiter '{cfg.delimiter}'.")
            label = (cfg.labels.get(column) or cfg.labels.get(column.upper()) or "") if cfg.format == "labeled" else ""
            items.append((label or (fd.label if fd else column), value))

        for part in (cfg.prefix, cfg.suffix, cfg.label_separator, *(lbl for lbl, _ in items)):
            if _has_control_chars(part):
                raise PayloadError("QR prefix, suffix or labels contain control characters.")
        if cfg.format == "plain":
            body = items[0][1]
        elif cfg.format == "delimited":
            body = cfg.delimiter.join(v for _, v in items)
        elif cfg.format == "json":
            body = json.dumps(dict(items), ensure_ascii=False, separators=(",", ":"))
        elif cfg.format == "labeled":
            if cfg.line_separator not in LINE_SEPARATORS and _has_control_chars(cfg.line_separator):
                raise PayloadError("QR line separator may only be CR+LF, LF or printable text.")
            body = cfg.line_separator.join(f"{label}{cfg.label_separator}{value}".rstrip() for label, value in items)
        else:
            raise PayloadError(f"Unknown QR format '{cfg.format}'.")

        text = unicodedata.normalize("NFC", f"{cfg.prefix}{body}{cfg.suffix}")
        size = len(text.encode("utf-8"))
        if size == 0:
            raise PayloadError("QR payload is empty.")
        limit = min(cfg.max_bytes, QR_BYTE_CAPACITY[cfg.error_correction])
        if size > limit:
            raise PayloadError(f"QR payload is {size} bytes; the limit is {limit} bytes.")
        return QrPayload(text=text, byte_length=size, error_correction=cfg.error_correction)
