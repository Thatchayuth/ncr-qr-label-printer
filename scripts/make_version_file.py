"""Write a PyInstaller Windows version-resource file from qrlabel.__version__.

Usage: python scripts/make_version_file.py <output-path>
Prints the version so build scripts can reuse it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version() -> str:
    text = (ROOT / "src" / "qrlabel" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text)
    if not m:
        raise SystemExit("Cannot read __version__ (expected MAJOR.MINOR.PATCH)")
    return ".".join(m.groups())


TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'NCR'),
      StringStruct('FileDescription', 'NCR QR Label Printer'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'NCRQRLabelPrinter'),
      StringStruct('OriginalFilename', 'NCRQRLabelPrinter.exe'),
      StringStruct('ProductName', 'NCR QR Label Printer'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    v = read_version()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    t = ", ".join(v.split(".") + ["0"])
    out.write_text(TEMPLATE.format(v=v, t=t), encoding="utf-8")
    print(v)


if __name__ == "__main__":
    main()
