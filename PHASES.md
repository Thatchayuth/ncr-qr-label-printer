# NCR Print Label — Phases

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

## Phase 2 — AX Database Access and Dynamic Data Profiles ✅ (editor added 2026-10-27)

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

## Phase 3 — QR Payload Engine and Label Designer 🟡 (software done, hardware check ⛔)

Engine: payload builder (plain / delimited / JSON, prefix/suffix, null rules, byte limit, Unicode), shared raster renderer, TSPL renderer, template validation, auto-fit text.

| # | Task | Status |
|---|---|---|
| 3.1 | QR Configuration page: tick/order fields, format, separator, prefix/suffix, empty-field rule, ECC, max bytes, live preview, test with a real AX record, decode check (when OpenCV is present), save as new profile version | ✅ |
| 3.2 | Label Designer: mm canvas, zoom (Ctrl+wheel, fit), grid, snap 0.1/0.5/1 mm, drag/resize, arrow-key nudge, Field/Text/QR/Box/Line, rotation, font size/bold/align/shrink-to-fit, alignment helpers, margin & overflow checks, label settings (size, gap, media, density, speed, direction, QR/text output mode) | ✅ |
| 3.3 | Template New / Duplicate / Import / Export (JSON) / Revert; Save = new version; invalid layouts cannot be saved | ✅ |
| 3.4 | Set the real sticker size from Phase 0.7 as the default template | ⛔ waiting for sticker size |

**Tests (executed 2026-10-26):** 78 automated tests pass (adds template import/export/duplicate/snap). Offscreen UI run: edit + add line + snap + save → template v2 picked up by Search & Print; QR page decodes its own QR.

**Acceptance still open:** preview vs printed sticker within ±0.5 mm on the TE200 (needs printer). Not included: undo/redo, multi-select alignment, images/logos.

---

## Phase 4 — TSC Printer Adapters and Print History 🟡 (software done, hardware ⛔)

Already implemented: Windows spooler (USB), shared printer (`\\HOST\Share`), RAW TCP 9100, sample printer; status model Pending → Submitting → SpoolerAccepted / SubmittedToDevice / Failed / UnknownDelivery / Cancelled; stop-after-failure; duplicate correlation IDs refused.

| # | Task | Status |
|---|---|---|
| 4.1 | Hardware tests of USB and shared printing (tests/hardware) | ⛔ printer not connected |
| 4.2 | Queue monitoring: "Check queue" reads the Windows job and printer status flags; "Cancel in queue" removes a waiting job and records Cancelled (refused if the job already left the queue) | ✅ (checked against a real Windows queue; not yet with TE200) |
| 4.3 | Reprint from history: reason required, same data snapshot + original profile/template versions, new job linked by `parent_job_id`, stops after a failed/unknown job, multi-select | ✅ |
| 4.4 | Operator marks: UnknownDelivery / SpoolerAccepted → ConfirmedPrinted or Failed, with note and user in the timeline | ✅ |
| 4.5 | History page: date/status/text filters, "needs attention" filter and highlight, details panel with timeline and reprint links, CSV export (UTF-8 BOM for Thai in Excel) | ✅ |
| 4.6 | Continuous-print test (e.g. 200 labels), density/speed tuning | ⛔ printer not connected |

**Tests (executed 2026-10-26):** 97 automated tests (adds DB migration v1→v2, reprint, operator marks, queue cancel, filters, status texts). Offscreen UI run: 3 prints → reprint 2 with reason → mark unknown as printed → filter → CSV export.

Note: jobs printed before this version have no data snapshot and cannot be reprinted from history (search and print them again).

**Acceptance:** USB and shared printing work; no history row claims success that did not happen; reprints are linked.

---

## Phase 5 — Windows Packaging, Installer, and UAT 🟡 (installer built and tested on the dev PC; UAT ⛔)

| # | Task | Status |
|---|---|---|
| 5.1 | Inno Setup script ([installer/NCRPrintLabel.iss](installer/NCRQRLabelPrinter.iss)): per-user by default, optional all-users, Start Menu + optional desktop shortcut, closes a running copy (AppMutex), removes the old `_internal` folder on upgrade, keeps user data, uninstall asks before deleting user data (default No) | ✅ |
| 5.2 | First-run wizard: admin password → AX connection (Test connection must pass) or sample data → printer (USB / shared / none) + test label → summary | ✅ |
| 5.3 | App icon, exe version resource, single-instance guard, version 0.9.0 | ✅ |
| 5.4 | Guides: [INSTALL](docs/INSTALL.md), [USER_GUIDE](docs/USER_GUIDE.md), [TROUBLESHOOTING](docs/TROUBLESHOOTING.md) (Thai), [UAT checklist](docs/UAT.md) | ✅ |
| 5.5 | UAT on clean Windows 10 / 11 PCs without Python, with the TE200 | ⛔ needs test PCs and the printer |

**Build:** `scripts/build.ps1` runs tests → icon/version → PyInstaller onedir (131 MB) → `dist/installer/NCR-Print-Label-Setup-0.9.0.exe` (38 MB).

**Executed on the dev PC (2026-10-26):**
- Silent per-user install to a test folder created the exe, uninstaller, Start Menu shortcut and Apps entry.
- File version is 0.9.0. The installed app starts, and a second copy does not start.
- Silent uninstall removed the program, the shortcut and the Apps entry, and left the user data folder untouched.
- Wizard tested offscreen: wrong password refused, AX requires a passed test, sample-printer test label works, settings saved.

**Not yet executed:** interactive uninstall prompt, "install for all users" mode, upgrade over a running copy, clean-PC install, anything with the TE200.

**Acceptance:** Setup.exe installs/uninstalls cleanly on a PC without Python; all Masterplan §16 criteria pass.

---

# Extension plan (agreed 2026-10-27)

Facts from AX (read-only checks): InventJournalTrans has 2,008,396 rows in db1. Voucher and ItemId searches take 60–450 ms, including "contains". InventDim and InventTable are stored in the virtual company VIR, which covers DAT, DB1, DB2 and DB3. JournalError links by REFTABLEID = 154 + JournalId + LineNum, and only 60 lines have errors. INFOLOG is binary, so only "has error" can be shown.

| Phase | Goal | Estimate | Depends on |
|---|---|---|---|
| 6 ✅ | Bind label templates to data profiles: allowed list + default; Search & Print shows only allowed labels; designer "Use with profiles"; warnings for fields a template needs | done 2026-10-27 | — |
| 7 ✅ | Search options per field (exact / starts with / contains), "at least one search value" option, field order (follows Move up/down) | done 2026-10-27 | — |
| 8 | Inventory Journal profile: related-table company = same / virtual (VIRTUALDATAAREALIST) / none, fixed-value conditions (REFTABLEID = 154), "has rows" fields; InventJournalTrans + InventDim + InventTable + JournalError; QR + template | 1.5–2 days | 6, 7, answers on label content |
| 9 | Installer choices: role (operator / administrator) and modules (Asset / Inventory journal); hide menus and profiles; admin can change later | 1–1.5 days | 8 |
| 10 | TE210 hardware tests, UAT, ship the fixed-QR template, release 1.0.0 | ~1 day + team testing | all (hardware tests can start now) |

Out of scope: per-user login or permissions (Masterplan §15 "User Management Server"), decoding JournalError INFOLOG, and writing anything back to AX.

## Phase 8 decisions (user answers + AX checks, 2026-10-27)

Label (like the "STOCK" sample): `STOCK เกรด [InventSizeId]` / `รหัสสินค้า : [ItemId]  [Qty] [Unit]` / `ชื่อสินค้า : [Item name]` / `Batch No : [InventBatchId]` + Note.

| Label item | AX source (checked read-only) |
|---|---|
| Grade (A) | INVENTDIM.INVENTSIZEID (company `vir`, by INVENTDIMID) |
| Item code | INVENTJOURNALTRANS.ITEMID |
| Qty | INVENTJOURNALTRANS.QTY. Transfer lines are always negative and can have decimals, so the label shows the absolute value |
| Unit (EA / Kg) | INVENTTABLEMODULE.UNITID where MODULETYPE = 0 (Invent), company `vir` |
| Item name | INVENTTABLE.ITEMNAME (company `vir`). INVENTDIMCOMBINATION.NAME has text for only 227 rows, so it is only used as a fallback |
| Batch No | INVENTDIM.INVENTBATCHID |
| Note | INVENTJOURNALTRANS.NOTES |
| Other InventDim fields | All of them can be added (location, warehouse location, serial, config, colour) |

- Transfer journals only: fixed filter JOURNALTYPE = 2. Checked: INVENTJOURNALTABLE type 2 is described as "Transfer journal".
- Number of labels: one label per journal line. Copies = Qty is not possible because Qty can be decimal (e.g. 5.99 Kg). The user can still set copies when printing.
- JournalError: not used for now.
- Phase 9 addition: admin-only buttons and pages are hidden. An admin icon unlocks them after the password is entered.
