# Hardware test checklist (manual)

These tests need a real TSC TE200 and are **not** run by `pytest`.
Record date, PC, printer firmware version, driver version and result for each test.

| # | Test | How | Pass when |
|---|---|---|---|
| H1 | USB queue reachable | Printer Settings → Windows printer → Test connection | Shows driver/port, no error |
| H2 | Bitmap label | `poc_print_test.py --printer "<queue>" --only 1` | QR scans as `TEST-FA-000123`; text sharp |
| H3 | Native label | `--only 2` | QR scans; compare size with H2 |
| H4 | Bitmap polarity | `--only 3` | Square is **black**, background white |
| H5 | Thai | `--only 4` | Thai vowels/tone marks correct |
| H6 | Size / gap / offset | `--only 5`, then print 20 | Border fully on sticker, no drift |
| H7 | Shared printer | On a 2nd PC: `--printer "\\MAIN-PC\Share" --only 1` | Same result as H2 |
| H8 | App end-to-end | App → search → select 3 → copies 2 → print | 6 stickers, 3 history rows `SpoolerAccepted` |
| H9 | Printer off | Turn printer off, print 1 label | Job stays in queue / error shown; no false "printed" |
| H10 | Continuous | Print 200 labels | No skipped/misaligned labels |
| H11 | Scanner | Scan 10 printed labels with the site scanner | All decode to the correct AssetId |
