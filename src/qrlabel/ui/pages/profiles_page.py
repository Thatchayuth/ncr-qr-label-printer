"""Data Profiles editor: which AX table/view to read, which columns to show, search and print.

Works with tables and with views made by the DBA (a view is used exactly like a table).
Admin only (wrapped in AdminGate by the main window).
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...domain.models import DataProfile, FieldDef, LookupDef, QrConfig, new_id
from ...infrastructure.ax.mock_source import MOCK_COMPANY
from ...services.formatting import format_value
from ...services.profile_io import duplicate_profile, export_profile, import_profile
from ...services.profile_rules import UNSORTABLE_TYPES, ColumnMap, new_field, template_issues, validate_profile
from ...services.query_builder import IDENT_RE, build_select, split_order
from ..icons import icon
from ..widgets import Banner, Card, chip, labeled, page_header
from ..workers import error_text, run_async

TYPES = ["string", "int", "decimal", "date"]
COLS = ["Field", "Header", "Type", "Format", "Search", "Date range", "Show", "Required", "Fallback", "From"]
CHECK_COLS = {4: "searchable", 5: "range_search", 6: "display", 7: "required"}
NO_COMPANY = "__none__"
TEST_ROWS = 20


def _columns_of(ctx: AppContext, tables: list[tuple[str, str]]) -> ColumnMap:
    """Read column names/types for (schema, table) pairs from the data source (worker thread)."""
    src = ctx.data_source()
    getattr(src, "forget_columns", lambda: None)()
    out: ColumnMap = {}
    for schema, table in tables:
        out[table.upper()] = {c.upper(): t.lower() for c, t in src.list_columns(table, schema)}
    return out


# ============================================================== dialogs


class SourcePickerDialog(QDialog):
    """Lists every table and view in the AX database; the chosen one is added to the approved list."""

    def __init__(self, parent: QWidget, ctx: AppContext, title: str = "Choose a table or view") -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(title)
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        info = QLabel("Views made by the DBA work exactly like tables. The program only reads data.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Type to filter, e.g. ASSET or V_NCR")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.status = QLabel("Loading tables and views...")
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.filter.textChanged.connect(self._apply_filter)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        self.choice: tuple[str, str] | None = None
        run_async(lambda: self.ctx.data_source().list_sources(), self._loaded, self._failed)

    def _loaded(self, sources) -> None:
        approved = {s.upper() for s in self.ctx.config["approved_sources"]}
        for schema, name, kind in sources:
            if not IDENT_RE.match(name) or not IDENT_RE.match(schema):
                continue  # names the query builder would refuse anyway
            mark = "   ✓ approved" if name.upper() in approved else ""
            it = QListWidgetItem(icon("table" if kind == "TABLE" else "layout", "#2563EB" if kind == "VIEW" else "#64748B"),
                                 f"{name}    ({kind.lower()}, {schema}){mark}")
            it.setData(Qt.ItemDataRole.UserRole, (schema, name))
            self.list.addItem(it)
        self.status.setText(f"{self.list.count()} tables and views")
        self._apply_filter(self.filter.text())

    def _failed(self, e: Exception) -> None:
        self.status.setText(error_text(e))
        self.status.setStyleSheet("color: #B91C1C;")

    def _apply_filter(self, text: str) -> None:
        t = text.strip().upper()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.data(Qt.ItemDataRole.UserRole)[1].upper())

    def _accept(self) -> None:
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return
        self.choice = it.data(Qt.ItemDataRole.UserRole)
        self.accept()


class AddFieldsDialog(QDialog):
    def __init__(self, parent: QWidget, columns: ColumnMap, tables: list[tuple[str, str]], used: set[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add fields")
        self.resize(520, 560)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter columns")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        for label, table in tables:
            head = QListWidgetItem(label)
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setForeground(QColor("#64748B"))
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            self.list.addItem(head)
            for col, typ in columns.get(table.upper(), {}).items():
                if (table.upper(), col) in used:
                    continue
                it = QListWidgetItem(f"   {col}    ({typ})")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, (table, col, typ))
                self.list.addItem(it)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.filter.textChanged.connect(self._apply_filter)

    def _apply_filter(self, text: str) -> None:
        t = text.strip().upper()
        for i in range(self.list.count()):
            it = self.list.item(i)
            data = it.data(Qt.ItemDataRole.UserRole)
            if data:
                it.setHidden(bool(t) and t not in data[1])

    def selected(self) -> list[tuple[str, str, str]]:
        return [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) and self.list.item(i).checkState() == Qt.CheckState.Checked
        ]


class LookupDialog(QDialog):
    """Related table: one row of it per main row (e.g. AssetBook for AssetTable)."""

    def __init__(self, parent: QWidget, ctx: AppContext, main: str, main_cols: dict[str, str], lk: LookupDef | None) -> None:
        super().__init__(parent)
        self.ctx, self.main, self.main_cols = ctx, main, main_cols
        self.setWindowTitle("Related table")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        info = QLabel(
            f"Adds columns from another table. For every row of <b>{main}</b> the program takes "
            "<b>one</b> matching row (the first by the sort below), so rows are never duplicated."
        )
        info.setWordWrap(True)
        lay.addWidget(info)
        f = QFormLayout()
        row = QHBoxLayout()
        self.table = QLineEdit(lk.table if lk else "")
        self.table.setReadOnly(True)
        browse = QPushButton("Browse...")
        row.addWidget(self.table, 1)
        row.addWidget(browse)
        self.schema = QLineEdit(lk.schema if lk else "dbo")
        self.join = QLineEdit(", ".join(f"{a}={b}" for a, b in lk.join) if lk else "")
        self.join.setPlaceholderText("RELATED_COLUMN=MAIN_COLUMN, e.g. ASSETID=ASSETID, DATAAREAID=DATAAREAID")
        self.order = QLineEdit(", ".join(lk.order_by) if lk else "")
        self.order.setPlaceholderText("Which row wins if there are several, e.g. ACQUISITIONPRICE DESC, BOOKID")
        f.addRow("Table / view", row)
        f.addRow("Schema", self.schema)
        f.addRow("Link columns", self.join)
        f.addRow("Pick first by", self.order)
        lay.addLayout(f)
        self.cols_label = QLabel("")
        self.cols_label.setObjectName("Muted")
        self.cols_label.setWordWrap(True)
        lay.addWidget(self.cols_label)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #B91C1C;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        browse.clicked.connect(self._browse)
        self.columns: dict[str, str] = {}
        if lk:
            self._load_columns()

    def _browse(self) -> None:
        dlg = SourcePickerDialog(self, self.ctx, "Choose the related table or view")
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        schema, name = dlg.choice
        if name.upper() == self.main.upper():
            self.error.setText("Choose a different table than the main one.")
            return
        _approve(self.ctx, name)
        self.table.setText(name)
        self.schema.setText(schema)
        self._load_columns(suggest=True)

    def _load_columns(self, suggest: bool = False) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cols = _columns_of(self.ctx, [(self.schema.text().strip() or "dbo", self.table.text())])
            self.columns = cols.get(self.table.text().upper(), {})
        except Exception as e:
            self.error.setText(error_text(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.cols_label.setText("Columns: " + ", ".join(self.columns))
        if suggest and not self.join.text().strip():
            common = [c for c in self.main_cols if c in self.columns and (c.endswith("ID") or c == "DATAAREAID")]
            self.join.setText(", ".join(f"{c}={c}" for c in common))

    def _accept(self) -> None:
        try:
            self.result_lookup = self.lookup()
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.accept()

    def lookup(self) -> LookupDef:
        table = self.table.text().strip()
        if not table:
            raise ValueError("Choose the related table.")
        pairs = []
        for part in [p.strip() for p in self.join.text().split(",") if p.strip()]:
            if "=" not in part:
                raise ValueError(f"'{part}': write RELATED_COLUMN=MAIN_COLUMN.")
            a, b = (x.strip().upper() for x in part.split("=", 1))
            if self.columns and a not in self.columns:
                raise ValueError(f"{a} is not a column of {table}.")
            if b not in self.main_cols:
                raise ValueError(f"{b} is not a column of {self.main}.")
            pairs.append([a, b])
        if not pairs:
            raise ValueError("Enter at least one pair of link columns.")
        order = [o.strip().upper() for o in self.order.text().split(",") if o.strip()]
        for o in order:
            col, _ = split_order(o)
            if self.columns and col not in self.columns:
                raise ValueError(f"Sort column {col} is not a column of {table}.")
            if self.columns.get(col) in UNSORTABLE_TYPES:
                raise ValueError(f"Cannot sort by {col} ({self.columns[col]}).")
        return LookupDef(table=table.upper(), schema=self.schema.text().strip() or "dbo", join=pairs, order_by=order)


def _approve(ctx: AppContext, name: str) -> None:
    """Add a table/view to the approved list (admin action) and save the settings."""
    sources = ctx.config["approved_sources"]
    if name.upper() not in {s.upper() for s in sources}:
        sources.append(name)
        ctx.save_config()


# ================================================================= page


class ProfilesPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.profile: DataProfile | None = None
        self.saved: DataProfile | None = None  # last saved version (None = new, not saved)
        self.columns: ColumnMap = {}
        self.fields: list[FieldDef] = []
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header(
            "Data Profiles",
            "Which AX table or view to read, which columns to show, search and print. Saving creates a new version.",
        ))
        root.addWidget(self._build_bar())
        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)
        left = QVBoxLayout()
        left.setSpacing(18)
        left.addWidget(self._build_source_card())
        left.addWidget(self._build_fields_card(), 1)
        body.addLayout(left, 1)
        right_w = QWidget()
        right_w.setFixedWidth(430)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(18)
        right.addWidget(self._build_labels_card())
        right.addWidget(self._build_lookups_card())
        right.addWidget(self._build_test_card())
        right.addStretch(1)
        body.addWidget(right_w)
        self.reload()

    # ------------------------------------------------------------- build UI

    def _build_bar(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        lbl = QLabel("Profile")
        lbl.setObjectName("FieldLabel")
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(280)
        self.state_chip = chip("", gray=True)
        row.addWidget(lbl)
        row.addWidget(self.profile_combo)
        row.addWidget(self.state_chip)
        row.addStretch(1)
        self.new_btn, self.dup_btn = QPushButton("New"), QPushButton("Duplicate")
        self.import_btn, self.export_btn = QPushButton("Import..."), QPushButton("Export...")
        self.revert_btn = QPushButton("Revert")
        self.save_btn = QPushButton("  Save")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setIcon(icon("check", "#FFFFFF", size=16))
        for b in (self.new_btn, self.dup_btn, self.import_btn, self.export_btn, self.revert_btn, self.save_btn):
            row.addWidget(b)
        card.body.addLayout(row)
        self.banner = Banner()
        card.body.addWidget(self.banner)
        self.profile_combo.activated.connect(self._on_profile_chosen)
        self.new_btn.clicked.connect(self._new)
        self.dup_btn.clicked.connect(self._duplicate)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.revert_btn.clicked.connect(lambda: self._open(self.profile.id) if self.saved else None)
        self.save_btn.clicked.connect(self._save)
        return card

    def _build_source_card(self) -> Card:
        card = Card("Source")
        f = QFormLayout()
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(8)
        self.name = QLineEdit()
        src_row = QHBoxLayout()
        self.source = QLineEdit()
        self.source.setReadOnly(True)
        self.source.setPlaceholderText("Choose a table or view")
        self.browse_btn = QPushButton("Browse...")
        src_row.addWidget(self.source, 1)
        src_row.addWidget(self.browse_btn)
        self.schema = QLineEdit("dbo")
        self.company_col = QComboBox()
        sort_row = QHBoxLayout()
        self.sort_col = QComboBox()
        self.sort_dir = QComboBox()
        self.sort_dir.addItem("A → Z", "ASC")
        self.sort_dir.addItem("Z → A", "DESC")
        sort_row.addWidget(self.sort_col, 1)
        sort_row.addWidget(self.sort_dir)
        self.row_limit = QSpinBox()
        self.row_limit.setRange(1, 5000)
        f.addRow("Name", self.name)
        f.addRow("Table / view", src_row)
        f.addRow("Schema", self.schema)
        f.addRow("Company column", self.company_col)
        f.addRow("Sort results by", sort_row)
        f.addRow("Max rows", self.row_limit)
        card.body.addLayout(f)
        self.browse_btn.clicked.connect(self._browse_source)
        self.name.textEdited.connect(self._changed)
        self.schema.editingFinished.connect(self._reload_columns)
        for c in (self.company_col, self.sort_col, self.sort_dir):
            c.currentIndexChanged.connect(self._changed)
        self.row_limit.valueChanged.connect(self._changed)
        return card

    def _build_labels_card(self) -> Card:
        card = Card("Labels")
        hint = QLabel("Tick the label templates operators may use with this profile. "
                      "The default label is chosen first on Search & Print.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self.labels = QListWidget()
        self.labels.setMaximumHeight(120)
        card.body.addWidget(self.labels)
        self.template = QComboBox()
        card.body.addWidget(labeled("Default label", self.template))
        self.label_warnings = QLabel("")
        self.label_warnings.setWordWrap(True)
        self.label_warnings.setStyleSheet("color: #B45309;")
        card.body.addWidget(self.label_warnings)
        self.labels.itemChanged.connect(self._on_labels_ticked)
        self.template.currentIndexChanged.connect(self._changed)
        return card

    def _build_fields_card(self) -> Card:
        card = Card("Fields")
        self.fields_chip = chip("", gray=True)
        card.header.addWidget(self.fields_chip)
        hint = QLabel("Header = column title on screen. Search = filter box on Search & Print. "
                      "Fallback = column used when this one is empty (COLUMN or TABLE.COLUMN).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(300)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for col, width in ((1, 170), (2, 118), (3, 90), (8, 130)):  # editable text / combo columns
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        header.setStretchLastSection(True)
        card.body.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.add_fields_btn = QPushButton("  Add fields...")
        self.add_fields_btn.setIcon(icon("plus", size=14))
        self.remove_field_btn = QPushButton("Remove")
        up, down = QPushButton("Move up"), QPushButton("Move down")
        for b in (up, down):
            b.setObjectName("Ghost")
        row.addWidget(self.add_fields_btn)
        row.addWidget(self.remove_field_btn)
        row.addStretch(1)
        row.addWidget(up)
        row.addWidget(down)
        card.body.addLayout(row)
        self.add_fields_btn.clicked.connect(self._add_fields)
        self.remove_field_btn.clicked.connect(self._remove_field)
        up.clicked.connect(lambda: self._move_field(-1))
        down.clicked.connect(lambda: self._move_field(1))
        self.table.itemChanged.connect(lambda *_: self._changed())
        return card

    def _build_lookups_card(self) -> Card:
        card = Card("Related tables")
        hint = QLabel("Optional. Example: AssetBook gives PO, department and acquisition data for each asset. "
                      "Or ask the DBA for one view that already contains everything.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self.lookups = QListWidget()
        self.lookups.setMaximumHeight(120)
        self.lookups.setWordWrap(True)
        card.body.addWidget(self.lookups)
        row = QHBoxLayout()
        add, edit, remove = QPushButton("Add..."), QPushButton("Edit..."), QPushButton("Remove")
        for b in (add, edit, remove):
            row.addWidget(b)
        row.addStretch(1)
        card.body.addLayout(row)
        add.clicked.connect(lambda: self._edit_lookup(None))
        edit.clicked.connect(lambda: self._edit_lookup(self.lookups.currentRow()))
        remove.clicked.connect(self._remove_lookup)
        self.lookups.itemDoubleClicked.connect(lambda _: self._edit_lookup(self.lookups.currentRow()))
        return card

    def _build_test_card(self) -> Card:
        card = Card("Test")
        self.test_chip = chip("", gray=True)
        self.test_chip.hide()
        card.header.addWidget(self.test_chip)
        row = QHBoxLayout()
        self.test_company = QLineEdit()
        self.test_company.setPlaceholderText("Company, e.g. db1")
        self.test_company.setMaximumWidth(120)
        self.test_btn = QPushButton("  Run test query")
        self.test_btn.setIcon(icon("search", size=14))
        row.addWidget(self.test_company)
        row.addWidget(self.test_btn, 1)
        card.body.addLayout(row)
        self.result = QTableWidget(0, 0)
        self.result.verticalHeader().setVisible(False)
        self.result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result.setMinimumHeight(170)
        card.body.addWidget(self.result)
        self.sql = QLabel("")
        self.sql.setObjectName("Mono")
        self.sql.setWordWrap(True)
        self.sql.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sql.hide()
        card.body.addWidget(self.sql)
        self.test_banner = Banner()
        card.body.addWidget(self.test_banner)
        self.test_btn.clicked.connect(self._test)
        return card

    # -------------------------------------------------------------- loading

    def load(self) -> None:  # called by AdminGate after unlocking
        self.reload()

    def reload(self) -> None:
        company = self.ctx.config["database"].get("company", "")
        if not company and self.ctx.using_mock_data:
            company = MOCK_COMPANY
        self.test_company.setText(company)
        current = self.profile.id if self.profile else None
        self._fill_combo(current)
        if self.profile is None:
            self._open(self.profile_combo.currentData())
        elif self.saved is not None and not self._dirty():
            latest = self.ctx.profiles.get(self.profile.id)  # e.g. labels bound from the Label Designer
            if latest is not None and latest.version != self.saved.version:
                self._load(latest, saved=True)
                self._fill_combo(latest.id)
        self._fill_templates()

    def _fill_combo(self, select: str | None) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.ctx.profiles.list_latest():
            self.profile_combo.addItem(icon("table", "#64748B"), f"{p.name}  (v{p.version})", p.id)
        if self.profile and self.profile_combo.findData(self.profile.id) < 0:
            self.profile_combo.addItem(f"{self.profile.name}  (new, not saved)", self.profile.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(select)) if select else 0)
        self.profile_combo.blockSignals(False)

    def _fill_templates(self) -> None:
        """Tick list of all label templates (checked = allowed) + default chooser."""
        self.all_templates = self.ctx.templates.list_latest()
        p = self.profile
        self.labels.blockSignals(True)
        self.labels.clear()
        for t in self.all_templates:
            it = QListWidgetItem(icon("qr", "#64748B"), f"{t.name}  (v{t.version})")
            it.setData(Qt.ItemDataRole.UserRole, t.id)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            allowed = p is None or p.allows_template(t.id)
            it.setCheckState(Qt.CheckState.Checked if allowed else Qt.CheckState.Unchecked)
            self.labels.addItem(it)
        self.labels.blockSignals(False)
        self._fill_default_label(p.template_id if p else "")

    def _ticked_templates(self) -> list[str]:
        return [
            self.labels.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.labels.count())
            if self.labels.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _fill_default_label(self, keep: str) -> None:
        ticked = set(self._ticked_templates())
        self.template.blockSignals(True)
        self.template.clear()
        self.template.addItem("(none)", "")
        for t in getattr(self, "all_templates", []):
            if t.id in ticked:
                self.template.addItem(f"{t.name}  (v{t.version})", t.id)
        idx = self.template.findData(keep)
        if idx < 0 and len(ticked) >= 1:
            idx = 1  # first ticked label becomes the default
        self.template.setCurrentIndex(max(0, idx))
        self.template.blockSignals(False)

    def _on_labels_ticked(self, _item=None) -> None:
        self._fill_default_label(self.template.currentData() or "")
        self._changed()

    def _show_label_warnings(self) -> None:
        if not self.profile:
            return
        p = self.collect()
        by_id = {t.id: t for t in getattr(self, "all_templates", [])}
        issues = [i for tid in self._ticked_templates() if tid in by_id for i in template_issues(by_id[tid], p)]
        self.label_warnings.setText("\n".join(f"⚠ {i}" for i in issues))
        self.label_warnings.setVisible(bool(issues))

    def _on_profile_chosen(self, _i: int) -> None:
        pid = self.profile_combo.currentData()
        if self.profile and pid == self.profile.id:
            return
        if self._dirty() and QMessageBox.question(self, "Unsaved changes", "Discard the unsaved changes?") != QMessageBox.StandardButton.Yes:
            self._fill_combo(self.profile.id)
            return
        self._open(pid)

    def _open(self, pid: str | None) -> None:
        p = self.ctx.profiles.get(pid) if pid else None
        if p is not None:
            self._load(p, saved=True)

    def _load(self, p: DataProfile, saved: bool) -> None:
        self.profile = copy.deepcopy(p)
        self.saved = copy.deepcopy(p) if saved else None
        self.fields = copy.deepcopy(p.fields)
        self._loading = True
        self.name.setText(p.name)
        self.source.setText(p.source)
        self.schema.setText(p.schema)
        self.row_limit.setValue(int(p.row_limit))
        self._fill_templates()
        self._fill_lookups()
        self._fill_fields_table()
        self._loading = False
        self.columns = {}
        self._fill_column_combos()
        self._clear_test()
        self.banner.clear_message()
        self._update_state()
        self._reload_columns()

    # -------------------------------------------------------------- columns

    def _tables(self) -> list[tuple[str, str]]:
        p = self.profile
        out = [(self.schema.text().strip() or "dbo", p.source)] if p and p.source else []
        return out + [(lk.schema, lk.table) for lk in (p.lookups if p else [])]

    def _reload_columns(self) -> None:
        tables = self._tables()
        if not tables:
            return
        run_async(lambda: _columns_of(self.ctx, tables), self._columns_loaded, self._columns_failed)

    def _columns_loaded(self, cols: ColumnMap) -> None:
        self.columns = cols
        self._fill_column_combos()
        self._update_state()

    def _columns_failed(self, e: Exception) -> None:
        self.banner.show_message(f"Cannot read columns: {error_text(e)}", "error")

    def _main_cols(self) -> dict[str, str]:
        return self.columns.get(self.profile.source.upper(), {}) if self.profile else {}

    def _fill_column_combos(self) -> None:
        p = self.profile
        if not p:
            return
        self._loading = True
        cols = self._main_cols()
        self.company_col.clear()
        self.company_col.addItem("(no company filter)", NO_COMPANY)
        for c in cols or ([p.dataarea_column] if p.dataarea_column else []):
            self.company_col.addItem(c, c)
        self.company_col.setCurrentIndex(max(0, self.company_col.findData(p.dataarea_column or NO_COMPANY)))
        self.sort_col.clear()
        for f in self.fields:
            self.sort_col.addItem(f.alias or f.column, f.column)
        col, direction = split_order(p.order_by[0]) if p.order_by else ((self.fields[0].column if self.fields else ""), "ASC")
        self.sort_col.setCurrentIndex(max(0, self.sort_col.findData(col)))
        self.sort_dir.setCurrentIndex(max(0, self.sort_dir.findData(direction)))
        self._loading = False

    # --------------------------------------------------------------- fields

    def _fill_fields_table(self) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for f in self.fields:
            self._append_row(f)
        self.fields_chip.setText(f"{len(self.fields)} fields")
        self._loading = False

    def _append_row(self, f: FieldDef) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        key = QTableWidgetItem(f.column)
        key.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        key.setToolTip(f"{f.table or 'main table'}.{f.source}")
        self.table.setItem(r, 0, key)
        self.table.setItem(r, 1, QTableWidgetItem(f.alias))
        typ = QComboBox()
        typ.addItems(TYPES)
        typ.setCurrentText(f.data_type if f.data_type in TYPES else "string")
        typ.currentIndexChanged.connect(lambda *_: self._changed())
        self.table.setCellWidget(r, 2, typ)
        self.table.setItem(r, 3, QTableWidgetItem(f.fmt))
        for col, attr in CHECK_COLS.items():
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            it.setCheckState(Qt.CheckState.Checked if getattr(f, attr) else Qt.CheckState.Unchecked)
            self.table.setItem(r, col, it)
        self.table.setItem(r, 8, QTableWidgetItem(f.fallback))
        src = QTableWidgetItem(f.table or "main")
        src.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        src.setForeground(QColor("#64748B"))
        self.table.setItem(r, 9, src)

    def _read_fields(self) -> list[FieldDef]:
        out = []
        for r, base in enumerate(self.fields):
            f = copy.deepcopy(base)
            f.alias = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            f.data_type = self.table.cellWidget(r, 2).currentText()
            f.fmt = (self.table.item(r, 3).text() if self.table.item(r, 3) else "").strip()
            for col, attr in CHECK_COLS.items():
                setattr(f, attr, self.table.item(r, col).checkState() == Qt.CheckState.Checked)
            f.fallback = (self.table.item(r, 8).text() if self.table.item(r, 8) else "").strip().upper()
            out.append(f)
        return out

    def _add_fields(self) -> None:
        if not self.profile or not self.profile.source:
            self.banner.show_message("Choose a table or view first.", "info")
            return
        if not self.columns:
            self.banner.show_message("Columns are still loading - try again in a moment.", "info")
            self._reload_columns()
            return
        self.fields = self._read_fields()
        used = {((f.table or self.profile.source).upper(), f.source.upper()) for f in self.fields}
        tables = [(f"{self.profile.source} (main)", self.profile.source)] + [(lk.table, lk.table) for lk in self.profile.lookups]
        dlg = AddFieldsDialog(self, self.columns, tables, used)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        keys = {f.column.upper() for f in self.fields}
        for table, col, typ in dlg.selected():
            f = new_field(col, typ, "" if table.upper() == self.profile.source.upper() else table, keys)
            keys.add(f.column.upper())
            self.fields.append(f)
        self._fill_fields_table()
        self._fill_column_combos()
        self._changed()

    def _remove_field(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        self.fields = self._read_fields()
        removed = self.fields.pop(r)
        self._fill_fields_table()
        self._fill_column_combos()
        self._changed()
        if removed.column.upper() in {c.upper() for c in self.profile.qr.fields}:
            self.banner.show_message(f"{removed.label} was used in the QR code. Check QR Configuration after saving.", "warning")

    def _move_field(self, delta: int) -> None:
        r = self.table.currentRow()
        t = r + delta
        if r < 0 or not 0 <= t < len(self.fields):
            return
        self.fields = self._read_fields()
        self.fields[r], self.fields[t] = self.fields[t], self.fields[r]
        self._fill_fields_table()
        self.table.selectRow(t)
        self._changed()

    # -------------------------------------------------------------- lookups

    def _fill_lookups(self) -> None:
        self.lookups.clear()
        for lk in self.profile.lookups if self.profile else []:
            join = ", ".join(f"{a}={b}" for a, b in lk.join)
            order = f"; first by {', '.join(lk.order_by)}" if lk.order_by else ""
            self.lookups.addItem(QListWidgetItem(icon("table", "#64748B"), f"{lk.table}  on {join}{order}"))

    def _edit_lookup(self, index: int | None) -> None:
        if not self.profile or not self.profile.source:
            self.banner.show_message("Choose the main table or view first.", "info")
            return
        lk = self.profile.lookups[index] if index is not None and 0 <= index < len(self.profile.lookups) else None
        if index is not None and lk is None:
            return
        dlg = LookupDialog(self, self.ctx, self.profile.source, self._main_cols(), lk)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.result_lookup
        others = [x.table.upper() for i, x in enumerate(self.profile.lookups) if i != index]
        if new.table in others:
            self.banner.show_message(f"{new.table} is already a related table.", "error")
            return
        if lk is None:
            self.profile.lookups.append(new)
        else:
            self.profile.lookups[index] = new
        self._fill_lookups()
        self._reload_columns()
        self._changed()

    def _remove_lookup(self) -> None:
        i = self.lookups.currentRow()
        if not self.profile or i < 0:
            return
        table = self.profile.lookups[i].table.upper()
        self.fields = self._read_fields()
        using = [f.label for f in self.fields if f.table.upper() == table]
        if using:
            self.banner.show_message(f"Remove the fields from {table} first: {', '.join(using)}.", "error")
            return
        self.profile.lookups.pop(i)
        self._fill_lookups()
        self._changed()

    # --------------------------------------------------------------- source

    def _browse_source(self) -> None:
        dlg = SourcePickerDialog(self, self.ctx)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        schema, name = dlg.choice
        if self.profile.source and name.upper() != self.profile.source.upper() and self.fields:
            if QMessageBox.question(self, "Change table", "Changing the table removes the current fields and related tables. Continue?") != QMessageBox.StandardButton.Yes:
                return
            self.fields, self.profile.lookups = [], []
            self._fill_fields_table()
            self._fill_lookups()
        _approve(self.ctx, name)
        self.profile.source = name
        self.source.setText(name)
        self.schema.setText(schema)
        self.columns = {}
        self._reload_columns()
        self._changed()

    # ------------------------------------------------------------- collect

    def collect(self) -> DataProfile:
        p = copy.deepcopy(self.profile)
        p.name = self.name.text().strip()
        p.schema = self.schema.text().strip() or "dbo"
        p.fields = self._read_fields()
        comp = self.company_col.currentData()
        p.dataarea_column = "" if comp in (None, NO_COMPANY) else comp
        sort = self.sort_col.currentData()
        p.order_by = [f"{sort} {self.sort_dir.currentData()}" if self.sort_dir.currentData() == "DESC" else sort] if sort else []
        p.row_limit = self.row_limit.value()
        p.template_id = self.template.currentData() or ""
        ticked = self._ticked_templates()
        everything = [t.id for t in getattr(self, "all_templates", [])]
        if not self.profile.template_ids and sorted(ticked) == sorted(everything):
            p.template_ids = []  # older profile with every label ticked: keep "all labels"
        else:
            p.template_ids = ticked
        keys = {f.column.upper() for f in p.fields}
        p.qr.fields = [c for c in p.qr.fields if c.upper() in keys]
        if not p.qr.fields and p.fields:
            p.qr = QrConfig(format="plain", fields=[p.fields[0].column])
        return p

    def _dirty(self) -> bool:
        if not self.profile:
            return False
        return self.saved is None or self.collect() != self.saved

    def _changed(self, *_) -> None:
        if not self._loading:
            self._update_state()

    def _update_state(self) -> None:
        if not self.profile:
            return
        dirty = self._dirty()
        self.state_chip.setObjectName("Chip" if dirty else "ChipGray")
        self.state_chip.setText("● Unsaved changes" if dirty else f"Saved · v{self.saved.version}")
        self.state_chip.style().unpolish(self.state_chip)
        self.state_chip.style().polish(self.state_chip)
        self.revert_btn.setEnabled(dirty and self.saved is not None)
        self.fields_chip.setText(f"{self.table.rowCount()} fields")
        self._show_label_warnings()

    # --------------------------------------------------------------- actions

    def _new(self) -> None:
        if self._dirty() and QMessageBox.question(self, "Unsaved changes", "Discard the unsaved changes?") != QMessageBox.StandardButton.Yes:
            return
        p = DataProfile(id=new_id(), name="New profile", source="", dataarea_column="DATAAREAID", row_limit=200)
        self._load(p, saved=False)
        self._fill_combo(p.id)
        self.banner.show_message("Press Browse... to choose the table or view.", "info")

    def _duplicate(self) -> None:
        if not self.profile:
            return
        d = duplicate_profile(self.collect())
        self._load(d, saved=False)
        self._fill_combo(d.id)
        self.banner.show_message("Copy created. Press Save to keep it.", "info")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import data profile", "", "Data profile (*.json)")
        if not path:
            return
        try:
            p = import_profile(Path(path))
        except Exception as e:
            self.banner.show_message(error_text(e), "error")
            return
        for t in [p.source] + [lk.table for lk in p.lookups]:
            _approve(self.ctx, t)
        self._load(p, saved=False)
        self._fill_combo(p.id)
        self.banner.show_message(f"Imported '{p.name}'. Check it with Run test query, then Save.", "info")

    def _export(self) -> None:
        if not self.profile:
            return
        p = self.collect()
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in p.name).strip() or "profile"
        path, _ = QFileDialog.getSaveFileName(self, "Export data profile", f"{safe}.json", "Data profile (*.json)")
        if path:
            export_profile(p, Path(path))
            self.banner.show_message(f"Exported to {path}", "success")

    def _check(self, p: DataProfile, cols: ColumnMap) -> list[str]:
        problems = validate_profile(p, cols, {t.id for t in self.ctx.templates.list_latest()})
        if not problems:
            try:
                build_select(p, {}, "x" if p.dataarea_column else "", approved_sources=self.ctx.config["approved_sources"],
                             allowed_columns={t: list(c) for t, c in cols.items()})
            except Exception as e:
                problems.append(error_text(e))
        return problems

    def _save(self) -> None:
        if not self.profile:
            return
        p = self.collect()
        if not p.source:
            self.banner.show_message("Choose a table or view first.", "error")
            return
        tables = [(p.schema, p.source)] + [(lk.schema, lk.table) for lk in p.lookups]
        self.save_btn.setEnabled(False)
        self.banner.show_message("Checking the profile against the database...", "info")
        run_async(lambda: _columns_of(self.ctx, tables), lambda cols: self._save_checked(p, cols), self._save_failed)

    def _save_checked(self, p: DataProfile, cols: ColumnMap) -> None:
        self.save_btn.setEnabled(True)
        self.columns = cols
        problems = self._check(p, cols)
        latest = self.ctx.profiles.get(p.id)
        if self.saved is not None and latest is not None and latest.version != self.saved.version:
            problems.insert(0, f"This profile was changed somewhere else (now version {latest.version}). "
                               "Press Revert to load it, then make your change again.")
        if problems:
            self.banner.show_message("Not saved - please fix:\n• " + "\n• ".join(problems), "error")
            return
        saved = self.ctx.profiles.save(copy.deepcopy(p))
        self._load(saved, saved=True)
        self._fill_combo(saved.id)
        self.banner.show_message(
            f"Saved '{saved.name}' as version {saved.version}. It is available on Search & Print "
            "(check QR Configuration for what goes into the QR code).", "success")

    def _save_failed(self, e: Exception) -> None:
        self.save_btn.setEnabled(True)
        self.banner.show_message(error_text(e), "error")

    # ------------------------------------------------------------------ test

    def _clear_test(self) -> None:
        self.result.setRowCount(0)
        self.result.setColumnCount(0)
        self.sql.hide()
        self.test_chip.hide()
        self.test_banner.clear_message()

    def _test(self) -> None:
        if not self.profile:
            return
        p = self.collect()
        p.row_limit = min(p.row_limit, TEST_ROWS)
        company = self.test_company.text().strip()
        try:
            sql, _ = build_select(p, {}, company, approved_sources=self.ctx.config["approved_sources"])
        except Exception as e:
            self.test_banner.show_message(error_text(e), "error")
            return
        self.sql.setText(sql)
        self.sql.show()
        self.test_btn.setEnabled(False)
        self.test_banner.show_message("Running...", "info")
        run_async(lambda: self.ctx.data_source().search(p, {}, company), lambda rows: self._tested(p, rows), self._test_failed)

    def _tested(self, p: DataProfile, rows) -> None:
        self.test_btn.setEnabled(True)
        fields = [f for f in p.fields if f.display] or p.fields
        self.result.setColumnCount(len(fields))
        self.result.setHorizontalHeaderLabels([f.label for f in fields])
        self.result.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            for c, f in enumerate(fields):
                self.result.setItem(r, c, QTableWidgetItem(" ".join(format_value(rec.get(f.column.upper()), f).split())))
        self.result.resizeColumnsToContents()
        self.test_chip.setText(f"{len(rows)} rows")
        self.test_chip.show()
        problems = validate_profile(p, self.columns or None)
        if problems:
            self.test_banner.show_message("Query works, but fix before saving:\n• " + "\n• ".join(problems), "warning")
        else:
            self.test_banner.show_message(f"OK - first {len(rows)} rows shown.", "success")

    def _test_failed(self, e: Exception) -> None:
        self.test_btn.setEnabled(True)
        self.test_banner.show_message(error_text(e), "error")
