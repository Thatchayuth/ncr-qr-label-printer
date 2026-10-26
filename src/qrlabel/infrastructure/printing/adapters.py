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
from pathlib import Path

from ...domain.errors import PrinterError
from ...domain.models import PrintStatus, SendResult

log = logging.getLogger(__name__)


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

    def cancel(self, spool_job_id: int) -> None:
        import win32print

        h = win32print.OpenPrinter(self.target)
        try:
            win32print.SetJob(h, spool_job_id, 0, None, win32print.JOB_CONTROL_DELETE)
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
