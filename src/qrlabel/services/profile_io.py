"""Data profile import / export / duplicate."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..domain.errors import ValidationError
from ..domain.models import DataProfile, new_id
from ..infrastructure.config import atomic_write_text
from .profile_rules import validate_profile

FILE_FORMAT = "ncr-qrlabel-profile"
FILE_FORMAT_VERSION = 1
MAX_FILE_BYTES = 1_000_000


def export_profile(p: DataProfile, path: Path) -> None:
    data = {"format": FILE_FORMAT, "format_version": FILE_FORMAT_VERSION, "profile": p.to_dict()}
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def import_profile(path: Path) -> DataProfile:
    """Read a profile file. It always gets a new id, so nothing existing is overwritten."""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError("Profile file is too large.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValidationError(f"Not a valid profile file: {e}") from None
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT:
        raise ValidationError("This file is not an NCR Print Label data profile.")
    if int(data.get("format_version", 0)) > FILE_FORMAT_VERSION:
        raise ValidationError("The profile file was made by a newer version of the application.")
    try:
        p = DataProfile.from_dict(data["profile"])
        p.row_limit = int(p.row_limit)
        for f in p.fields:
            for attr in ("column", "alias", "table", "source_column", "fallback", "data_type", "fmt", "default"):
                if not isinstance(getattr(f, attr), str):
                    raise TypeError(f"field {attr} must be text")
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError(f"Profile file is damaged: {e}") from None
    problems = validate_profile(p)  # structure only; columns are checked against AX when saving
    if problems:
        raise ValidationError("Profile file is invalid: " + "; ".join(problems))
    p.id = new_id()
    p.version = 1
    return p


def duplicate_profile(p: DataProfile) -> DataProfile:
    d = copy.deepcopy(p)
    d.id = new_id()
    d.version = 1
    d.name = f"Copy of {p.name}"
    return d
