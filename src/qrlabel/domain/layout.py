"""Physical-unit helpers and template validation."""
from __future__ import annotations

from .models import LabelTemplate

# TSC TE200 datasheet values (verify against the unit in Phase 0 hardware tests).
TE200_DPI = 203
TE200_MAX_PRINT_WIDTH_MM = 108.0
TE200_MAX_PRINT_LENGTH_MM = 2794.0

VALID_KINDS = {"text", "qr", "rect", "line", "image"}
VALID_ROTATIONS = {0, 90, 180, 270}


def mm_to_dots(mm: float, dpi: int = TE200_DPI) -> int:
    return int(round(mm * dpi / 25.4))


def dots_to_mm(dots: int, dpi: int = TE200_DPI) -> float:
    return dots * 25.4 / dpi


def validate_template(t: LabelTemplate) -> list[str]:
    """Return a list of human-readable problems. Empty list = valid."""
    issues: list[str] = []
    if t.width_mm <= 0 or t.height_mm <= 0:
        issues.append("Label width and height must be greater than 0 mm.")
    if t.width_mm > TE200_MAX_PRINT_WIDTH_MM:
        issues.append(f"Label width {t.width_mm} mm exceeds TE200 print width {TE200_MAX_PRINT_WIDTH_MM} mm.")
    if t.height_mm > TE200_MAX_PRINT_LENGTH_MM:
        issues.append(f"Label height {t.height_mm} mm exceeds TE200 max length.")
    if t.gap_mm < 0:
        issues.append("Gap cannot be negative.")
    if t.media not in ("gap", "bline", "continuous"):
        issues.append(f"Unknown media type '{t.media}'.")
    if not 0 <= t.density <= 15:
        issues.append("Density must be between 0 and 15.")
    if t.speed not in (2, 3, 4, 5, 6):
        issues.append("Speed must be 2-6 ips (TE200 supports up to 6 ips).")
    if t.qr_mode not in ("bitmap", "native"):
        issues.append(f"Unknown QR mode '{t.qr_mode}'.")
    if t.text_mode not in ("bitmap", "native", "auto"):
        issues.append(f"Unknown text mode '{t.text_mode}'.")

    m = t.margin_mm
    for i, e in enumerate(t.elements):
        label = e.name or f"{e.kind} #{i + 1}"
        if e.kind not in VALID_KINDS:
            issues.append(f"{label}: unknown element type '{e.kind}'.")
            continue
        if e.rotation not in VALID_ROTATIONS:
            issues.append(f"{label}: rotation must be 0, 90, 180 or 270.")
        if e.w_mm <= 0 or e.h_mm <= 0:
            if not (e.kind == "line" and (e.w_mm > 0 or e.h_mm > 0)):
                issues.append(f"{label}: size must be greater than 0.")
        w, h = (e.h_mm, e.w_mm) if e.rotation in (90, 270) else (e.w_mm, e.h_mm)
        if e.x_mm < m - 1e-6 or e.y_mm < m - 1e-6 or e.x_mm + w > t.width_mm - m + 1e-6 or e.y_mm + h > t.height_mm - m + 1e-6:
            issues.append(f"{label}: outside printable area (margin {m} mm).")
        if e.kind == "text" and e.font_mm <= 0:
            issues.append(f"{label}: font size must be greater than 0.")
        if e.kind == "qr" and not 0 <= int(e.qr_version) <= 40:
            issues.append(f"{label}: QR size must be Auto or version 1-40.")
        if e.kind == "image" and not e.image_data:
            issues.append(f"{label}: no image selected.")
    return issues
