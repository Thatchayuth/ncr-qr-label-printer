"""Bar at the top of the window that offers a new version (see services.updater)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ..services.updater import UpdateInfo

_STYLE = {
    "info": "QFrame#UpdateBar { background: #EFF6FF; border-bottom: 1px solid #BFDBFE; }",
    "required": "QFrame#UpdateBar { background: #FEF3C7; border-bottom: 1px solid #FCD34D; }",
    "error": "QFrame#UpdateBar { background: #FEF2F2; border-bottom: 1px solid #FECACA; }",
}


class UpdateBar(QFrame):
    update_clicked = Signal(object)  # UpdateInfo

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("UpdateBar")
        self.info: UpdateInfo | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 8)
        lay.setSpacing(12)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.update_btn = QPushButton("Update now")
        self.update_btn.setObjectName("Primary")
        self.later_btn = QPushButton("Later")
        self.later_btn.setObjectName("Ghost")
        lay.addWidget(self.text, 1)
        lay.addWidget(self.update_btn)
        lay.addWidget(self.later_btn)
        self.update_btn.clicked.connect(lambda: self.info and self.update_clicked.emit(self.info))
        self.later_btn.clicked.connect(self.hide)
        self.hide()

    def show_update(self, info: UpdateInfo, current: str) -> None:
        from html import escape

        self.info = info
        notes = f"<br><span style='color:#475569'>{escape(info.notes)}</span>" if info.notes else ""
        must = " <b>This update is required.</b>" if info.required else ""
        self.text.setText(f"<b>New version {escape(info.version)}</b> is available (you have {escape(current)}).{must}{notes}")
        self.setStyleSheet(_STYLE["required" if info.required else "info"])
        self.update_btn.setVisible(True)
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Update now")
        self.later_btn.setVisible(not info.required)
        self.show()

    def show_busy(self, text: str) -> None:
        self.text.setText(text)
        self.update_btn.setEnabled(False)
        self.later_btn.hide()
        self.show()

    def show_error(self, text: str, retry: bool = True) -> None:
        """retry=False: trying again cannot help (e.g. running from source), so no "Try again" button."""
        from html import escape

        self.setStyleSheet(_STYLE["error"])
        self.text.setText(escape(text))
        self.update_btn.setVisible(retry)
        self.update_btn.setEnabled(retry and self.info is not None)
        self.update_btn.setText("Try again")
        self.later_btn.setVisible(not (self.info and self.info.required))
        self.show()
