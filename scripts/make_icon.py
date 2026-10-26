"""Generate the application icon (src/qrlabel/resources/app.ico + app.png).

Blue-to-indigo rounded square with a white QR-style mark, matching the sidebar logo.
Run: .venv\\Scripts\\python scripts\\make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "qrlabel" / "resources"
SIZE = 256


def draw_icon(size: int = SIZE) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # diagonal gradient #3B82F6 -> #6366F1
    grad = Image.new("RGBA", (s, s))
    px = grad.load()
    a, b = (0x3B, 0x82, 0xF6), (0x63, 0x66, 0xF1)
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * (s - 1))
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    u = s / 16  # grid unit; mark spans 3..13
    lw = max(1, round(u * 0.9))

    def finder(cx: float, cy: float) -> None:
        d.rounded_rectangle([cx, cy, cx + 3.6 * u, cy + 3.6 * u], radius=u * 0.6, outline=white, width=lw)
        d.rounded_rectangle([cx + 1.25 * u, cy + 1.25 * u, cx + 2.35 * u, cy + 2.35 * u], radius=u * 0.25, fill=white)

    finder(3 * u, 3 * u)
    finder(9.4 * u, 3 * u)
    finder(3 * u, 9.4 * u)
    for gx, gy in [(9.6, 9.6), (11.6, 9.6), (9.6, 11.6), (12.0, 12.0), (10.8, 10.8), (7.6, 4.2), (7.6, 7.6), (4.2, 7.6)]:
        d.rounded_rectangle([gx * u, gy * u, (gx + 1.2) * u, (gy + 1.2) * u], radius=u * 0.25, fill=white)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw_icon(SIZE)
    big.save(OUT / "app.png")
    big.save(OUT / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {OUT / 'app.ico'} and {OUT / 'app.png'}")


if __name__ == "__main__":
    main()
