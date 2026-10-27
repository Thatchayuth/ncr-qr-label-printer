"""Shared raster renderer.

Used for (a) the on-screen preview and (b) BITMAP elements sent to the printer,
so preview and print come from the same pixels. Images are 1-bit, 0 = black dot.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

from ..domain.layout import mm_to_dots
from ..domain.models import LabelElement, LabelTemplate

ECC_LEVELS = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}

# Fonts that ship with Windows and cover Thai + Latin.
_REGULAR_FONTS = ["tahoma.ttf", "LeelawUI.ttf", "arial.ttf"]
_BOLD_FONTS = ["tahomabd.ttf", "LeelaUIb.ttf", "arialbd.ttf"]

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
MIN_QR_CELL_DOTS = 3  # 3 dots = 0.375 mm per QR module at 203 dpi; smaller is unreliable to scan


@dataclass
class Placed:
    image: Image.Image  # mode "1"
    x: int
    y: int


@dataclass(frozen=True)
class QrGeometry:
    modules: int
    cell: int
    offset_x: int
    offset_y: int

    @property
    def size(self) -> int:
        return self.modules * self.cell


@lru_cache(maxsize=64)
def _font_path(bold: bool) -> str | None:
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in _BOLD_FONTS if bold else _REGULAR_FONTS:
        p = fonts_dir / name
        if p.exists():
            return str(p)
    return None


@lru_cache(maxsize=128)
def get_font(size_px: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, size_px)
    return ImageFont.load_default(size_px)


def resolve_text(el: LabelElement, values: dict[str, str]) -> str:
    if el.field:
        return values.get(el.field.upper(), "")
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1).upper(), ""), el.text)


def qr_matrix(text: str, ecc: str) -> list[list[bool]]:
    q = qrcode.QRCode(error_correction=ECC_LEVELS[ecc], box_size=1, border=0)
    q.add_data(text.encode("utf-8"))
    q.make(fit=True)
    return q.get_matrix()


def qr_geometry(modules: int, box_w: int, box_h: int, max_cell: int | None = None) -> QrGeometry:
    cell = max(1, min(box_w, box_h) // modules)
    if max_cell:
        cell = min(cell, max_cell)
    size = modules * cell
    return QrGeometry(modules, cell, max(0, (box_w - size) // 2), max(0, (box_h - size) // 2))


def _rotate(img: Image.Image, rotation: int) -> Image.Image:
    ops = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
    return img.transpose(ops[rotation]) if rotation in ops else img


def _to_1bit(gray: Image.Image) -> Image.Image:
    return gray.point(lambda p: 255 if p >= 128 else 0).convert("1", dither=Image.Dither.NONE)


def text_overflows(text: str, el: LabelElement, dpi: int) -> bool:
    font = get_font(fit_font_px(text, el, dpi), el.bold)
    left, top, right, bottom = font.getbbox(text or " ", anchor="la")
    return (right - left) > mm_to_dots(el.w_mm, dpi) or bottom > mm_to_dots(el.h_mm, dpi)


def rasterize_qr(qr_text: str, ecc: str, el: LabelElement, dpi: int) -> tuple[Placed, QrGeometry]:
    matrix = qr_matrix(qr_text, ecc)
    n = len(matrix)
    geo = qr_geometry(n, mm_to_dots(el.w_mm, dpi), mm_to_dots(el.h_mm, dpi))
    img = Image.new("1", (n, n), 1)
    px = img.load()
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                px[x, y] = 0
    img = img.resize((geo.size, geo.size), Image.Resampling.NEAREST)
    x0, y0 = mm_to_dots(el.x_mm, dpi), mm_to_dots(el.y_mm, dpi)
    return Placed(_rotate(img, el.rotation), x0 + geo.offset_x, y0 + geo.offset_y), geo


def fit_font_px(text: str, el: LabelElement, dpi: int) -> int:
    """Font size in dots: the configured size, shrunk to fit the box when auto_fit is on."""
    size = max(1, mm_to_dots(el.font_mm, dpi))
    if not el.auto_fit or not text:
        return size
    w, h = mm_to_dots(el.w_mm, dpi), mm_to_dots(el.h_mm, dpi)
    smallest = max(1, mm_to_dots(min(el.min_font_mm, el.font_mm), dpi))
    while size > smallest:
        left, _, right, bottom = get_font(size, el.bold).getbbox(text, anchor="la")
        if right - left <= w and bottom <= h:
            break
        size -= 1
    return size


def rasterize_text(text: str, el: LabelElement, dpi: int) -> tuple[Placed, bool]:
    w, h = max(1, mm_to_dots(el.w_mm, dpi)), max(1, mm_to_dots(el.h_mm, dpi))
    font = get_font(fit_font_px(text, el, dpi), el.bold)
    gray = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(gray)
    left, _, right, bottom = draw.textbbox((0, 0), text or "", font=font, anchor="la")
    tw = right - left
    if el.align == "center":
        x = (w - tw) // 2 - left
    elif el.align == "right":
        x = w - tw - left
    else:
        x = -left
    draw.text((x, 0), text, font=font, fill=0, anchor="la")
    overflow = tw > w or bottom > h
    x0, y0 = mm_to_dots(el.x_mm, dpi), mm_to_dots(el.y_mm, dpi)
    return Placed(_rotate(_to_1bit(gray), el.rotation), x0, y0), overflow


def rasterize_shape(el: LabelElement, dpi: int) -> Placed:
    w, h = mm_to_dots(el.w_mm, dpi), mm_to_dots(el.h_mm, dpi)
    t = max(1, mm_to_dots(el.thickness_mm, dpi))
    if el.kind == "line":
        size = (max(w, 1), t) if w >= h else (t, max(h, 1))
        img = Image.new("1", size, 0)
    else:
        img = Image.new("1", (max(w, 1), max(h, 1)), 1)
        ImageDraw.Draw(img).rectangle([0, 0, img.width - 1, img.height - 1], outline=0, width=t)
    return Placed(_rotate(img, el.rotation), mm_to_dots(el.x_mm, dpi), mm_to_dots(el.y_mm, dpi))


def rasterize_element(
    el: LabelElement, t: LabelTemplate, values: dict[str, str], qr_text: str | None, ecc: str = "M"
) -> tuple[Placed | None, list[str]]:
    warnings: list[str] = []
    name = el.name or el.kind
    if el.kind == "qr":
        if not qr_text:
            return None, [f"{name}: no QR payload"]
        placed, geo = rasterize_qr(qr_text, ecc, el, t.dpi)
        if geo.cell < MIN_QR_CELL_DOTS:
            warnings.append(
                f"{name}: QR dots are only {geo.cell} printer dot(s) ({geo.modules}×{geo.modules} modules) - "
                f"may be hard to scan. Make the QR bigger, put less data in it or use error correction L."
            )
        return placed, warnings
    if el.kind == "text":
        text = resolve_text(el, values)
        placed, overflow = rasterize_text(text, el, t.dpi)
        if overflow:
            warnings.append(f"{name}: text '{text}' does not fit its box")
        return placed, warnings
    if el.kind in ("rect", "line"):
        return rasterize_shape(el, t.dpi), warnings
    return None, [f"{name}: unsupported element type '{el.kind}'"]


def paste_black(canvas: Image.Image, placed: Placed) -> None:
    """Draw only the black dots of `placed` onto an L-mode canvas."""
    mask = ImageOps.invert(placed.image.convert("L"))
    canvas.paste(0, (placed.x, placed.y), mask)


def render_label_image(
    t: LabelTemplate, values: dict[str, str], qr_text: str | None, ecc: str = "M"
) -> tuple[Image.Image, list[str]]:
    """Full label as an L-mode image at printer resolution (1 px = 1 dot)."""
    canvas = Image.new("L", (mm_to_dots(t.width_mm, t.dpi), mm_to_dots(t.height_mm, t.dpi)), 255)
    warnings: list[str] = []
    for el in t.elements:
        placed, w = rasterize_element(el, t, values, qr_text, ecc)
        warnings += w
        if placed:
            paste_black(canvas, placed)
    return canvas, warnings
