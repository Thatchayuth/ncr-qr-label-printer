"""Phase 0 - TSC TE200 hardware proof of concept.

Generates test labels as TSPL (.prn) files and, if --printer is given, sends them
RAW to a Windows print queue (USB queue or \\\\HOST\\Share).

Test labels:
  1_bitmap_qr_text   - default mode: QR + AssetId both as BITMAP (preview == print)
  2_native_qr_text   - native QRCODE + native TEXT (compare sharpness / size)
  3_polarity_check   - black square top-left + text; verifies BITMAP bit polarity
  4_thai_bitmap      - Thai text as bitmap (font support check)
  5_edges            - 1 mm border box; checks label size, gap and offset

Usage:
    .venv\\Scripts\\python scripts\\poc_print_test.py --list
    .venv\\Scripts\\python scripts\\poc_print_test.py --width 40 --height 30 --gap 2
    .venv\\Scripts\\python scripts\\poc_print_test.py --printer "TSC TE200" --only 1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from qrlabel.app.defaults import default_asset_template  # noqa: E402
from qrlabel.domain.layout import mm_to_dots  # noqa: E402
from qrlabel.domain.models import LabelElement  # noqa: E402
from qrlabel.infrastructure.printing.adapters import (  # noqa: E402
    WindowsSharedPrinterAdapter,
    WindowsSpoolerAdapter,
    list_windows_printers,
)
from qrlabel.rendering.raster import Placed, render_label_image  # noqa: E402
from qrlabel.rendering.tspl import CRLF, TsplRenderer, bitmap_command  # noqa: E402

ASSET_ID = "TEST-FA-000123"


def build_tests(width: float, height: float, gap: float) -> dict[str, tuple[bytes, Image.Image | None]]:
    r = TsplRenderer()
    base = default_asset_template()
    base.width_mm, base.height_mm, base.gap_mm = width, height, gap
    # scale the sample layout to the requested size
    sx, sy = width / 40.0, height / 30.0
    for e in base.elements:
        e.x_mm, e.w_mm, e.y_mm, e.h_mm = e.x_mm * sx, e.w_mm * sx, e.y_mm * sy, e.h_mm * sy
    q = base.elements[0]
    side = min(q.w_mm, q.h_mm)
    q.x_mm, q.w_mm, q.h_mm = (width - side) / 2, side, side
    values = {"ASSETID": ASSET_ID}
    out: dict[str, tuple[bytes, Image.Image | None]] = {}

    data, w = r.render_job(base, [(values, ASSET_ID)], copies=1)
    out["1_bitmap_qr_text"] = (data, render_label_image(base, values, ASSET_ID)[0])

    native = default_asset_template()
    native.__dict__.update({k: v for k, v in base.__dict__.items() if k != "elements"})
    native.elements = [LabelElement(**e.__dict__) for e in base.elements]
    native.qr_mode, native.text_mode = "native", "native"
    out["2_native_qr_text"] = (r.render_job(native, [(values, ASSET_ID)], copies=1)[0], None)

    square = Image.new("1", (mm_to_dots(8), mm_to_dots(8)), 0)
    text_t = default_asset_template()
    text_t.width_mm, text_t.height_mm, text_t.gap_mm = width, height, gap
    text_t.elements = [LabelElement(kind="text", x_mm=11, y_mm=2, w_mm=width - 13, h_mm=8, font_mm=3,
                                    text="<- SQUARE MUST BE BLACK")]
    body = r.header(text_t) + b"CLS" + CRLF + bitmap_command(Placed(square, mm_to_dots(2), mm_to_dots(2)))
    body += r.label_commands(text_t, {}, None, 1)[0].replace(b"CLS" + CRLF, b"", 1)
    out["3_polarity_check"] = (body, None)

    thai = default_asset_template()
    thai.width_mm, thai.height_mm, thai.gap_mm = width, height, gap
    thai.elements = [LabelElement(kind="text", x_mm=1.5, y_mm=3, w_mm=width - 3, h_mm=8, font_mm=4,
                                  text="ทดสอบภาษาไทย", align="center"),
                     LabelElement(kind="text", x_mm=1.5, y_mm=12, w_mm=width - 3, h_mm=8, font_mm=3.5,
                                  text="สินทรัพย์ 123", align="center", bold=True)]
    out["4_thai_bitmap"] = (r.render_job(thai, [({}, None)], copies=1)[0], render_label_image(thai, {}, None)[0])

    edge = default_asset_template()
    edge.width_mm, edge.height_mm, edge.gap_mm = width, height, gap
    edge.elements = [LabelElement(kind="rect", x_mm=1, y_mm=1, w_mm=width - 2, h_mm=height - 2, thickness_mm=0.3),
                     LabelElement(kind="text", x_mm=2, y_mm=height / 2 - 2, w_mm=width - 4, h_mm=5, font_mm=3,
                                  text=f"{width:g} x {height:g} mm gap {gap:g}", align="center")]
    out["5_edges"] = (r.render_job(edge, [({}, None)], copies=1)[0], render_label_image(edge, {}, None)[0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list Windows printers and exit")
    ap.add_argument("--width", type=float, default=40.0, help="label width mm (SAMPLE default 40)")
    ap.add_argument("--height", type=float, default=30.0, help="label height mm (SAMPLE default 30)")
    ap.add_argument("--gap", type=float, default=2.0, help="gap between labels mm")
    ap.add_argument("--out", default="out/poc", help="folder for .prn and preview .png files")
    ap.add_argument("--printer", help=r'Windows printer name or \\HOST\Share to send to')
    ap.add_argument("--only", help="comma-separated test numbers to send, e.g. 1,3")
    args = ap.parse_args()

    if args.list:
        for name in list_windows_printers():
            print(name)
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tests = build_tests(args.width, args.height, args.gap)
    wanted = set(args.only.split(",")) if args.only else None
    adapter = None
    if args.printer:
        adapter = WindowsSharedPrinterAdapter(args.printer) if args.printer.startswith("\\\\") else WindowsSpoolerAdapter(args.printer)
        print(adapter.test_connection())

    for name, (data, preview) in tests.items():
        (out_dir / f"{name}.prn").write_bytes(data)
        if preview is not None:
            preview.save(out_dir / f"{name}.png")
        line = f"{name}: {len(data)} bytes -> {out_dir / (name + '.prn')}"
        if adapter and (wanted is None or name.split("_")[0] in wanted):
            result = adapter.send(data, f"QRLabel POC {name}")
            line += f" | {result.status.value} {result.message}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
