# Changelog

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
