"""Run blocking I/O on the Qt thread pool; results come back on the GUI thread."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..domain.errors import AppError

log = logging.getLogger(__name__)
_active: set["Worker"] = set()


class _Signals(QObject):
    done = Signal(object)
    error = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:  # reported to the UI; unexpected ones are logged with traceback
            if not isinstance(e, AppError):
                log.exception("Background task failed")
            self.signals.error.emit(e)
        else:
            self.signals.done.emit(result)


def run_async(fn: Callable[..., Any], on_done: Callable[[Any], None], on_error: Callable[[Exception], None], *args: Any, **kwargs: Any) -> Worker:
    w = Worker(fn, *args, **kwargs)
    _active.add(w)

    def finish(cb):
        def handler(value):
            _active.discard(w)
            cb(value)
        return handler

    w.signals.done.connect(finish(on_done))
    w.signals.error.connect(finish(on_error))
    QThreadPool.globalInstance().start(w)
    return w


def error_text(e: Exception) -> str:
    if isinstance(e, AppError):
        return e.message
    return f"Unexpected error: {e}. Details are in the log file."
