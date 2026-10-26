# Build NCR QR Label Printer: tests -> icon -> PyInstaller (onedir) -> Inno Setup installer.
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1            # full build
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -NoInstaller
# Output:
#   dist\NCRQRLabelPrinter\NCRQRLabelPrinter.exe
#   dist\installer\NCR-QR-Label-Printer-Setup-<version>.exe
param([switch]$NoInstaller, [switch]$SkipTests)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Missing .venv. Run: py -3.12 -m venv .venv; .venv\Scripts\python -m pip install -r requirements-dev.txt"
}

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

if (-not $SkipTests) {
    Step "Tests"
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed - build stopped." }
}

Step "Icon and version resource"
& $py scripts\make_icon.py
$version = (& $py scripts\make_version_file.py build\version_info.txt).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Could not read the application version." }
Write-Host "Version $version"

Step "PyInstaller"
& $py -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name NCRQRLabelPrinter `
    --icon src\qrlabel\resources\app.ico `
    --version-file build\version_info.txt `
    --add-data "src\qrlabel\resources;qrlabel\resources" `
    --paths src `
    --exclude-module cv2 --exclude-module numpy --exclude-module pytest `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtPdf `
    src\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "Built: $root\dist\NCRQRLabelPrinter\NCRQRLabelPrinter.exe"

if ($NoInstaller) { return }

Step "Inno Setup"
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup --scope user" }
& $iscc "/DAppVersion=$version" installer\NCRQRLabelPrinter.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
Write-Host "Installer: $root\dist\installer\NCR-QR-Label-Printer-Setup-$version.exe" -ForegroundColor Green
