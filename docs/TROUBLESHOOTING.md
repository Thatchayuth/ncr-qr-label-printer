# การแก้ปัญหา

สำหรับ: IT / ผู้ดูแลระบบ ทุกครั้งที่ติดปัญหา ให้ดูข้อมูลที่หน้า **Diagnostics** และใน log ที่ `%LOCALAPPDATA%\NCR\QRLabelPrinter\logs\qrlabel.log` ประกอบ

## เชื่อมต่อ AX ไม่ได้

| ข้อความ | สาเหตุ / วิธีแก้ |
|---|---|
| Login failed | ชื่อผู้ใช้หรือรหัส SQL ผิด หรือ login ยังไม่มีสิทธิ์เข้าฐานข้อมูลนั้น |
| Cannot reach the SQL Server | ชื่อ server หรือ instance ผิด, firewall ปิดพอร์ต 1433, หรือบริการ SQL Browser ปิดอยู่ |
| The selected ODBC driver is not installed | ติดตั้ง ODBC Driver 17 หรือเลือกไดรเวอร์ `SQL Server` แทน |
| SSL / certificate error | ปิด **Encrypt connection** และเปิด **Trust server certificate** (AX 4.0 มักใช้ SQL Server รุ่นเก่า) |
| The table or view does not exist | ชื่อ Approved sources ผิด หรือ login ไม่มีสิทธิ์อ่านตารางนั้น |
| timeout | เพิ่ม Query timeout หรือค้นหาให้แคบลง |
| ใช้รหัส SQL ที่บันทึกไว้ไม่ได้ | รหัสเข้ารหัสผูกกับ Windows user คนที่บันทึก ให้ใส่รหัสใหม่ |

## พิมพ์ไม่ออก

1. หน้า Print History → เลือกงาน → **Check queue**
2. ถ้าขึ้นว่า **Printer offline / Out of paper / Paused**: แก้ที่เครื่องพิมพ์ หรือไปปิด "Use printer offline" ใน Windows
3. ถ้างาน **No longer in queue** แต่สติกเกอร์ไม่ออก:
   - ตรวจว่ามีไฟเตือนที่เครื่องพิมพ์หรือไม่
   - ทำ calibrate gap sensor ใหม่
   - ตรวจขนาดฉลากใน Label Designer ว่าตรงกับสติกเกอร์จริง
4. ถ้าใช้ shared printer: เปิด `\\MAIN-PC\ShareName` ได้หรือไม่ และเครื่องหลักต้องเปิดอยู่

## ภาพหรือข้อความผิดตำแหน่ง

| อาการ | วิธีแก้ |
|---|---|
| ฉลากเลื่อนทีละดวง | calibrate sensor ใหม่ แล้วตรวจค่า **Gap** และ **Media** ใน Label Designer |
| พิมพ์กลับหัว | เปลี่ยน **Direction** |
| สีจาง หรือ QR สแกนยาก | เพิ่ม **Density** (เช่น 10–12) หรือลด **Speed** |
| ข้อความเกินกรอบ | Label Designer จะเตือนสีส้ม ให้ขยายกล่องหรือเปิด **Shrink to fit** |

## อื่น ๆ

| อาการ | วิธีแก้ |
|---|---|
| "already open" ตอนเปิดโปรแกรม | มีโปรแกรมเปิดอยู่แล้ว ให้หาหน้าต่างเดิมใน taskbar |
| ลืมรหัส Admin | ให้ IT ลบค่า `admin.password_hash` ใน `config.json` แล้วรหัสตั้งต้นจะกลับมาใช้ได้ จากนั้นเปลี่ยนรหัสทันที |
| ค่าตั้งค่าหายหลังเปิดโปรแกรม | ไฟล์ config อ่านไม่ได้ ระบบเก็บไฟล์เดิมไว้เป็น `config.json.invalid-*` แล้วใช้ค่าตั้งต้นแทน |
