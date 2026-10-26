"""NCR QR Label Printer - entry point."""
from __future__ import annotations

import logging
import sys
import traceback


MUTEX_NAME = "NCRQRLabelPrinter"  # also used by the installer (AppMutex) to detect a running copy
_mutex_handle = None


def _already_running() -> bool:
    """Create a named mutex; True if another copy of the app already owns it."""
    global _mutex_handle
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from qrlabel import __version__
    from qrlabel.app.context import AppContext
    from qrlabel.app.logging_setup import setup_logging
    from qrlabel.app.paths import log_dir, resource_path
    from qrlabel.ui.main_window import MainWindow
    from qrlabel.ui.theme import QSS

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("NCR QR Label Printer")
    app.setOrganizationName("NCR")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(resource_path("app.ico"))))

    if _already_running():
        QMessageBox.information(
            None, "NCR QR Label Printer",
            "NCR QR Label Printer is already open.\nUse the window that is already running.",
        )
        return 0

    log_file = setup_logging(log_dir())
    log = logging.getLogger("qrlabel")
    log.info("Application start")

    def excepthook(exc_type, exc, tb):
        log.critical("Unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, "Unexpected error", f"{exc}\n\nDetails were written to:\n{log_file}")

    sys.excepthook = excepthook

    font = QFont()
    font.setFamilies(["Segoe UI", "Leelawadee UI", "Tahoma"])  # Leelawadee/Tahoma render Thai
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(QSS)

    try:
        ctx = AppContext()
    except Exception as e:
        log.exception("Startup failed")
        QMessageBox.critical(None, "Cannot start", f"The application could not start:\n{e}\n\nLog: {log_file}")
        return 1

    window = MainWindow(ctx)
    window.show()
    if ctx.first_run:
        from qrlabel.ui.first_run import FirstRunWizard

        FirstRunWizard(ctx, window).exec()
        window.refresh_after_setup()
    code = app.exec()
    log.info("Application exit code=%s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
