# NCR QR Label Printer — Phases

Status legend: ✅ done · 🟡 in progress / partly done · ⬜ not started · ⛔ blocked on hardware or information

Confirmed business facts (2026-10-26):

| Item | Value |
|---|---|
| AX source | `AssetTable` (Dynamics AX 4.0, SQL Server) |
| QR content | `AssetId` (plain text) |
| Label text | `AssetId` printed below the QR |
| Media | Sticker labels; **size not yet measured** (development uses SAMPLE 40 × 30 mm, gap 2 mm) |
| Printer connection | TE200 on **USB** at the main PC; other PCs print through the **Windows shared printer** on the main PC |
| DB authentication | SQL Server Authentication |
| Printer status | **Not connected yet** — no hardware test has been executed |

---

## Phase 0 — Discovery and Hardware Proof of Concept 🟡

**Objective:** Prove we can read `AssetTable` read-only and print a scannable QR + AssetId sticker on the TE200, and record the facts the later phases depend on.

| # | Task | Status | Depends on |
|---|---|---|---|
| 0.1 | Record confirmed requirements and open questions ([docs/phase0-discovery.md](docs/phase0-discovery.md)) | ✅ | — |
| 0.2 | AX discovery — connect read-only, list `AssetTable` columns, rows per DATAAREAID, sample/longest ASSETID ([scripts/poc_ax_discover.py](scripts/poc_ax_discover.py)) | ✅ done on `AX40DB_Test` 2026-10-26 (results in discovery notes) | — |
| 0.3 | TSPL PoC generator — 5 test labels as `.prn` + preview `.png`, optional RAW send ([scripts/poc_print_test.py](scripts/poc_print_test.py)) | ✅ written & files generated · ⛔ not printed | — |
| 0.4 | Run test labels on TE200 via USB queue | ⛔ | printer + driver installed |
| 0.5 | Run test labels via `\\MAIN-PC\Share` from a second PC | ⛔ | 0.4, printer shared |
| 0.6 | Decide default QR mode (bitmap vs native `QRCODE`) and text mode from physical results | ⛔ | 0.4 |
| 0.7 | Measure real sticker width / height / gap; check gap vs black-mark | ⛔ | sticker roll |

**Acceptance tests**
- `poc_ax_discover.py` prints the column list and sample ASSETIDs with a read-only login. *(not yet executed)*
- Test label 1 (bitmap) and 2 (native) print and scan correctly with the site's scanner/phone. *(not yet executed)*
- Test label 3 shows a **black** square (bitmap polarity correct). *(not yet executed)*
- Test label 5 border is fully on the sticker and does not drift over 20 labels. *(not yet executed)*

**Completion criteria:** all four acceptance tests pass and decisions 0.6/0.7 are written into `docs/phase0-discovery.md`.

---

## Phase 1 — Project Foundation and UI Shell 🟡 (foundation done)

**Objective:** A runnable desktop app with the layered architecture, local storage, configuration, logging, sample data and sample printer, so all later work can be built and tested without hardware.

| # | Task | Status |
|---|---|---|
| 1.1 | Project structure, pinned dependencies, git, pytest config | ✅ |
| 1.2 | Domain models + interfaces (`IDataSourceRepository`, `IQueryProfileRepository`, `ILabelTemplateRepository`, `IQrPayloadBuilder`, `ILabelRenderer`, `IPrinterAdapter`, `IPrintJobRepository`, `IConfigurationService`) | ✅ |
| 1.3 | Config in `%LOCALAPPDATA%\NCR\QRLabelPrinter\config.json` — JSON-schema validation, atomic write, migration with backup, DPAPI password, safe import/export | ✅ |
| 1.4 | SQLite: versioned profiles/templates, print jobs + status events, schema migrations | ✅ |
| 1.5 | Rotating structured log (user, version, correlation/job IDs, no secrets) | ✅ |
| 1.6 | Mock AX data source + sample printer (.prn files) | ✅ |
| 1.7 | UI shell: 8 pages, light theme, Qt thread-pool workers, high-DPI | ✅ |
| 1.8 | Working Search & Print page on sample data (search → select → preview → print → history) | ✅ |
| 1.9 | Application Settings (DB connection + test), Printer Settings (USB/shared/TCP + test print), History, Diagnostics | ✅ |
| 1.10 | PyInstaller onedir build script | ✅ ([scripts/build.ps1](scripts/build.ps1)) |
| 1.11 | Thai UI language (labels/messages) | ⬜ decision needed |

**Acceptance tests (executed 2026-10-26 on the dev PC)**
- `pytest` — 63 unit + integration tests pass.
- Offscreen UI smoke test: search sample data, select 2 rows, print to sample printer → 2 `.prn` files and 2 history rows.

**Completion criteria:** remaining item 1.11 decided; app launched manually on a clean user account.

---

## Phase 2 — AX Database Access and Dynamic Data Profiles ⬜

**Depends on:** Phase 0.2 run against the real database (column list of `AssetTable`).

| # | Task |
|---|---|
| 2.1 | Run `SqlServerDataSource` against AX with a `db_datareader` login; tune timeouts; confirm DATAAREAID values |
| 2.2 | Data Profile editor: pick approved source → discover columns → choose search / display / QR / label fields, aliases, types, formats, defaults, sort, row limit |
| 2.3 | Profile versioning in the UI (save = new version; history of versions) |
| 2.4 | Approved Query Mode: DBA-provided views / stored procedures with declared parameters (whitelist) |
| 2.5 | Integration tests against a test SQL Server database (never production) |

**Acceptance:** search returns the same rows as an equivalent query run by the AX/DB team; no non-SELECT statement is possible; wrong password / unreachable server / timeout show friendly messages.

---

## Phase 3 — QR Payload Engine and Label Designer ⬜ (engine ✅, editors ⬜)

Already implemented and tested: payload builder (plain / delimited / JSON, prefix/suffix, null rules, byte limit, Unicode), shared raster renderer, TSPL renderer, template validation.

| # | Task |
|---|---|
| 3.1 | QR Configuration page: field order, format, delimiter, ECC, live payload preview, test-decode |
| 3.2 | Label Designer (Qt Graphics View): mm canvas, zoom, grid/snap, drag/resize, text/QR/rect/line, rotation, font size/bold, margin & overflow checks |
| 3.3 | Template save / duplicate / import / export (JSON), versioning |
| 3.4 | Set the real sticker size from Phase 0.7 as the default template |

**Acceptance:** preview vs printed sticker within ±0.5 mm on the TE200; QR scans; overflow is flagged before printing.

---

## Phase 4 — TSC Printer Adapters and Print History 🟡 (adapters + history written, hardware ⛔)

Already implemented: Windows spooler (USB), shared printer (`\\HOST\Share`), RAW TCP 9100, sample printer; status model Pending → Submitting → SpoolerAccepted / SubmittedToDevice / Failed / UnknownDelivery / Cancelled; stop-after-failure; duplicate correlation IDs refused.

| # | Task |
|---|---|
| 4.1 | Hardware tests of USB and shared printing (tests/hardware) |
| 4.2 | Queue monitoring: read spooler job state after submit; cancel pending spool jobs |
| 4.3 | Reprint from history with mandatory reason → new job linked by `parent_job_id` |
| 4.4 | Operator confirmation flow for `UnknownDelivery` |
| 4.5 | Continuous-print test (e.g. 200 labels), density/speed tuning |

**Acceptance:** USB and shared printing work; no history row claims success that did not happen; reprints are linked.

---

## Phase 5 — Windows Packaging, Installer, and UAT ⬜

| # | Task |
|---|---|
| 5.1 | Inno Setup script: per-user install, optional admin mode, Start Menu + optional desktop shortcut, uninstaller with "delete user data?" choice, upgrade keeps settings |
| 5.2 | First-run wizard (DB connection → printer → test print) |
| 5.3 | App icon, version info, CHANGELOG |
| 5.4 | Installation, operator and troubleshooting guides |
| 5.5 | UAT on a clean Windows 10 and Windows 11 PC without Python |

**Acceptance:** Setup.exe installs/uninstalls cleanly on a PC without Python; all Masterplan §16 criteria pass.
