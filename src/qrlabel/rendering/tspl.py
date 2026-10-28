"""TSPL/TSPL2 command generation for TSC TE200 (203 dpi).

Dynamic data never goes into a TSPL string literal unless every character is in a
strict whitelist (no quotes, backslashes or control characters). Anything else is
rasterised and sent as BITMAP, so operator/AX data cannot break the command stream.
"""
from __future__ import annotations

import string

from PIL import Image

from ..domain.errors import ValidationError
from ..domain.layout import mm_to_dots, validate_template
from ..domain.models import LabelElement, LabelTemplate
from .raster import Placed, qr_geometry, qr_matrix, rasterize_element, resolve_text, text_overflows

CRLF = b"\r\n"
NATIVE_SAFE_CHARS = frozenset(string.ascii_letters + string.digits + " -_./:+*$%#=,;@()&?'")
# Built-in TSPL bitmap fonts at 203 dpi: name, char width, char height (dots).
NATIVE_FONTS = [("1", 8, 12), ("2", 12, 20), ("3", 16, 24), ("4", 24, 32), ("5", 32, 48)]
MAX_NATIVE_QR_CELL = 10


def is_native_safe(text: str) -> bool:
    return bool(text) and all(ch in NATIVE_SAFE_CHARS for ch in text)


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def bitmap_command(placed: Placed) -> bytes:
    img = placed.image.convert("1")
    if img.width % 8:  # pad right edge with white; padding bits must not print
        padded = Image.new("1", (img.width + 8 - img.width % 8, img.height), 1)
        padded.paste(img, (0, 0))
        img = padded
    head = f"BITMAP {placed.x},{placed.y},{img.width // 8},{img.height},0,".encode("ascii")
    return head + img.tobytes() + CRLF


def _pick_native_font(font_mm: float, dpi: int) -> tuple[str, int, int]:
    target = mm_to_dots(font_mm, dpi)
    best = NATIVE_FONTS[0]
    for f in NATIVE_FONTS:
        if f[2] <= target:
            best = f
    return best


class TsplRenderer:
    def header(self, t: LabelTemplate) -> bytes:
        lines = [f"SIZE {_num(t.width_mm)} mm,{_num(t.height_mm)} mm"]
        if t.media == "bline":
            lines.append(f"BLINE {_num(t.gap_mm)} mm,0 mm")
        elif t.media == "continuous":
            lines.append("GAP 0,0")
        else:
            lines.append(f"GAP {_num(t.gap_mm)} mm,0 mm")
        lines += [
            f"DIRECTION {int(t.direction)}",
            "REFERENCE 0,0",
            f"DENSITY {int(t.density)}",
            f"SPEED {int(t.speed)}",
        ]
        return CRLF.join(s.encode("ascii") for s in lines) + CRLF

    # ------------------------------------------------------------------ elements

    def _native_qr(self, el: LabelElement, t: LabelTemplate, text: str, ecc: str) -> bytes:
        n = len(qr_matrix(text, ecc))
        box_w, box_h = mm_to_dots(el.w_mm, t.dpi), mm_to_dots(el.h_mm, t.dpi)
        geo = qr_geometry(n, box_w, box_h, max_cell=MAX_NATIVE_QR_CELL)
        x = mm_to_dots(el.x_mm, t.dpi) + geo.offset_x
        y = mm_to_dots(el.y_mm, t.dpi) + geo.offset_y
        return f'QRCODE {x},{y},{ecc},{geo.cell},A,0,"{text}"'.encode("ascii") + CRLF

    def _native_text(self, el: LabelElement, t: LabelTemplate, text: str) -> tuple[bytes, bool]:
        name, cw, ch = _pick_native_font(el.font_mm, t.dpi)
        box_w = mm_to_dots(el.w_mm, t.dpi)
        if el.auto_fit:  # step down to smaller built-in fonts until the text fits
            for f in reversed(NATIVE_FONTS):
                if f[2] <= ch and f[1] * len(text) <= box_w:
                    name, cw, ch = f
                    break
        tw = cw * len(text)
        x = mm_to_dots(el.x_mm, t.dpi)
        if el.align == "center":
            x += max(0, (box_w - tw) // 2)
        elif el.align == "right":
            x += max(0, box_w - tw)
        y = mm_to_dots(el.y_mm, t.dpi)
        overflow = tw > box_w or ch > mm_to_dots(el.h_mm, t.dpi)
        return f'TEXT {x},{y},"{name}",0,1,1,"{text}"'.encode("ascii") + CRLF, overflow

    def _shape(self, el: LabelElement, t: LabelTemplate) -> bytes:
        x, y = mm_to_dots(el.x_mm, t.dpi), mm_to_dots(el.y_mm, t.dpi)
        w, h = mm_to_dots(el.w_mm, t.dpi), mm_to_dots(el.h_mm, t.dpi)
        th = max(1, mm_to_dots(el.thickness_mm, t.dpi))
        if el.kind == "rect":
            return f"BOX {x},{y},{x + w},{y + h},{th}".encode("ascii") + CRLF
        bar = (max(w, 1), th) if w >= h else (th, max(h, 1))
        return f"BAR {x},{y},{bar[0]},{bar[1]}".encode("ascii") + CRLF

    def element_commands(
        self, el: LabelElement, t: LabelTemplate, values: dict[str, str], qr_text: str | None, ecc: str
    ) -> tuple[bytes, list[str]]:
        name = el.name or el.kind
        # the printer's QRCODE command picks its own size, so a fixed QR size always uses the bitmap
        if el.kind == "qr" and qr_text and t.qr_mode == "native" and el.rotation == 0 and not el.qr_version:
            if is_native_safe(qr_text):
                return self._native_qr(el, t, qr_text, ecc), []
            fallback = [f"{name}: QR data not safe for native mode; printed as bitmap"]
        else:
            fallback = []

        if el.kind == "text" and el.rotation == 0:
            text = resolve_text(el, values)
            use_native = t.text_mode == "native" or (t.text_mode == "auto" and not el.bold)
            if use_native and is_native_safe(text) and not el.wrap:  # printer fonts draw one line only
                cmd, overflow = self._native_text(el, t, text)
                return cmd, ([f"{name}: text '{text}' does not fit its box"] if overflow else [])

        if el.kind in ("rect", "line") and el.rotation == 0:
            return self._shape(el, t), []

        placed, warnings = rasterize_element(el, t, values, qr_text, ecc)
        return (bitmap_command(placed) if placed else b""), fallback + warnings

    # --------------------------------------------------------------------- public

    def label_commands(
        self, t: LabelTemplate, values: dict[str, str], qr_text: str | None, copies: int, ecc: str = "M"
    ) -> tuple[bytes, list[str]]:
        out = [b"CLS" + CRLF]
        warnings: list[str] = []
        for el in t.elements:
            cmd, w = self.element_commands(el, t, values, qr_text, ecc)
            out.append(cmd)
            warnings += w
        out.append(f"PRINT 1,{int(copies)}".encode("ascii") + CRLF)
        return b"".join(out), warnings

    def render_job(
        self,
        t: LabelTemplate,
        labels: list[tuple[dict[str, str], str | None]],
        copies: int,
        ecc: str = "M",
    ) -> tuple[bytes, list[str]]:
        problems = validate_template(t)
        if problems:
            raise ValidationError("Label template is invalid: " + "; ".join(problems))
        if not 1 <= int(copies) <= 999:
            raise ValidationError("Copies must be between 1 and 999.")
        parts = [self.header(t)]
        warnings: list[str] = []
        for values, qr_text in labels:
            data, w = self.label_commands(t, values, qr_text, copies, ecc)
            parts.append(data)
            warnings += w
        return b"".join(parts), warnings


__all__ = ["TsplRenderer", "bitmap_command", "is_native_safe", "text_overflows"]
