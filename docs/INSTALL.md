# คู่มือติดตั้ง NCR QR Label Printer

สำหรับ: ผู้ดูแลระบบ / IT

## สิ่งที่ต้องมีก่อนติดตั้ง

| รายการ | รายละเอียด |
|---|---|
| Windows | Windows 10 หรือ 11 แบบ 64-bit |
| Python | **ไม่ต้องติดตั้ง** มีมาในตัวโปรแกรมแล้ว |
| ODBC Driver | แนะนำ **ODBC Driver 17 for SQL Server** ถ้าไม่มี ให้ใช้ไดรเวอร์ `SQL Server` ที่มากับ Windows แทนได้ ตัวติดตั้งของโปรแกรมนี้ไม่ได้ติดตั้งไดรเวอร์ให้ |
| SQL login | login ที่อ่าน AX ได้อย่างเดียว (`db_datareader`) |
| เครื่องพิมพ์ | ติดตั้ง **TSC TE200 Windows driver** ที่เครื่องหลักที่ต่อ USB |

## เครื่องหลัก (ต่อ TE200 ผ่าน USB)

1. ต่อ TE200 ผ่าน USB แล้วติดตั้งไดรเวอร์ของ TSC
2. ใส่ม้วนสติกเกอร์ แล้วทำ **Calibrate gap sensor** ด้วย TSC Diagnostic Tool หรือตามขั้นตอนในคู่มือ TE200
3. แชร์เครื่องพิมพ์ให้เครื่องอื่นใช้: Settings → Printers → TE200 → Printer properties → Sharing → ตั้งชื่อแชร์ เช่น `TSC_TE200`
4. รัน `NCR-QR-Label-Printer-Setup-<version>.exe`
   - ค่าปกติคือ **ติดตั้งเฉพาะผู้ใช้นี้** ไม่ต้องใช้สิทธิ์ Admin
   - ถ้าต้องการติดตั้งให้ทุกคนในเครื่อง เลือก "Install for all users" (ต้องใช้สิทธิ์ Admin)
5. เปิดโปรแกรมครั้งแรกจะเจอ **Setup wizard**:
   1. ใส่รหัส Admin (ขอรหัสตั้งต้นจากผู้ดูแลระบบ)
   2. ใส่ข้อมูลเชื่อมต่อ AX แล้วกด **Test connection** ให้ผ่าน
   3. เลือก **TE200 on this PC (USB)** แล้วกด **Print test label**
   4. สแกน QR บนสติกเกอร์ทดสอบ ต้องอ่านได้ `TEST-0001`
6. ไปที่ Application Settings → **Change admin password** แล้วเปลี่ยนรหัส Admin

## เครื่องลูก (พิมพ์ผ่านเครื่องหลัก)

1. ใน Windows ให้เพิ่มเครื่องพิมพ์ที่แชร์ไว้: เปิด `\\MAIN-PC` แล้วดับเบิลคลิก `TSC_TE200` (ขั้นนี้อาจต้องใช้สิทธิ์ติดตั้งไดรเวอร์)
2. ติดตั้งโปรแกรมด้วย Setup.exe ตัวเดียวกัน
3. ใน Setup wizard ให้เลือก **Shared printer on the main PC** แล้วใส่ `\\MAIN-PC\TSC_TE200`
4. กด **Print test label**

## อัปเกรดเวอร์ชัน

- รัน Setup.exe ของเวอร์ชันใหม่ทับได้เลย
- ถ้าโปรแกรมเปิดอยู่ ตัวติดตั้งจะขอให้ปิดก่อน
- ค่าตั้งค่า ประวัติการพิมพ์ และ template ยังอยู่ครบ เพราะเก็บแยกไว้ที่ `%LOCALAPPDATA%\NCR\QRLabelPrinter`
- ถ้ามีการอัปเกรดฐานข้อมูล ระบบจะสำรองไฟล์เดิมเป็น `qrlabel.sqlite3.bak-vN` ก่อน

## ถอนการติดตั้ง

ไปที่ Settings → Apps → **NCR QR Label Printer** → Uninstall ระบบจะถามว่าจะลบค่าตั้งค่าและประวัติด้วยหรือไม่ (ค่าตั้งต้นคือ **ไม่ลบ**)

## ตำแหน่งไฟล์

| สิ่งที่เก็บ | ตำแหน่ง |
|---|---|
| โปรแกรม (ติดตั้งเฉพาะผู้ใช้) | `%LOCALAPPDATA%\Programs\NCR QR Label Printer` |
| โปรแกรม (ติดตั้งให้ทุกคน) | `C:\Program Files\NCR QR Label Printer` |
| ค่าตั้งค่า (รหัส SQL ถูกเข้ารหัสด้วย DPAPI) | `%LOCALAPPDATA%\NCR\QRLabelPrinter\config.json` |
| ประวัติการพิมพ์, profile, template | `%LOCALAPPDATA%\NCR\QRLabelPrinter\qrlabel.sqlite3` |
| Log | `%LOCALAPPDATA%\NCR\QRLabelPrinter\logs\` |

> รหัส SQL ถูกเข้ารหัสด้วย DPAPI ซึ่งผูกกับ Windows user คนที่บันทึก ถ้าใช้ Windows user คนอื่น ต้องใส่รหัส SQL ใหม่

## Build ตัวติดตั้งเอง (สำหรับนักพัฒนา)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
winget install JRSoftware.InnoSetup --scope user
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

ผลลัพธ์อยู่ที่ `dist\installer\NCR-QR-Label-Printer-Setup-<version>.exe`
