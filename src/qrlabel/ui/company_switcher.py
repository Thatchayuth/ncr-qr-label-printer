"""Sidebar button showing the active company (DATAAREAID); click to pick another one."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QPushButton

from ..app.context import AppContext
from .icons import icon
from .workers import error_text, run_async


class CompanySwitcher(QPushButton):
    changed = Signal(str)

    def __init__(self, ctx: AppContext, profile_provider: Callable[[], object]) -> None:
        super().__init__()
        self.ctx = ctx
        self._profile = profile_provider
        self.companies: list[tuple[str, str, int | None]] = []
        self._loading = False
        self.setObjectName("CompanyButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icon("building", "#93C5FD", size=16))
        self.setIconSize(QSize(16, 16))
        self.setToolTip("Company (DATAAREAID) used for searching and printing. Click to change.")
        self.clicked.connect(self._open_menu)
        self.refresh_text()

    # ------------------------------------------------------------------ data

    def load(self, then: Callable[[], None] | None = None) -> None:
        """Read the company list in the background (names + number of rows)."""
        if self._loading:
            return
        self._loading = True
        profile = self._profile()

        def done(rows) -> None:
            self._loading = False
            self.companies = rows
            self.refresh_text()
            if then:
                then()

        def failed(e: Exception) -> None:
            self._loading = False
            self.companies = []
            self.setToolTip(f"Cannot read the company list: {error_text(e)}")
            if then:
                then()

        run_async(lambda: self.ctx.data_source().list_companies(profile), done, failed)

    def name_of(self, cid: str) -> str:
        return next((n for c, n, _ in self.companies if c == cid.lower()), "")

    def refresh_text(self) -> None:
        cid = self.ctx.company
        name = self.name_of(cid)
        text = f"{cid.upper() or 'No company'}" + (f"  ·  {name}" if name else "") + "   ▾"
        self.setText(text)
        self.setToolTip(f"Company (DATAAREAID): {cid.upper() or '-'}{f' - {name}' if name else ''}. Click to change.")

    # ------------------------------------------------------------------ menu

    def _open_menu(self) -> None:
        if not self.companies:
            self.setText("Loading companies...")
            self.load(then=self._show_menu)
        else:
            self._show_menu()

    def _show_menu(self) -> None:
        self.refresh_text()
        menu = QMenu(self)
        menu.setObjectName("CompanyMenu")
        title = menu.addAction("Choose company (DATAAREAID)")
        title.setEnabled(False)
        menu.addSeparator()
        group = QActionGroup(menu)
        current = self.ctx.company.lower()
        if not self.companies:
            empty = menu.addAction("No companies found - check the AX connection")
            empty.setEnabled(False)
        for cid, name, count in self.companies:
            label = cid.upper() + (f"   {name}" if name else "")
            if count is not None:
                label += f"   ·   {count:,} rows" if count else "   ·   no data"
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(cid == current)
            act.setData(cid)
            group.addAction(act)
            menu.addAction(act)
        menu.addSeparator()
        reload_act = menu.addAction("Refresh list")
        chosen = menu.exec(self.mapToGlobal(QPoint(0, 0)) - QPoint(0, menu.sizeHint().height() + 4))
        if chosen is None:
            return
        if chosen is reload_act:
            self.companies = []
            self._open_menu()
            return
        cid = chosen.data()
        if cid and cid != current:
            self.ctx.set_company(cid)
            self.refresh_text()
            self.changed.emit(cid)
