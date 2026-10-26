"""Password gate in front of admin-only pages. Locks again when the page is left."""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.context import AppContext
from .icons import icon, pixmap
from .widgets import Banner, Card, page_header
from .workers import error_text

log = logging.getLogger(__name__)


class ChangePasswordDialog(QDialog):
    def __init__(self, parent: QWidget, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Change admin password")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.current, self.new, self.confirm = QLineEdit(), QLineEdit(), QLineEdit()
        for e in (self.current, self.new, self.confirm):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow("Current password", self.current)
        f.addRow("New password", self.new)
        f.addRow("Confirm new password", self.confirm)
        lay.addLayout(f)
        hint = QLabel("At least 8 characters. The password is stored only as a secure hash.")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #B91C1C;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Change password")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _accept(self) -> None:
        try:
            self.ctx.admin.change(self.current.text(), self.new.text(), self.confirm.text())
        except Exception as e:
            self.error.setText(error_text(e))
            return
        log.info("Admin password changed")
        self.accept()


class AdminGate(QWidget):
    def __init__(self, ctx: AppContext, content: QWidget, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.ctx = ctx
        self.content = content
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)

        # ------------------------------------------------------------ locked
        locked = QWidget()
        lv = QVBoxLayout(locked)
        lv.setContentsMargins(32, 28, 32, 28)
        lv.setSpacing(18)
        lv.addWidget(page_header(title, subtitle))
        card = Card()
        card.setFixedWidth(420)
        lock_icon = QLabel()
        lock_icon.setPixmap(pixmap("sliders", "#2563EB", 36, 1.8))
        lock_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head = QLabel("Admin password required")
        head.setObjectName("CardTitle")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("These settings are for administrators only.")
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Admin password")
        self.unlock_btn = QPushButton("Unlock")
        self.unlock_btn.setObjectName("Primary")
        self.banner = Banner()
        for w in (lock_icon, head, sub, self.password, self.unlock_btn, self.banner):
            card.body.addWidget(w)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        lv.addSpacing(30)
        lv.addLayout(row)
        lv.addStretch(1)
        self.stack.addWidget(locked)

        # ---------------------------------------------------------- unlocked
        unlocked = QWidget()
        uv = QVBoxLayout(unlocked)
        uv.setContentsMargins(0, 0, 0, 0)
        uv.setSpacing(0)
        bar = QFrame()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(32, 14, 32, 0)
        badge = QLabel("●  Admin mode")
        badge.setStyleSheet("QLabel { background:#EFF6FF; color:#1D4ED8; border-radius:10px; padding:3px 10px; font-weight:600; }")
        change = QPushButton("Change admin password...")
        change.setObjectName("Ghost")
        lock_btn = QPushButton("  Lock")
        lock_btn.setIcon(icon("x", "#334155", size=14))
        lock_btn.setIconSize(QSize(14, 14))
        bl.addWidget(badge)
        bl.addStretch(1)
        bl.addWidget(change)
        bl.addWidget(lock_btn)
        uv.addWidget(bar)
        uv.addWidget(content, 1)
        self.stack.addWidget(unlocked)

        self.unlock_btn.clicked.connect(self._unlock)
        self.password.returnPressed.connect(self._unlock)
        lock_btn.clicked.connect(self.lock)
        change.clicked.connect(self._change_password)
        self.lock()

    @property
    def unlocked(self) -> bool:
        return self.stack.currentIndex() == 1

    def lock(self) -> None:
        self.password.clear()
        self.banner.clear_message()
        self.stack.setCurrentIndex(0)

    def _unlock(self) -> None:
        try:
            ok = self.ctx.admin.verify(self.password.text())
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            self.password.clear()
            return
        self.password.clear()
        if not ok:
            log.warning("Wrong admin password entered")
            self.banner.show_message("Wrong password.", "error")
            return
        log.info("Admin settings unlocked")
        self.banner.clear_message()
        if hasattr(self.content, "load"):
            self.content.load()  # show the current saved values
        self.stack.setCurrentIndex(1)

    def _change_password(self) -> None:
        if ChangePasswordDialog(self, self.ctx).exec() == QDialog.DialogCode.Accepted:
            banner = getattr(self.content, "banner", None)
            if banner is not None:
                banner.show_message("Admin password changed.", "success")

    def reload(self) -> None:
        if self.unlocked and hasattr(self.content, "reload"):
            self.content.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.unlocked:
            self.password.setFocus()
