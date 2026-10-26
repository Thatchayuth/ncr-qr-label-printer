# Phase 0 — Discovery Notes

_Last updated: 2026-10-26_

## Confirmed by the business

- **Source table:** `AssetTable` in the Dynamics AX 4.0 SQL Server database.
- **QR content:** the asset's `AssetId` only (plain text, no prefix).
- **Label layout:** QR code with the `AssetId` printed underneath.
- **Media:** sticker labels. Exact size **not provided yet**.
- **Printing:** TE200 connected by USB to the main PC. Other PCs print through the Windows printer share on that PC.
- **Authentication:** SQL Server Authentication.
- **Printer:** not connected yet, so no hardware results exist.

## Assumptions used for development (clearly marked SAMPLE)

| Item | Sample value | Where to change |
|---|---|---|
| Label size | 40 × 30 mm, gap 2 mm, gap media | Template `asset-qr-sample-40x30` (Label Designer, Phase 3) |
| QR size | 20 × 20 mm area, ECC level M | Template / profile QR config |
| AssetId text | 3.4 mm Tahoma Bold, centred | Template |
| Company | user enters DATAAREAID (sample data uses `smp`) | Application Settings → Default company |
| Column names | only `ASSETID` and `DATAAREAID` are assumed (AX system/standard columns) | Data Profile |

No other `AssetTable` columns are assumed. Run `scripts/poc_ax_discover.py` to list the real columns.

## Technical decisions (provisional until hardware tests)

1. **Default render mode = bitmap** for both QR and text.
   - Preview and print use the same pixels, so they match exactly.
   - Thai and any other Unicode text print correctly with Windows fonts (Tahoma / Leelawadee UI).
   - Data never enters a TSPL string, so it cannot inject printer commands.
   - Cost: about 4–5 KB per 40 × 30 mm label, which is small for USB.
2. **Native `QRCODE` / `TEXT`** are available per template (`qr_mode` / `text_mode = native`). They are used only when the value is plain safe ASCII (letters, digits, `-._/:+*$%#=,;@()&?'` and space). Anything else falls back to bitmap automatically. Compare test labels 1 and 2 on real hardware before switching the default.
3. **RAW printing** through the Windows spooler (`win32print`, datatype `RAW`). The TSC driver is only the queue; it does not render. The shared printer path uses the same API with `\\HOST\Share`.
4. **Print state honesty:** `SpoolerAccepted` means Windows accepted the job. It does not mean the sticker printed. After `Failed` or `UnknownDelivery`, the rest of the batch is cancelled and nothing is sent again automatically.
5. **ODBC:** Driver 17 and 18 for SQL Server are installed on the dev PC. AX 4.0 often runs on older SQL Server versions. If Driver 17/18 cannot connect, try the legacy `SQL Server` driver, and keep `Encrypt` off unless the server has a valid certificate.

## Open questions

| # | Question | Needed for |
|---|---|---|
| Q1 | Sticker width × height × gap (mm)? Gap or black mark? | Final template, calibration |
| Q2 | SQL Server name / instance and database name; a read-only SQL login | Phase 0.2 / Phase 2 |
| Q3 | Which DATAAREAID (company) values should operators use? One fixed or selectable? | Search defaults |
| Q4 | Should other columns appear on screen (e.g. asset name, location)? Only for display, or also on the label? | Data Profile |
| Q5 | Which scanner/app reads the QR? Any required prefix or format? | QR config |
| Q6 | Is AssetId ever longer than ~16 characters? (affects text size) | Template |
| Q7 | UI language: Thai, English, or both? | Phase 1.11 |
| Q8 | SQL Server version used by AX 4.0 | ODBC driver choice |

## How to run the Phase 0 checks

### AX (read-only)

```powershell
.venv\Scripts\python scripts\poc_ax_discover.py --server <SERVER> --database <AXDB> --user <readonly_login> [--company <dataareaid>]
```

The script runs SELECT statements only and asks for the password without echoing it.

### Printer

1. Install the TSC TE200 driver on the main PC and connect USB. Calibrate the gap sensor.
2. List queues: `.venv\Scripts\python scripts\poc_print_test.py --list`
3. Generate and send: `.venv\Scripts\python scripts\poc_print_test.py --width <W> --height <H> --gap <G> --printer "<queue name>"`
4. Check the results against [tests/hardware/README.md](../tests/hardware/README.md) and record them below.

## AX discovery results (2026-10-26, test database)

Connected through the app (Application Settings → Test connection) and with a read-only check script.

- Server `NCR176`, database `AX40DB_Test`, **SQL Server 10.50.1600.1 (2008 R2)**. ODBC Driver 17 works with Encrypt off and Trust server certificate on.
- `AssetTable`: 45 columns. Useful candidates for display: `ASSETID`, `NAME`, `ASSETGROUP`, `LOCATION`, `SERIALNUM`, `MAKE`, `MODEL`, `RESPONSIBLE`, `BARCODE`, `NAMEALIAS`, `NCR_DEPRECIATIONGROUP`, `NCR_COSTCATEGORYID`.
- Companies: `db1` 5,997 rows, `db2` 2,517, `db3` 2,517. The default company is set to `db1`.
- Longest `ASSETID` is **17 characters** (e.g. `MACH_EQUIP0000001`). The only character besides A–Z, 0–9 and `-` is `_` (4,140 IDs).
- Changes made after these results:
  - Label text now shrinks automatically to fit its box, down to a minimum size (`auto_fit`). A 17-character ID fits the SAMPLE 40 mm label.
  - `_` was added to the safe set for native TSPL.
- `BARCODE` is empty in every row, so the QR uses `ASSETID` (confirmed).
- Result columns requested by the business (data profile `asset` v3):
  - Fixed asset number = `ASSETID`
  - Name = `NAME`
  - PU No. = `TECHINFO1` (confirmed by the user)
  - PO No. = `TECHINFO2`. This is inferred: 76 rows equal `ASSETBOOK.PURCHID`, and some rows have a PO only here. Some values are multi-line (`PO: …\nPO Date: …`).
  - Created date = `CREATEDDATE`
- Search is available on Fixed asset number, Name, PU No. and PO No.

## Hardware results

_None yet. The printer has not been connected._

## Admin settings lock (2026-10-26)

- Application Settings (AX connection) needs the admin password. It locks again when the page is left or the app restarts.
- The initial admin password was given by the business and is not written in this repository. Only its PBKDF2 hash is stored (`services/admin_auth.py`, then `config.json` → `admin.password_hash` after a change).
- **Change the admin password after installation** (Application Settings → Change admin password).
- After 5 wrong attempts, the unlock is blocked for 30 seconds.
- This is an operator gate, not a security boundary: a Windows user can still edit or delete `config.json`. If `admin.password_hash` is removed, the initial password works again. Real data protection is the read-only SQL login.
