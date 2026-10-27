"""Images (logos) stored inside label templates as base64 PNG.

Images are flattened onto white and stored in greyscale: the label printer prints black
dots only, so colour would just make the template bigger.
"""
from __future__ import annotations

import base64
import binascii
import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..domain.errors import ValidationError

MAX_SIDE_PX = 800  # plenty for a sticker: 800 px = 100 mm at 203 dpi
MAX_ENCODED_CHARS = 600_000
SUPPORTED = "*.png *.jpg *.jpeg *.bmp *.gif"


def _to_grey_png(im: Image.Image) -> str:
    im = ImageOps.exif_transpose(im)
    rgba = im.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    grey = Image.alpha_composite(white, rgba).convert("L")
    grey.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    grey.save(buf, format="PNG", optimize=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    if len(data) > MAX_ENCODED_CHARS:
        raise ValidationError("The image is too detailed. Use a simpler or smaller logo.")
    return data


def load_image_file(path: Path) -> tuple[str, int, int]:
    """Read an image file -> (base64 PNG, width px, height px)."""
    try:
        with Image.open(path) as im:
            im.load()
            data = _to_grey_png(im)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValidationError(f"Cannot open this image: {e}") from None
    img = decode_image(data)
    return data, img.width, img.height


@lru_cache(maxsize=32)
def decode_image(data: str) -> Image.Image:
    """base64 PNG -> greyscale image. Raises ValidationError for damaged data."""
    try:
        raw = base64.b64decode(data, validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            return im.convert("L")
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as e:
        raise ValidationError(f"Image data in the template is damaged: {e}") from None
