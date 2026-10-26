"""NCR QR Label Printer - entry point."""
from __future__ import annotations

import logging
import sys
import traceback


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from qrlabel import __version__
    from qrlabel.app.context import AppContext
    from qrlabel.app.logging_setup import setup_logging
    from qrlabel.app.paths import log_dir
    from qrlabel.ui.main_window import MainWindow
    from qrlabel.ui.theme import QSS

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("NCR QR Label Printer")
    app.setOrganizationName("NCR")
    app.setApplicationVersion(__version__)

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
    code = app.exec()
    log.info("Application exit code=%s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
