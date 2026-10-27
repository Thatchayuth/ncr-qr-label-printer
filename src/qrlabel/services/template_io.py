"""Template import / export / duplicate."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..domain.errors import ValidationError
from ..domain.layout import validate_template
from ..domain.models import LabelTemplate, new_id
from ..infrastructure.config import atomic_write_text

FILE_FORMAT = "ncr-qrlabel-template"
FILE_FORMAT_VERSION = 1
MAX_FILE_BYTES = 5_000_000  # templates can contain logos


def export_template(t: LabelTemplate, path: Path) -> None:
    data = {"format": FILE_FORMAT, "format_version": FILE_FORMAT_VERSION, "template": t.to_dict()}
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def import_template(path: Path) -> LabelTemplate:
    """Read a template file. The result always gets a new id so nothing is overwritten."""
    t = read_template_file(path)
    t.id = new_id()
    t.version = 1
    return t


def read_template_file(path: Path) -> LabelTemplate:
    """Read and validate a template file, keeping its id (used for templates shipped with the app)."""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError("Template file is too large.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValidationError(f"Not a valid template file: {e}") from None
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT:
        raise ValidationError("This file is not an NCR QR Label template.")
    if int(data.get("format_version", 0)) > FILE_FORMAT_VERSION:
        raise ValidationError("The template file was made by a newer version of the application.")
    try:
        t = LabelTemplate.from_dict(data["template"])
        _coerce_numbers(t)
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError(f"Template file is damaged: {e}") from None
    problems = validate_template(t)
    if problems:
        raise ValidationError("Template file is invalid: " + "; ".join(problems))
    if not t.id or len(t.id) > 64:
        t.id = new_id()
    t.version = 1
    return t


def duplicate_template(t: LabelTemplate, name: str | None = None) -> LabelTemplate:
    d = copy.deepcopy(t)
    d.id = new_id()
    d.version = 1
    d.name = name or f"Copy of {t.name}"
    return d


def _coerce_numbers(t: LabelTemplate) -> None:
    for attr in ("width_mm", "height_mm", "gap_mm", "margin_mm"):
        setattr(t, attr, float(getattr(t, attr)))
    for attr in ("dpi", "density", "speed", "direction"):
        setattr(t, attr, int(getattr(t, attr)))
    for e in t.elements:
        for attr in ("x_mm", "y_mm", "w_mm", "h_mm", "font_mm", "thickness_mm", "min_font_mm"):
            setattr(e, attr, float(getattr(e, attr)))
        e.rotation = int(e.rotation)
        for attr in ("text", "field", "align", "kind", "name", "image_data"):
            if not isinstance(getattr(e, attr), str):
                raise TypeError(f"element {attr} must be text")
        if e.kind == "image" and e.image_data:
            from ..rendering.images import MAX_ENCODED_CHARS, decode_image

            if len(e.image_data) > MAX_ENCODED_CHARS:
                raise ValueError("image is too large")
            decode_image(e.image_data)  # raises if the image data is damaged


def snap(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 2)
    return round(round(value / step) * step, 2)
