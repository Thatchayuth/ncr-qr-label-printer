"""Application error types. Messages are safe to show to operators."""
from __future__ import annotations


class AppError(Exception):
    code = "APP"

    def __init__(self, message: str, *, code: str | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail  # technical detail for logs (never contains secrets)


class ValidationError(AppError):
    code = "VALIDATION"


class DataSourceError(AppError):
    code = "DATASOURCE"


class PayloadError(AppError):
    code = "PAYLOAD"


class PrinterError(AppError):
    code = "PRINTER"


class DuplicateJobError(AppError):
    code = "DUPLICATE"
