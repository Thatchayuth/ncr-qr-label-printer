import pytest

from qrlabel.infrastructure.printing.adapters import PrinterInfo, is_virtual_printer

# (name, driver, port) as reported by Windows on the design PC (2026-10-27)
REAL = [
    ("TSC TE210", "TSC TE210", "USB001"),
    ("Canon iR-ADV C5235/5240 UFR II", "Canon iR-ADV C5235/5240 UFR II", "192.168.10.15"),
    ("\\MAIN-PC\TSC_TE210", "TSC TE210", ""),
]
VIRTUAL = [
    ("OneNote for Windows 10", "Microsoft Software Printer Driver",
     "Microsoft.Office.OneNote_16001.14326.22594.0_x64__8wekyb3d8bbwe_microsoft.onenoteim_S-1-5-21"),
    ("OneNote (Desktop)", "Send to Microsoft OneNote 16 Driver", "nul:"),
    ("Microsoft XPS Document Writer", "Microsoft XPS Document Writer v4", "PORTPROMPT:"),
    ("Microsoft Print to PDF", "Microsoft Print To PDF", "PORTPROMPT:"),
    ("Fax", "Microsoft Shared Fax Driver", "SHRFAX:"),
    ("Adobe PDF", "Adobe PDF Converter", "Documents\*.pdf"),
]


@pytest.mark.parametrize("name,driver,port", REAL)
def test_real_printers_kept(name, driver, port):
    assert not is_virtual_printer(name, driver, port)


@pytest.mark.parametrize("name,driver,port", VIRTUAL)
def test_virtual_printers_removed(name, driver, port):
    assert is_virtual_printer(name, driver, port)


def test_label_printer_detection():
    assert PrinterInfo("TSC TE210", "TSC TE210", "USB001").is_label_printer
    assert PrinterInfo("Warehouse", "ZDesigner ZD421-203dpi", "USB002").is_label_printer is False  # driver brand not first word
    assert PrinterInfo("Zebra ZD421", "ZDesigner ZD421-203dpi", "USB002").is_label_printer
    assert not PrinterInfo("Canon iR-ADV C5235/5240 UFR II", "Canon iR-ADV C5235/5240 UFR II", "192.168.10.15").is_label_printer
