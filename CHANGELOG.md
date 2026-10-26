# Changelog

## Unreleased — Phase 3

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
