# คู่มือติดตั้ง NCR Print Label

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
4. รัน `NCR-Print-Label-Setup-<version>.exe`
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

## แบบฉลากที่ติดไปกับตัวติดตั้ง

- เครื่องที่ติดตั้งใหม่จะได้ template **"New label"** (38.1 × 38.1 มม.) เป็นค่าเริ่มต้นทันที โดยไม่ต้อง Import
- เครื่องที่มี template อยู่แล้ว (เช่น ติดตั้งทับเวอร์ชันเก่า) ระบบจะไม่เขียนทับ ถ้าต้องการแบบใหม่ ให้ใช้ Label Designer → **Import...**
- ถ้าต้องการเปลี่ยนแบบฉลากที่ติดไปกับตัวติดตั้ง (สำหรับนักพัฒนา):
  1. Label Designer → **Export...**
  2. นำไฟล์ไปแทนที่ใน `src/qrlabel/resources/templates/` และแก้ `index.json` ถ้าเปลี่ยนชื่อไฟล์หรือ id
  3. build ตัวติดตั้งใหม่

## อัปเกรดเวอร์ชัน

- โปรแกรมเปลี่ยนชื่อจาก "NCR QR Label Printer" เป็น **"NCR Print Label"** แล้ว ติดตั้งทับเวอร์ชันเก่าได้เลย ค่าตั้งค่าและประวัติยังอยู่ครบ ตัวติดตั้งจะลบไฟล์ .exe และ shortcut ที่ใช้ชื่อเก่าออกให้

- รัน Setup.exe ของเวอร์ชันใหม่ทับได้เลย
- ถ้าโปรแกรมเปิดอยู่ ตัวติดตั้งจะขอให้ปิดก่อน
- ค่าตั้งค่า ประวัติการพิมพ์ และ template ยังอยู่ครบ เพราะเก็บแยกไว้ที่ `%LOCALAPPDATA%\NCR\QRLabelPrinter`
- ถ้ามีการอัปเกรดฐานข้อมูล ระบบจะสำรองไฟล์เดิมเป็น `qrlabel.sqlite3.bak-vN` ก่อน

## ถอนการติดตั้ง

ไปที่ Settings → Apps → **NCR Print Label** → Uninstall ระบบจะถามว่าจะลบค่าตั้งค่าและประวัติด้วยหรือไม่ (ค่าตั้งต้นคือ **ไม่ลบ**)

## ตำแหน่งไฟล์

| สิ่งที่เก็บ | ตำแหน่ง |
|---|---|
| โปรแกรม (ติดตั้งเฉพาะผู้ใช้) | `%LOCALAPPDATA%\Programs\NCR Print Label` |
| โปรแกรม (ติดตั้งให้ทุกคน) | `C:\Program Files\NCR Print Label` |
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


## เลือกส่วนของโปรแกรมตอนติดตั้ง

หน้า **Select Additional Tasks** ของตัวติดตั้งมีหัวข้อ "Use the program for:"
- **Asset labels (fixed assets)**: พิมพ์สติกเกอร์ทรัพย์สิน (AssetTable)
- **Stock labels (inventory transfer journal)**: พิมพ์สติกเกอร์ STOCK จาก Transfer journal (ยิงบาร์โค้ดเลข Journal)

ต้องเลือกอย่างน้อยหนึ่งอย่าง ถ้าเลือก Stock labels โปรแกรมจะสร้างโปรไฟล์ "Inventory transfer journal" และแบบสติกเกอร์ STOCK ให้เองเมื่อเปิดครั้งแรก
ติดตั้งแบบเงียบ (silent): `NCR-Print-Label-Setup-x.y.z.exe /VERYSILENT /TASKS="modjournal"` (ใส่ `modasset,modjournal` ถ้าต้องการทั้งสองอย่าง)
ภายหลังผู้ดูแลเปลี่ยนได้ที่ Application Settings → **Parts of the program**

สิทธิ์การเห็นเมนูไม่ได้เลือกตอนติดตั้ง ระบบใช้กลุ่ม AD ของ Windows: กลุ่ม ICT-RY เห็นทุกเมนู ผู้ใช้อื่นเห็น Search & Print, Print History, Printer Settings


## อัปเดตอัตโนมัติ (สำหรับ ICT)

โปรแกรมเช็กเวอร์ชันใหม่จากโฟลเดอร์แชร์ (ตอนทดสอบใช้ `\\ncr230\NCR_Data\General\ICT\NCRPrintLabel`) ทุกครั้งที่เปิด
ถ้ามีเวอร์ชันใหม่จะขึ้นแถบด้านบน ผู้ใช้กด **Update now** โปรแกรมจะปิด ติดตั้งเวอร์ชันใหม่แบบเงียบ แล้วเปิดกลับมาเอง การตั้งค่าและประวัติยังอยู่ครบ

ขั้นตอนออกเวอร์ชันใหม่:
1. เพิ่มเลขเวอร์ชันใน `src\qrlabel\__init__.py` เช่น `0.9.2`
2. `.\scripts\build.ps1` (รันเทสและสร้างตัวติดตั้ง)
3. `.\scripts\publish_update.ps1 -Notes "แก้อะไรบ้าง"` (ใส่ `-Required` ถ้าต้องบังคับอัปเดต)

ข้อควรรู้:
- โฟลเดอร์ควรให้ผู้ใช้ทั่วไป**อ่านได้อย่างเดียว** และให้ ICT เขียนได้
- ระบบตรวจ SHA-256 ก่อนติดตั้ง ถ้าไฟล์ถูกแก้หรือเสียจะไม่ติดตั้ง
- เครื่องที่ติดตั้งแบบ "for all users" (Program Files) อัปเดตเองไม่ได้ เพราะผู้ใช้ไม่มีสิทธิ์เขียน ICT ต้องติดตั้งให้
- เปลี่ยนโฟลเดอร์ได้ที่ Application Settings → Updates
