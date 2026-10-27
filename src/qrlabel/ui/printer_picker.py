"""Drop-down of the real printers on this PC (no PDF / XPS / OneNote / Fax), label printers first."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..infrastructure.printing.adapters import PrinterInfo, default_windows_printer, list_physical_printers
from .icons import icon


class PrinterPicker(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Read the printer list from Windows again (after plugging in or installing a printer)")
        row.addWidget(self.combo, 1)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.printers: list[PrinterInfo] = []
        self.refresh_btn.clicked.connect(lambda: self.refresh(self.current_name()))
        self.combo.currentIndexChanged.connect(self._on_changed)

    def refresh(self, select: str = "") -> None:
        try:
            self.printers = list_physical_printers()
            error = ""
        except Exception as e:  # spooler stopped etc.
            self.printers, error = [], str(e)
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in self.printers:
            detail = f"{p.port}" + ("  ·  label printer" if p.is_label_printer else "")
            self.combo.addItem(icon("printer", "#2563EB" if p.is_label_printer else "#94A3B8"), f"{p.name}    ({detail})", p.name)
        if select and self.combo.findData(select) < 0:
            self.combo.addItem(icon("x", "#B91C1C"), f"{select}    (not found on this PC)", select)
        if select:
            self.combo.setCurrentIndex(self.combo.findData(select))
        elif self.printers:
            label = next((p.name for p in self.printers if p.is_label_printer), "")
            default = default_windows_printer()
            self.combo.setCurrentIndex(max(0, self.combo.findData(label or default)))
        self.combo.blockSignals(False)
        if error:
            self._hint(f"Cannot read printers from Windows: {error}", "#B91C1C")
        elif not self.printers:
            self._hint("No printers found. Connect the TSC printer by USB and install its Windows driver, then press Refresh.", "#B45309")
        else:
            self._on_changed()

    def current_name(self) -> str:
        return self.combo.currentData() or ""

    def _hint(self, text: str, color: str) -> None:
        self.hint.setStyleSheet(f"color: {color};")
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def _on_changed(self, *_) -> None:
        name = self.current_name()
        info = next((p for p in self.printers if p.name == name), None)
        if info is None and name:
            self._hint("This printer is not installed on this PC. Choose another one or install its driver.", "#B91C1C")
        elif info is not None and not info.is_label_printer:
            self._hint(
                "This does not look like a label printer. Labels are sent as TSPL commands - "
                "an office printer would print them as text.", "#B45309",
            )
        else:
            self._hint("", "")
        self.changed.emit(name)
