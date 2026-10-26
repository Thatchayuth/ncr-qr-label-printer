# UAT checklist (Phase 5)

Run on a **clean** Windows 10 and a **clean** Windows 11 PC with no Python. Record PC name, Windows version, tester, date and Pass/Fail for each row.

| # | Test | Expected result |
|---|---|---|
| U1 | Run Setup.exe as a normal user | Installs without admin rights; Start Menu shortcut created |
| U2 | Run Setup.exe → "Install for all users" | Asks for admin rights; installs to Program Files |
| U3 | First start | Setup wizard opens; wrong admin password is refused |
| U4 | Wizard → AX connection → Test connection | Shows server, database and AssetTable column count |
| U5 | Wizard → TE200 (USB) → Print test label | Sticker prints; QR scans as `TEST-0001` |
| U6 | Second PC → Wizard → Shared printer `\\MAIN-PC\Share` → test | Same sticker as U5 |
| U7 | Search one Asset ID, print 1 copy | Sticker matches the preview; QR = Asset ID |
| U8 | Search a range and a pasted list, print 5 labels × 2 copies | 10 stickers, 5 history rows |
| U9 | Printer off → print 1 | No false success; job in queue / error shown; Check queue explains |
| U10 | History → Reprint with reason | Same sticker; new row "Reprint" linked to the original |
| U11 | Application Settings without password | Settings not visible |
| U12 | Change admin password | Old password refused, new one works |
| U13 | Open the app twice | Second start shows "already open" |
| U14 | Install the next version over it while the app is open | Setup asks to close the app; settings and history kept |
| U15 | Uninstall → answer **No** to delete data | Program removed; `%LOCALAPPDATA%\NCR\QRLabelPrinter` kept |
| U16 | Uninstall → answer **Yes** | Program and data folder removed |
| U17 | Check AX | No data changed (the login is read-only) |
| U18 | Thai text | Thai names show correctly in Search, History and CSV export |

Hardware checks: see [tests/hardware/README.md](../tests/hardware/README.md).
