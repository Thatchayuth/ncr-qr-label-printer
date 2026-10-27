# Changelog

## Unreleased

- The app always uses its light look, also when Windows is in dark mode. Dialogs, lists, tables and menus showed dark text on a dark background before.

- Phase 6: labels bound to data profiles.
  - Data Profiles has a Labels card to tick the allowed labels and pick the default; it warns when a label prints fields the profile does not have.
  - Search & Print lists only the allowed labels and marks the default with ★.
  - Label Designer shows "Used by" and has a "Use with profiles..." button.
  - Older profiles with no ticked labels still allow every label.
  - Saving a profile that was changed elsewhere in the meantime is refused, so the other change is not silently overwritten.

- Renamed to **NCR Print Label**: installer, Start Menu / desktop shortcuts, Apps list, install folder, `NCRPrintLabel.exe`, window, splash and sidebar. AppId, the single-instance mutex and the user data folder are unchanged, so installing over the old "NCR QR Label Printer" upgrades it, keeps settings and removes the old exe and shortcuts.

- Company (DATAAREAID) moved from the search form to the sidebar, under the AX LIVE badge. Click it to pick a company from AX: names come from DATAAREA, virtual companies are hidden, and each shows its number of assets. The choice is saved, and changing it clears the old results.

- Redesigned date picker: all day numbers visible, weekday header, chevron navigation, rounded blue selected day, today in bold blue, weekends in red, other months greyed.

- Fixed QR size: a QR element can use a fixed QR version, so every label has the same QR size (it grows only when the data does not fit, with a warning). The Label Designer lists each version with its printed size and byte capacity. Fixed sizes always print as bitmap.

- Search results have a tick column, and only the tick box decides what is printed. Clicking a row only previews it. Ticked rows are tinted green. Space ticks the highlighted row, and the ✓ header, Tick all and Untick all work on every row.

- Data Profiles editor (admin password required):
  - Create, duplicate, import, export and version data profiles.
  - Choose any AX table or DBA view (searchable list of tables and views; the choice is added to the approved sources).
  - Add fields from the discovered columns, with header, type, format, search, date range, show, required and fallback settings; reorder fields.
  - Add related tables (one row per main row, link columns, "pick first by").
  - Test query shows the first 20 rows and the generated SQL.
  - Saving is refused when columns are missing, ntext columns are searched or sorted, or the QR uses removed fields.
- Search & Print shows newly created profiles without restarting.

- Printer choice is now a drop-down of real printers only. PDF, XPS, OneNote and Fax are hidden, label printers (TSC, Zebra, …) are listed first, and other printers show a warning. The same drop-down is used in Printer Settings and the setup wizard.
- Supports TSC TE210 (203 dpi, same as TE200; confirmed from the Windows driver).

- The installer ships the label template "New label" (38.1 × 38.1 mm, from v14 on the design PC). A new installation uses it as the default template for the Asset profile.

- Label Designer: Image element for logos/pictures (PNG/JPG/BMP/GIF; stored in the template; fitted with aspect ratio; black/white or dithered), Alt+6.
- Label Designer: smart guides - while dragging, an element snaps to the label centre and to other elements' centres, shown with pink guide lines.

- QR content now matches the previous application: one "Label : value" per line (Asset code, Name, Acquisition date, Acquisition, Department, Purchase order), CR+LF between lines, error correction L. New QR format "Labeled lines" with editable QR labels and separators in QR Configuration.
- Warning when QR dots are smaller than 3 printer dots (hard to scan) in preview, designer and print.

- PO No. now comes from `AssetBook.PurchId` as in the previous application, with `TechInfo2` used when PurchId is empty.
- New columns from AssetBook: Department (Dimension), Acquisition date (with From–To filter) and Acquisition price (`#,##0.00`).
- Data profiles can read one row per asset from a related table (`OUTER APPLY TOP 1`) with a chosen order, and can fall back to another column.
- Config v2 migration adds `AssetBook` to the approved sources.
- Search results: Name column has a fixed width that can be resized, and numbers are right-aligned.
- Startup splash screen.
- Setup wizard: removed the stray back-arrow button.

## 0.9.0 — 2026-10-26 (release candidate for UAT)

- Windows installer (Inno Setup): per-user or all-users, shortcuts, keeps data on upgrade, asks before deleting data on uninstall.
- First-run setup wizard (admin password, AX connection test, printer + test label).
- App icon, exe version info, only one copy can run at a time.
- Admin password gate for Application Settings.
- Label Designer: Layers panel.
- Guides: installation, user guide, troubleshooting (Thai), UAT checklist.

## Phase 4

- Print History rebuilt: filters (date, status, text), needs-attention highlight, details with timeline and reprint links, CSV export.
- Reprint with required reason, identical data and original template/profile versions, linked to the original job.
- Operator can mark a job as printed / not printed (UnknownDelivery follow-up).
- Check the Windows print queue for a job and cancel it while it is still waiting.
- Database schema v2: stores the label values of each job (automatic migration with backup).
- Search: ranges (`A..B`) and lists (`A, B, C` or pasted lines) in text fields.
- Label Designer: keyboard shortcuts, undo/redo, copy/paste/duplicate.

## Phase 3

- Label Designer page: mm canvas drawn with the print renderer, drag/resize/snap/nudge, Field/Text/QR/Box/Line, label settings, validation, New/Duplicate/Import/Export/Revert/Save (versioned).
- QR Configuration page: choose and order QR fields, format, separator, prefix/suffix, ECC, max length; live preview; test with a real AX record; decode check.
- Search & Print picks up newly saved template/profile versions without clearing the search.
- Redesigned UI (dark sidebar with icons, two-column search, sticker-style preview).
- Asset profile: Name, PU No. (TECHINFO1), PO No. (TECHINFO2), Created date with From–To filter (dd/MM/yyyy).

## 0.1.0 — 2026-10-26 (development, not released)

- Phase 0: discovery notes, AX read-only discovery script, TE200 TSPL test-label generator.
- Phase 1 foundation: layered project, config (JSON schema, DPAPI password, atomic writes), SQLite history and versioned profiles/templates, rotating log, sample AX data, sample printer.
- QR payload engine (plain / delimited / JSON) and TSPL renderer (bitmap default, safe native fallback).
- Printer adapters: Windows spooler (USB), Windows shared printer, RAW TCP 9100, sample printer.
- UI: Search & Print, Printer Settings, Application Settings, Print History, Diagnostics; read-only views for Data Profiles, QR Configuration, Label Designer.
