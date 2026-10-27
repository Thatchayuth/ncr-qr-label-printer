"""Printer adapters. Each one sends a ready TSPL byte stream to one destination.

Status meaning:
- Failed            -> the data definitely did not leave this PC.
- SpoolerAccepted   -> Windows spooler accepted the whole job (not proof of printing).
- SubmittedToDevice -> all bytes were written to the TCP socket (not proof of printing).
- UnknownDelivery   -> something failed part-way; it may or may not have printed.
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from pathlib import Path

from ...domain.errors import PrinterError
from ...domain.models import PrintStatus, SendResult

log = logging.getLogger(__name__)

# Windows JOB_STATUS_* flags
_JOB_FLAGS = [
    (0x0002, "Error", True), (0x0020, "Printer offline", True), (0x0040, "Out of paper", True),
    (0x0400, "Needs attention at the printer", True), (0x0200, "Blocked", True), (0x0001, "Paused", True),
    (0x0004, "Being deleted", False), (0x0008, "Spooling", False), (0x0010, "Printing", False),
    (0x0800, "Restarting", False), (0x0080, "Printed", False), (0x1000, "Complete", False), (0x0100, "Deleted", False),
]
# Windows PRINTER_STATUS_* flags that mean the operator must act
_PRINTER_PROBLEMS = [
    (0x00000001, "printer paused"), (0x00000002, "printer error"), (0x00000008, "paper jam"),
    (0x00000010, "out of paper"), (0x00000040, "paper problem"), (0x00000080, "printer offline"),
    (0x00001000, "printer not available"), (0x00100000, "needs attention"), (0x00400000, "cover open"),
]
_PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400


@dataclass
class QueueState:
    in_queue: bool
    text: str
    problem: bool = False

    @property
    def can_cancel(self) -> bool:
        return self.in_queue


def describe_job_status(flags: int, status_text: str | None = None) -> tuple[str, bool]:
    names = [name for bit, name, _ in _JOB_FLAGS if flags & bit]
    problem = any(flags & bit for bit, _, bad in _JOB_FLAGS if bad)
    if status_text:
        names.insert(0, status_text)
    return (", ".join(names) or "Waiting in queue"), problem


def describe_printer_status(status: int, attributes: int = 0) -> list[str]:
    problems = [name for bit, name in _PRINTER_PROBLEMS if status & bit]
    if attributes & _PRINTER_ATTRIBUTE_WORK_OFFLINE:
        problems.append("'Use printer offline' is switched on in Windows")
    return problems


_VIRTUAL_PORTS = {"PORTPROMPT:", "NUL:", "FILE:", "SHRFAX:", "XPSPORT:"}
_VIRTUAL_HINTS = ("onenote", "print to pdf", "xps document writer", "fax", "pdf", "software printer driver")
_LABEL_BRANDS = ("tsc", "zebra", "godex", "argox", "honeywell", "bixolon", "sato", "citizen", "datamax", "intermec")


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    driver: str = ""
    port: str = ""

    @property
    def is_label_printer(self) -> bool:
        text = f"{self.name} {self.driver}".lower()
        return any(text.startswith(b) or f" {b}" in text for b in _LABEL_BRANDS)


def is_virtual_printer(name: str, driver: str, port: str) -> bool:
    """PDF / XPS / OneNote / Fax and other 'printers' that are not a device."""
    port_u = (port or "").strip().upper()
    if port_u in _VIRTUAL_PORTS or port_u.startswith("MICROSOFT.OFFICE.ONENOTE"):
        return True
    text = f"{name} {driver}".lower()
    return any(h in text for h in _VIRTUAL_HINTS)


def list_physical_printers() -> list[PrinterInfo]:
    """Real printers only, label printers first."""
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    found: dict[str, PrinterInfo] = {}
    for p in win32print.EnumPrinters(flags, None, 2):
        info = PrinterInfo(p.get("pPrinterName", ""), p.get("pDriverName", "") or "", p.get("pPortName", "") or "")
        if info.name and not is_virtual_printer(info.name, info.driver, info.port):
            found[info.name] = info
    return sorted(found.values(), key=lambda i: (not i.is_label_printer, i.name.lower()))


def list_windows_printers() -> list[str]:
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return sorted({p[2] for p in win32print.EnumPrinters(flags, None, 1)}, key=str.lower)


def default_windows_printer() -> str:
    import win32print

    try:
        return win32print.GetDefaultPrinter()
    except Exception:  # no default printer configured
        return ""


class WindowsSpoolerAdapter:
    """RAW printing through a local Windows print queue (e.g. TE200 on USB)."""

    kind = "spooler"

    def __init__(self, printer_name: str) -> None:
        if not printer_name:
            raise PrinterError("No printer selected. Choose a printer in Printer Settings.")
        self.target = printer_name

    def test_connection(self) -> str:
        import win32print

        try:
            h = win32print.OpenPrinter(self.target)
        except Exception as e:
            raise PrinterError(f"Cannot open printer '{self.target}'.", detail=str(e)) from None
        try:
            info = win32print.GetPrinter(h, 2)
        finally:
            win32print.ClosePrinter(h)
        status = info.get("Status", 0)
        state = "ready" if status == 0 else f"status flags 0x{status:X}"
        return f"{self.target}: driver '{info.get('pDriverName', '')}', port '{info.get('pPortName', '')}', {state}, {info.get('cJobs', 0)} job(s) queued"

    def send(self, data: bytes, job_name: str) -> SendResult:
        import win32print

        try:
            h = win32print.OpenPrinter(self.target)
        except Exception as e:
            return SendResult(PrintStatus.FAILED, f"Cannot open printer '{self.target}': {e}", error_code="OPEN")
        job_id = None
        try:
            try:
                job_id = win32print.StartDocPrinter(h, 1, (job_name[:120], None, "RAW"))
            except Exception as e:
                return SendResult(PrintStatus.FAILED, f"Spooler refused the job: {e}", error_code="STARTDOC")
            try:
                win32print.StartPagePrinter(h)
                written = win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
            except Exception as e:
                return SendResult(PrintStatus.UNKNOWN_DELIVERY, f"Error while writing to spooler: {e}", job_id, "WRITE")
            finally:
                try:
                    win32print.EndDocPrinter(h)
                except Exception as e:  # job may be incomplete
                    log.warning("EndDocPrinter failed: %s", e)
            if written != len(data):
                return SendResult(PrintStatus.UNKNOWN_DELIVERY, f"Only {written} of {len(data)} bytes written", job_id, "PARTIAL")
            return SendResult(PrintStatus.SPOOLER_ACCEPTED, "Accepted by Windows spooler", job_id)
        finally:
            win32print.ClosePrinter(h)

    def queue_state(self, spool_job_id: int | None) -> QueueState:
        """Where is this job now? Note: many USB label drivers report printer errors only partly."""
        import win32print

        try:
            h = win32print.OpenPrinter(self.target)
        except Exception as e:
            raise PrinterError(f"Cannot open printer '{self.target}'.", detail=str(e)) from None
        try:
            info = win32print.GetPrinter(h, 2)
            printer_problems = describe_printer_status(info.get("Status", 0), info.get("Attributes", 0))
            job = None
            if spool_job_id:
                try:
                    job = win32print.GetJob(h, int(spool_job_id), 1)
                except Exception:  # not found: already sent to the device, or removed
                    job = None
        finally:
            win32print.ClosePrinter(h)
        suffix = f" Printer: {', '.join(printer_problems)}." if printer_problems else ""
        if job is None:
            return QueueState(
                False,
                "No longer in the Windows print queue (sent to the printer, or removed). Check the sticker." + suffix,
                bool(printer_problems),
            )
        text, problem = describe_job_status(job.get("Status", 0), job.get("pStatus"))
        pos = job.get("Position")
        where = f" (position {pos} in queue)" if pos else ""
        return QueueState(True, f"Still in the Windows print queue{where}: {text}." + suffix, problem or bool(printer_problems))

    def cancel(self, spool_job_id: int) -> None:
        import win32print

        try:
            h = win32print.OpenPrinter(self.target)
        except Exception as e:
            raise PrinterError(f"Cannot open printer '{self.target}'.", detail=str(e)) from None
        try:
            win32print.SetJob(h, int(spool_job_id), 0, None, win32print.JOB_CONTROL_DELETE)
        except Exception as e:
            raise PrinterError("Windows could not cancel the job. It may already have been sent to the printer.", detail=str(e)) from None
        finally:
            win32print.ClosePrinter(h)


class WindowsSharedPrinterAdapter(WindowsSpoolerAdapter):
    """RAW printing to a printer shared from another PC: \\\\HOST\\ShareName."""

    kind = "shared"

    def __init__(self, unc_path: str) -> None:
        unc_path = (unc_path or "").strip()
        parts = unc_path.lstrip("\\").split("\\")
        if not unc_path.startswith("\\\\") or len(parts) != 2 or not all(parts):
            raise PrinterError("Shared printer path must look like \\\\HOST\\ShareName.")
        super().__init__(unc_path)


class TcpPrinterAdapter:
    """RAW TCP (port 9100) via an external print server. TE200 has no built-in Ethernet."""

    kind = "tcp"

    def __init__(self, host: str, port: int = 9100, timeout: float = 5.0) -> None:
        if not host:
            raise PrinterError("No print-server host configured.")
        self.host, self.port, self.timeout = host, int(port), timeout
        self.target = f"{host}:{port}"

    def test_connection(self) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout):
                return f"TCP connection to {self.target} succeeded"
        except OSError as e:
            raise PrinterError(f"Cannot connect to {self.target}.", detail=str(e)) from None

    def send(self, data: bytes, job_name: str) -> SendResult:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            return SendResult(PrintStatus.FAILED, f"Cannot connect to {self.target}: {e}", error_code="CONNECT")
        try:
            sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
        except OSError as e:
            return SendResult(PrintStatus.UNKNOWN_DELIVERY, f"Connection broke while sending: {e}", error_code="SEND")
        finally:
            sock.close()
        return SendResult(PrintStatus.SUBMITTED_TO_DEVICE, "All data sent to print server")


class MockPrinterAdapter:
    """Writes each job to a .prn file instead of printing (development / no hardware)."""

    kind = "mock"

    def __init__(self, output_dir: Path, fail_with: PrintStatus | None = None) -> None:
        self.output_dir = output_dir
        self.target = "Sample printer (.prn files)"
        self.fail_with = fail_with
        self.sent: list[bytes] = []
        self._counter = 0

    def test_connection(self) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return f"Mock printer writes .prn files to {self.output_dir}"

    def send(self, data: bytes, job_name: str) -> SendResult:
        if self.fail_with is not None:
            return SendResult(self.fail_with, "Simulated failure", error_code="MOCK")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._counter += 1
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_name)[:60]
        path = self.output_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{self._counter:03d}-{safe}.prn"
        path.write_bytes(data)
        self.sent.append(data)
        return SendResult(PrintStatus.SPOOLER_ACCEPTED, f"Mock: written to {path.name}", self._counter)
