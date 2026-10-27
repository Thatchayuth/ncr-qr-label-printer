"""Main window: dark sidebar navigation + stacked pages."""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.context import AppContext
from ..app.paths import resource_path
from .admin_gate import AdminGate
from .update_bar import UpdateBar
from .workers import error_text, run_async
from .company_switcher import CompanySwitcher
from .icons import icon, pixmap
from .pages.designer_page import DesignerPage
from .pages.history_page import HistoryPage
from .pages.qr_config_page import QrConfigPage
from .pages.info_pages import DiagnosticsPage, ReadOnlyJsonPage
from .pages.printer_page import PrinterPage
from .pages.profiles_page import ProfilesPage
from .pages.search_print import SearchPrintPage
from .pages.settings_page import SettingsPage

NAV_COLOR, NAV_SELECTED = "#94A3B8", "#FFFFFF"


class PageHost(QWidget):
    """Holds a page inside its scroll area and never lets it be squeezed.

    Pages with wrapped text (card descriptions) report a height-for-width that equals their *minimum*
    height. The scroll area then shrinks the page to that, and forms lose their row spacing (fields
    touching each other on Application Settings). This host asks for the page's preferred height
    instead; a taller page simply scrolls.
    """

    def __init__(self, page: QWidget) -> None:
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(page)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return False

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        least = super().minimumSizeHint()
        return QSize(least.width(), max(least.height(), self.page.sizeHint().height()))


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"NCR Print Label {ctx.version}")
        self.setWindowIcon(QIcon(str(resource_path("app.ico"))))
        self.resize(1440, 900)
        self.setMinimumSize(1180, 700)

        central = QWidget()
        central.setObjectName("Content")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)
        outer.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.update_bar = UpdateBar()
        self.update_bar.update_clicked.connect(self.start_update)
        right.addWidget(self.update_bar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")
        right.addWidget(self.stack, 1)
        outer.addLayout(right, 1)

        self.search_page = SearchPrintPage(ctx)
        sections = [
            ("OPERATIONS", [
                ("search", "Search & Print", "search", self.search_page),
                ("history", "Print History", "history", HistoryPage(ctx)),
            ]),
            ("LABEL SETUP", [
                ("profiles", "Data Profiles", "table", AdminGate(
                    ctx, ProfilesPage(ctx), "Data Profiles",
                    "Which AX table or view to read, which columns to show, search and print.",
                )),
                ("qr", "QR Configuration", "qr", QrConfigPage(ctx)),
                ("designer", "Label Designer", "layout", DesignerPage(ctx)),
            ]),
            ("SYSTEM", [
                ("printer", "Printer Settings", "printer", PrinterPage(ctx, on_saved=self._settings_changed)),
                ("settings", "Application Settings", "sliders", AdminGate(
                    ctx, SettingsPage(ctx, on_saved=self._settings_changed, on_access_changed=self.access_settings_changed,
                                 on_check_updates=self.check_updates),
                    "Application Settings", "Connection to the Dynamics AX 4.0 SQL Server (read-only).",
                )),
                ("diagnostics", "Diagnostics", "activity", DiagnosticsPage(ctx)),
            ]),
        ]
        self.pages: list[tuple[str, QWidget]] = []
        self._row_to_page: dict[int, int] = {}
        self._menu_items: dict[str, QListWidgetItem] = {}
        self._sections: list[tuple[QListWidgetItem, list[str]]] = []  # header, menu keys
        header_font = QFont()
        header_font.setPointSizeF(7.5)
        header_font.setBold(True)
        for s_index, (section, items) in enumerate(sections):
            head = QListWidgetItem(("\n" if s_index else "") + section)
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setFont(header_font)
            head.setForeground(QColor("#64748B"))
            self.nav.addItem(head)
            self._sections.append((head, [key for key, *_ in items]))
            for key, name, icon_name, page in items:
                item = QListWidgetItem(icon(icon_name, NAV_COLOR, NAV_SELECTED), "  " + name)
                self.nav.addItem(item)
                self._menu_items[key] = item
                self._row_to_page[self.nav.row(item)] = len(self.pages)
                self.pages.append((name, page))
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setWidget(PageHost(page))
                self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self._show_row)
        self.nav.setCurrentRow(1)
        self.apply_access()
        self._settings_changed()
        if ctx.config.get("update", {}).get("check_on_start", True):
            QTimer.singleShot(2500, self.check_updates)  # after the window is up; never blocks start

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(248)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 22, 0, 18)
        side.setSpacing(0)

        brand = QHBoxLayout()
        brand.setContentsMargins(22, 0, 18, 0)
        brand.setSpacing(12)
        logo = QFrame()
        logo.setObjectName("Logo")
        logo.setFixedSize(38, 38)
        ll = QVBoxLayout(logo)
        ll.setContentsMargins(0, 0, 0, 0)
        logo_icon = QLabel()
        logo_icon.setPixmap(pixmap("qr", "#FFFFFF", 22))
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_icon.setStyleSheet("background: transparent;")
        ll.addWidget(logo_icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("NCR Print Label")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Asset label printer")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        brand.addWidget(logo)
        brand.addLayout(titles, 1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.nav.setCursor(Qt.CursorShape.PointingHandCursor)
        side.addWidget(self.nav, 1)

        foot = QVBoxLayout()
        foot.setContentsMargins(22, 0, 22, 0)
        foot.setSpacing(8)
        self.mode_badge = QLabel()
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.mode_badge)
        badge_row.addStretch(1)
        foot.addLayout(badge_row)
        self.company = CompanySwitcher(
            self.ctx, lambda: self.search_page.current_profile() if hasattr(self, "search_page") else None
        )
        self.company.changed.connect(self._company_changed)
        foot.addWidget(self.company)
        self.admin_btn = QPushButton()
        self.admin_btn.setObjectName("SideAdmin")
        self.admin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.admin_btn.setStyleSheet(
            "QPushButton#SideAdmin { background: transparent; color: #CBD5E1; border: 1px solid #334155;"
            " border-radius: 8px; padding: 5px 10px; text-align: left; }"
            "QPushButton#SideAdmin:hover { background: #1E293B; color: #FFFFFF; }"
            "QPushButton#SideAdmin:disabled { color: #86EFAC; border-color: #1E3A2F; }"
        )
        self.admin_btn.clicked.connect(self._admin_clicked)
        foot.addWidget(self.admin_btn)
        self.user_info = QLabel()
        self.user_info.setObjectName("SideFooter")
        self.user_info.setWordWrap(True)
        foot.addWidget(self.user_info)
        side.addLayout(foot)
        return sidebar

    def _show_row(self, row: int) -> None:
        if row not in self._row_to_page:
            return
        index = self._row_to_page[row]
        previous = self.pages[self.stack.currentIndex()][1] if self.pages else None
        if isinstance(previous, AdminGate) and self.stack.currentIndex() != index:
            previous.lock()  # leaving an admin page locks it again
        self.stack.setCurrentIndex(index)
        page = self.pages[index][1]
        if page is self.search_page:
            page._refresh_printer_label()
            page.refresh_definitions()
        elif hasattr(page, "reload"):
            page.reload()

    def show_page(self, name: str) -> None:
        for row, index in self._row_to_page.items():
            if self.pages[index][0] == name:
                self.nav.setCurrentRow(row)
                return

    # ------------------------------------------------------------ updates

    def check_updates(self, report=None) -> None:
        """Look for a newer version in the update folder. report(text, level) shows the result (Settings)."""
        from ..services.updater import check_for_update

        folder = self.ctx.config.get("update", {}).get("folder", "")
        if not folder.strip():
            if report:
                report("Set the update folder first.", "warning")
            return

        def found(info) -> None:
            if info is None:
                if report:
                    report(f"This is the newest version ({self.ctx.version}).", "success")
                return
            self.update_bar.show_update(info, self.ctx.version)
            if report:
                report(f"Version {info.version} is available: use the bar at the top of the window.", "info")

        def failed(e: Exception) -> None:
            logging.getLogger(__name__).warning("Update check failed: %s", e)
            if report:
                report(error_text(e), "error")

        run_async(lambda: check_for_update(folder, self.ctx.version), found, failed)

    def start_update(self, info) -> None:
        from ..app.paths import app_data_dir
        from ..services.updater import ADMIN_MODE, download, install_mode, start_installer_after_exit

        mode, why = install_mode()
        if mode is None:
            self.update_bar.show_error(why, retry=False)
            return
        if getattr(self.search_page, "_printing", False):
            self.update_bar.show_error("Labels are being printed. Update when printing has finished.")
            return
        admin_note = f"\n\n{why}" if mode == ADMIN_MODE else ""
        answer = QMessageBox.question(
            self, "Update NCR Print Label",
            f"NCR Print Label will close, install version {info.version} and open again (about a minute).\n\n"
            f"Settings, print history and label designs are kept.{admin_note}\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        folder = self.ctx.config["update"]["folder"]
        self.update_bar.show_busy(f"Copying version {info.version} from the update folder...")

        def ready(installer) -> None:
            import os

            try:
                start_installer_after_exit(installer, os.getpid(), mode=mode)
            except Exception as e:
                self.update_bar.show_error(f"Cannot start the installer: {e}")
                return
            logging.getLogger(__name__).info("Closing for the update to %s", info.version)
            self.update_bar.show_busy("Installing... the program opens again when it is done."
                                      + (" Windows asks for an administrator password." if mode == ADMIN_MODE else ""))
            QTimer.singleShot(300, QApplication.instance().quit)

        run_async(lambda: download(info, folder, app_data_dir() / "updates"), ready,
                  lambda e: self.update_bar.show_error(error_text(e)))

    # ------------------------------------------------------------ access

    def apply_access(self) -> None:
        """Hide the menus this user may not see (AD group or admin password)."""
        access = self.ctx.access
        for key, item in self._menu_items.items():
            item.setHidden(not access.can_see(key))
        for head, keys in self._sections:
            head.setHidden(all(self._menu_items[k].isHidden() for k in keys))
        current = self.nav.currentItem()
        if current is None or current.isHidden():
            self.nav.setCurrentItem(self._menu_items["search"])
        for _, page in self.pages:
            if isinstance(page, AdminGate):
                page.sync_access()
        user = self.ctx.identity.user or "unknown user"
        self.user_info.setText(f"{user}  ·  v{self.ctx.version}")
        self.user_info.setToolTip(access.describe())
        if access.is_ad_admin:
            self.admin_btn.setText(f"  Admin · {access.matched_admin_group}")
            self.admin_btn.setIcon(icon("check", "#86EFAC", size=14))
            self.admin_btn.setToolTip("Your Windows account is in an admin group: every menu is shown.")
            self.admin_btn.setEnabled(False)
        elif access.unlocked:
            self.admin_btn.setText("  Admin unlocked · Lock")
            self.admin_btn.setIcon(icon("x", "#FCA5A5", size=14))
            self.admin_btn.setToolTip("Hide the admin menus again")
            self.admin_btn.setEnabled(True)
        else:
            self.admin_btn.setText("  Admin")
            self.admin_btn.setIcon(icon("lock", "#CBD5E1", size=14))
            self.admin_btn.setToolTip("Show every menu (admin password)")
            self.admin_btn.setEnabled(True)

    def _admin_clicked(self) -> None:
        access = self.ctx.access
        if access.is_ad_admin:
            return
        if access.unlocked:
            access.unlocked = False
            self.apply_access()
            return
        if AdminPasswordDialog(self, self.ctx).exec() == QDialog.DialogCode.Accepted:
            access.unlocked = True
            self.apply_access()

    def access_settings_changed(self) -> None:
        self.ctx.reload_access()
        self.apply_access()

    def _company_changed(self, cid: str) -> None:
        self.search_page.on_company_changed(cid, self.company.name_of(cid))

    def refresh_after_setup(self) -> None:
        """Re-read settings changed by the first-run wizard."""
        for _, page in self.pages:
            content = getattr(page, "content", page)
            if hasattr(content, "load"):
                content.load()
        self._settings_changed()

    def _settings_changed(self) -> None:
        if self.ctx.using_mock_data:
            self.mode_badge.setObjectName("ModeMock")
            self.mode_badge.setText("●  SAMPLE DATA")
        else:
            db = self.ctx.config["database"]
            self.mode_badge.setObjectName("ModeLive")
            self.mode_badge.setText(f"●  AX LIVE · {db.get('database', '')}")
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)
        self.search_page.reload()
        self.company.companies = []  # database may have changed: read the list again
        self.company.refresh_text()
        self.company.load()


class AdminPasswordDialog(QDialog):
    """Admin password: shows every menu until locked again or the application closes."""

    def __init__(self, parent: QWidget, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Admin")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        head = QLabel("Enter the admin password to show every menu.")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Admin password")
        lay.addWidget(self.password)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #B91C1C;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Unlock")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _accept(self) -> None:
        try:
            ok = self.ctx.admin.verify(self.password.text())
        except Exception as e:  # too many wrong attempts
            self.error.setText(error_text(e))
            self.password.clear()
            return
        self.password.clear()
        if not ok:
            self.error.setText("Wrong password.")
            return
        logging.getLogger(__name__).info("Admin menus unlocked with the password by %s", self.ctx.identity.user)
        self.accept()
