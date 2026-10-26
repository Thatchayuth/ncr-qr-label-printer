# NCR QR Label Printer

Windows desktop app that searches **Dynamics AX 4.0** (`AssetTable`, read-only) and prints **QR + AssetId** stickers on a **TSC TE200** (USB or Windows shared printer).

Status: **development (Phase 0 / Phase 1)**. See [PHASES.md](PHASES.md) and [docs/phase0-discovery.md](docs/phase0-discovery.md).

## Developer setup

Requires Windows 10/11 x64 and Python 3.12.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest            # unit + integration tests
.venv\Scripts\python src\main.py          # run the app
```

The app starts in **SAMPLE DATA** mode with a **sample printer** that writes `.prn` files, so no database or printer is needed. Switch to AX in *Application Settings* and to the TE200 in *Printer Settings*.

Build an exe folder (no Python needed on the target PC):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

## Where things are stored

`%LOCALAPPDATA%\NCR\QRLabelPrinter\`

- `config.json`: settings. The SQL password is stored only as a Windows DPAPI blob.
- `qrlabel.sqlite3`: data profiles, label templates, print history.
- `logs\qrlabel.log`: rotating log. Passwords and connection strings are never logged.
- `mock_prints\`: output of the sample printer.

## Layout

```
src/main.py                       entry point
src/qrlabel/domain/               models, interfaces, layout validation, errors
src/qrlabel/services/             query builder, QR payload, formatting, print orchestration
src/qrlabel/rendering/            shared raster renderer (preview + BITMAP) and TSPL renderer
src/qrlabel/infrastructure/ax/    SQL Server (pyodbc, read-only) and sample data source
src/qrlabel/infrastructure/printing/  spooler / shared / TCP / sample adapters
src/qrlabel/infrastructure/storage/   SQLite database + repositories
src/qrlabel/infrastructure/security/  DPAPI
src/qrlabel/ui/                   PySide6 pages, theme, background workers
scripts/                          Phase 0 PoC scripts, build script
tests/unit, tests/integration     automated tests
tests/hardware                    manual printer checklist
```

## Safety rules built into the code

- Only `SELECT` statements are compiled. Identifiers are validated against a whitelist and the discovered columns, and every value is bound as a parameter.
- AX data reaches the printer as bitmap pixels by default. Native TSPL text is used only for a strict safe-ASCII set.
- After a failed or uncertain send, the batch stops and nothing is resent automatically.
