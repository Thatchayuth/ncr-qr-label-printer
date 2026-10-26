# Build NCR QR Label Printer (PyInstaller onedir). Run from any folder:
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# Output: dist\NCRQRLabelPrinter\NCRQRLabelPrinter.exe
# The Inno Setup installer (Phase 5) packages that folder.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Missing .venv. Run: py -3.12 -m venv .venv; .venv\Scripts\python -m pip install -r requirements-dev.txt"
}

& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - build stopped." }

& $py -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name NCRQRLabelPrinter `
    --paths src `
    --exclude-module cv2 --exclude-module numpy --exclude-module pytest `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtPdf `
    src\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "Built: $root\dist\NCRQRLabelPrinter\NCRQRLabelPrinter.exe"
