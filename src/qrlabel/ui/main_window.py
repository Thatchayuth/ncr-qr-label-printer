"""Main window: dark sidebar navigation + stacked pages."""
from __future__ import annotations

import getpass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.context import AppContext
from ..app.paths import resource_path
from .admin_gate import AdminGate
from .icons import icon, pixmap
from .pages.designer_page import DesignerPage
from .pages.history_page import HistoryPage
from .pages.qr_config_page import QrConfigPage
from .pages.info_pages import DiagnosticsPage, ReadOnlyJsonPage
from .pages.printer_page import PrinterPage
from .pages.search_print import SearchPrintPage
from .pages.settings_page import SettingsPage

NAV_COLOR, NAV_SELECTED = "#94A3B8", "#FFFFFF"


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"NCR QR Label Printer {ctx.version}")
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
        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")
        outer.addWidget(self.stack, 1)

        self.search_page = SearchPrintPage(ctx)
        sections = [
            ("OPERATIONS", [
                ("Search & Print", "search", self.search_page),
                ("Print History", "history", HistoryPage(ctx)),
            ]),
            ("LABEL SETUP", [
                ("Data Profiles", "table", ReadOnlyJsonPage(ctx, "Data Profiles", "Profile editor arrives in Phase 2. Current profiles:", "profiles")),
                ("QR Configuration", "qr", QrConfigPage(ctx)),
                ("Label Designer", "layout", DesignerPage(ctx)),
            ]),
            ("SYSTEM", [
                ("Printer Settings", "printer", PrinterPage(ctx, on_saved=self._settings_changed)),
                ("Application Settings", "sliders", AdminGate(
                    ctx, SettingsPage(ctx, on_saved=self._settings_changed),
                    "Application Settings", "Connection to the Dynamics AX 4.0 SQL Server (read-only).",
                )),
                ("Diagnostics", "activity", DiagnosticsPage(ctx)),
            ]),
        ]
        self.pages: list[tuple[str, QWidget]] = []
        self._row_to_page: dict[int, int] = {}
        header_font = QFont()
        header_font.setPointSizeF(7.5)
        header_font.setBold(True)
        for s_index, (section, items) in enumerate(sections):
            head = QListWidgetItem(("\n" if s_index else "") + section)
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setFont(header_font)
            head.setForeground(QColor("#64748B"))
            self.nav.addItem(head)
            for name, icon_name, page in items:
                item = QListWidgetItem(icon(icon_name, NAV_COLOR, NAV_SELECTED), "  " + name)
                self.nav.addItem(item)
                self._row_to_page[self.nav.row(item)] = len(self.pages)
                self.pages.append((name, page))
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setWidget(page)
                self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self._show_row)
        self.nav.setCurrentRow(1)
        self._settings_changed()

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
        title = QLabel("NCR QR Label")
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
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        info = QLabel(f"{user}  ·  v{self.ctx.version}")
        info.setObjectName("SideFooter")
        foot.addWidget(info)
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
