"""QR Configuration: which fields go into the QR code and how they are joined."""
from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.context import AppContext
from ...domain.models import DataProfile, LabelElement, QrConfig
from ...rendering.raster import rasterize_qr
from ...services.qr_payload import QR_BYTE_CAPACITY
from ..icons import icon
from ..widgets import Banner, Card, chip, labeled, page_header, pil_to_pixmap, sticker_pixmap
from ..workers import error_text, run_async


LABEL_ROLE = Qt.ItemDataRole.UserRole + 1  # label used inside the QR (labeled format)
NAME_ROLE = Qt.ItemDataRole.UserRole + 2  # field display name


def try_decode(img) -> str | None:
    """Decode a QR image with OpenCV if it is installed (development builds). None = not available."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    from PIL import Image

    big = img.convert("L").resize((img.width * 3, img.height * 3), Image.Resampling.NEAREST)
    canvas = Image.new("L", (big.width + 80, big.height + 80), 255)
    canvas.paste(big, (40, 40))
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(np.array(canvas))
    return text


class QrConfigPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.profiles: list[DataProfile] = []
        self.record: dict[str, Any] | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addWidget(page_header("QR Configuration", "Choose what is encoded in the QR code. Saving creates a new profile version."))
        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        # ------------------------------------------------------------ config
        cfg = Card("QR content")
        self.version_chip = chip("", gray=True)
        cfg.header.addWidget(self.version_chip)
        self.profile_combo = QComboBox()
        cfg.body.addWidget(labeled("Data profile", self.profile_combo))

        self.fields = QListWidget()
        self.fields.setMinimumHeight(170)
        self.fields.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.fields.setStyleSheet(
            "QListWidget { border: 1px solid #CBD5E1; border-radius: 8px; padding: 4px; background: #FFFFFF; }"
            "QListWidget::item { padding: 6px; border-radius: 6px; }"
            "QListWidget::item:selected { background: #EFF6FF; color: #0F172A; }"
        )
        order = QHBoxLayout()
        up, down = QPushButton("Move up"), QPushButton("Move down")
        up.setObjectName("Ghost")
        down.setObjectName("Ghost")
        order.addStretch(1)
        order.addWidget(up)
        order.addWidget(down)
        cfg.body.addWidget(labeled("Fields in the QR (tick, then drag or move to order)", self.fields))
        cfg.body.addLayout(order)

        f = QFormLayout()
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(8)
        self.format = QComboBox()
        self.format.addItem("Plain - one field only", "plain")
        self.format.addItem("Delimited - fields joined by a separator", "delimited")
        self.format.addItem("JSON - {\"label\": \"value\"}", "json")
        self.format.addItem("Labeled lines - \"Label : value\" per line (previous app)", "labeled")
        self.delimiter = QLineEdit()
        self.delimiter.setMaxLength(5)
        self.qr_label = QLineEdit()
        self.qr_label.setMaxLength(40)
        self.qr_label.setPlaceholderText("Select a field above, then type its label in the QR")
        self.label_sep = QLineEdit()
        self.label_sep.setMaxLength(5)
        self.line_sep = QComboBox()
        for text, sep in (("New line (CR+LF)", "\r\n"), ("New line (LF)", "\n"), ("Space", " "), ("Semicolon", "; ")):
            self.line_sep.addItem(text, sep)
        self.prefix = QLineEdit()
        self.prefix.setMaxLength(50)
        self.suffix = QLineEdit()
        self.suffix.setMaxLength(50)
        self.null_policy = QComboBox()
        self.null_policy.addItem("Stop - do not print the label", "error")
        self.null_policy.addItem("Allow empty value", "empty")
        self.ecc = QComboBox()
        for key, text in (("L", "L - 7% recovery"), ("M", "M - 15% recovery (default)"), ("Q", "Q - 25% recovery"), ("H", "H - 30% recovery")):
            self.ecc.addItem(text, key)
        self.max_bytes = QSpinBox()
        self.max_bytes.setRange(1, QR_BYTE_CAPACITY["L"])
        self.max_bytes.setSuffix(" bytes")
        f.addRow("Format", self.format)
        f.addRow("Separator", self.delimiter)
        f.addRow("Label in QR", self.qr_label)
        f.addRow("Between label and value", self.label_sep)
        f.addRow("Between lines", self.line_sep)
        f.addRow("Prefix", self.prefix)
        f.addRow("Suffix", self.suffix)
        f.addRow("Empty field", self.null_policy)
        f.addRow("Error correction", self.ecc)
        f.addRow("Max length", self.max_bytes)
        self.form = f
        cfg.body.addLayout(f)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.revert_btn = QPushButton("Revert")
        self.save_btn = QPushButton("  Save")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setIcon(icon("check", "#FFFFFF", size=16))
        buttons.addWidget(self.revert_btn)
        buttons.addWidget(self.save_btn)
        cfg.body.addLayout(buttons)
        self.banner = Banner()
        cfg.body.addWidget(self.banner)
        body.addWidget(cfg, 1)

        # ------------------------------------------------------------- test
        test = Card("Test")
        row = QHBoxLayout()
        self.test_id = QLineEdit("FA-IT-5-26-0001")
        self.load_btn = QPushButton("Load from AX")
        row.addWidget(self.test_id, 1)
        row.addWidget(self.load_btn)
        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        test.body.addWidget(labeled("Asset to test with (first profile field)", w))
        self.record_label = QLabel("Using sample values. Load a record to test real data.")
        self.record_label.setObjectName("Muted")
        self.record_label.setWordWrap(True)
        test.body.addWidget(self.record_label)
        self.qr_image = QLabel()
        self.qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_image.setMinimumHeight(230)
        self.qr_image.setStyleSheet("QLabel { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #E2E8F0, stop:1 #CBD5E1); border-radius: 12px; }")
        test.body.addWidget(self.qr_image)
        self.payload = QLabel("")
        self.payload.setObjectName("Mono")
        self.payload.setWordWrap(True)
        self.payload.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        test.body.addWidget(self.payload)
        self.result = Banner()
        test.body.addWidget(self.result)
        test.body.addStretch(1)
        test.setFixedWidth(420)
        body.addWidget(test)

        self.profile_combo.currentIndexChanged.connect(self._on_profile)
        for c in (self.format, self.null_policy, self.ecc):
            c.currentIndexChanged.connect(self._preview)
        for e in (self.delimiter, self.prefix, self.suffix, self.label_sep):
            e.textChanged.connect(self._preview)
        self.line_sep.currentIndexChanged.connect(self._preview)
        self.qr_label.textEdited.connect(self._on_qr_label_edited)
        self.fields.currentRowChanged.connect(self._on_field_row)
        self.max_bytes.valueChanged.connect(self._preview)
        self.fields.itemChanged.connect(lambda *_: self._preview())
        self.fields.model().rowsMoved.connect(lambda *_: self._preview())
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        self.save_btn.clicked.connect(self._save)
        self.revert_btn.clicked.connect(self._on_profile)
        self.load_btn.clicked.connect(self._load_record)
        self.test_id.returnPressed.connect(self._load_record)
        self.reload()

    # ----------------------------------------------------------------- data

    def reload(self) -> None:
        current = self.profile_combo.currentData()
        self.profiles = self.ctx.profiles.list_latest()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(f"{p.name}  (v{p.version})", p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(current)))
        self.profile_combo.blockSignals(False)
        self._on_profile()

    def profile(self) -> DataProfile | None:
        pid = self.profile_combo.currentData()
        return next((p for p in self.profiles if p.id == pid), None)

    def _on_profile(self, *_):
        p = self.profile()
        if not p:
            return
        self._loading = True
        self.version_chip.setText(f"v{p.version}")
        q = p.qr
        self.fields.clear()
        chosen = [c.upper() for c in q.fields]
        ordered = [p.get_field(c) for c in q.fields if p.get_field(c)] + [f for f in p.fields if f.column.upper() not in chosen]
        labels = {k.upper(): v for k, v in q.labels.items()}
        for fd in ordered:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, fd.column)
            item.setData(LABEL_ROLE, labels.get(fd.column.upper(), ""))
            item.setData(NAME_ROLE, fd.label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if fd.column.upper() in chosen else Qt.CheckState.Unchecked)
            self._set_item_text(item)
            self.fields.addItem(item)
        self.format.setCurrentIndex(max(0, self.format.findData(q.format)))
        self.delimiter.setText(q.delimiter)
        self.label_sep.setText(q.label_separator)
        idx = self.line_sep.findData(q.line_separator)
        if idx < 0:
            self.line_sep.addItem(repr(q.line_separator), q.line_separator)
            idx = self.line_sep.count() - 1
        self.line_sep.setCurrentIndex(idx)
        self.qr_label.clear()
        self.prefix.setText(q.prefix)
        self.suffix.setText(q.suffix)
        self.null_policy.setCurrentIndex(max(0, self.null_policy.findData(q.null_policy)))
        self.ecc.setCurrentIndex(max(0, self.ecc.findData(q.error_correction)))
        self.max_bytes.setValue(q.max_bytes)
        self._loading = False
        self.record = None
        self.record_label.setText("Using sample values. Load a record to test real data.")
        self.banner.clear_message()
        self._preview()

    def _move(self, delta: int) -> None:
        row = self.fields.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.fields.count():
            return
        item = self.fields.takeItem(row)
        self.fields.insertItem(target, item)
        self.fields.setCurrentRow(target)
        self._preview()

    def _set_item_text(self, item: QListWidgetItem) -> None:
        text = f"{item.data(NAME_ROLE)}   ·   {item.data(Qt.ItemDataRole.UserRole)}"
        if item.data(LABEL_ROLE):
            text += f"      QR label: “{item.data(LABEL_ROLE)}”"
        item.setText(text)

    def _on_field_row(self, row: int) -> None:
        item = self.fields.item(row) if row >= 0 else None
        self.qr_label.setEnabled(item is not None)
        self.qr_label.setText(item.data(LABEL_ROLE) if item else "")

    def _on_qr_label_edited(self, text: str) -> None:
        item = self.fields.currentItem()
        if item is None:
            return
        item.setData(LABEL_ROLE, text.strip())
        self._set_item_text(item)
        self._preview()

    def form_config(self) -> QrConfig:
        items = [self.fields.item(i) for i in range(self.fields.count())]
        cols = [it.data(Qt.ItemDataRole.UserRole) for it in items if it.checkState() == Qt.CheckState.Checked]
        labels = {it.data(Qt.ItemDataRole.UserRole): it.data(LABEL_ROLE) for it in items if it.data(LABEL_ROLE)}
        return QrConfig(
            format=self.format.currentData(), fields=cols, delimiter=self.delimiter.text(),
            labels=labels, label_separator=self.label_sep.text(), line_separator=self.line_sep.currentData(),
            prefix=self.prefix.text(), suffix=self.suffix.text(), null_policy=self.null_policy.currentData(),
            error_correction=self.ecc.currentData(), max_bytes=self.max_bytes.value(),
        )

    def _edited_profile(self) -> DataProfile | None:
        p = self.profile()
        if not p:
            return None
        edited = copy.deepcopy(p)
        edited.qr = self.form_config()
        return edited

    def _sample_record(self, p: DataProfile) -> dict[str, Any]:
        if self.record is not None:
            return self.record
        rec = {}
        for i, fd in enumerate(p.fields):
            rec[fd.column.upper()] = self.test_id.text().strip() if i == 0 else f"Sample {fd.label}"
        return rec

    # -------------------------------------------------------------- preview

    def _preview(self, *_):
        if self._loading:
            return
        self.form.setRowVisible(self.delimiter, self.format.currentData() == "delimited")
        labeled = self.format.currentData() == "labeled"
        for w in (self.qr_label, self.label_sep, self.line_sep):
            self.form.setRowVisible(w, labeled)
        p = self._edited_profile()
        if not p:
            return
        changed = p.qr != self.profile().qr
        self.save_btn.setEnabled(changed)
        self.revert_btn.setEnabled(changed)
        try:
            payload = self.ctx.payloads.build(self._sample_record(p), p)
        except Exception as e:
            self.qr_image.clear()
            self.payload.setText("-")
            self.result.show_message(error_text(e), "error")
            return
        cap = QR_BYTE_CAPACITY[payload.error_correction]
        self.payload.setText(f"{payload.text}\n\n{payload.byte_length} bytes (limit {min(p.qr.max_bytes, cap)})")
        el = LabelElement(kind="qr", x_mm=0, y_mm=0, w_mm=30, h_mm=30)
        placed, geo = rasterize_qr(payload.text, payload.error_correction, el, 203)
        img = placed.image.convert("L")
        self.qr_image.setPixmap(sticker_pixmap(pil_to_pixmap(img), 360, 230))
        decoded = try_decode(img)
        size_mm = geo.size * 25.4 / 203
        info = f"QR version with {geo.modules}×{geo.modules} modules; {size_mm:.1f} mm at {geo.cell} dots per module on a 30 mm box."
        if decoded is None:
            self.result.show_message(info + "\nDecode check not available in this build - scan a printed label.", "info")
        elif decoded == payload.text:
            self.result.show_message("✓ Decoded correctly.\n" + info, "success")
        else:
            self.result.show_message(f"Decoded text does not match: {decoded!r}", "error")

    def _load_record(self) -> None:
        p = self.profile()
        if not p or not p.fields:
            return
        key = p.fields[0].column
        value = self.test_id.text().strip()
        company = self.ctx.config["database"].get("company", "") or "smp"
        self.load_btn.setEnabled(False)

        def work():
            rows = self.ctx.data_source().search(p, {key: value} if p.fields[0].searchable else {}, company)
            exact = [r for r in rows if str(r.get(key.upper(), "")).strip().upper() == value.upper()]
            return (exact or rows or [None])[0]

        run_async(work, self._on_record, self._on_record_error)

    def _on_record(self, rec) -> None:
        self.load_btn.setEnabled(True)
        if rec is None:
            self.record = None
            self.record_label.setText("No record found - using sample values.")
        else:
            self.record = rec
            p = self.profile()
            first = p.fields[0].column.upper() if p else ""
            self.record_label.setText(f"Testing with AX record {rec.get(first, '')}.")
        self._preview()

    def _on_record_error(self, e: Exception) -> None:
        self.load_btn.setEnabled(True)
        self.record_label.setText(error_text(e))

    # ----------------------------------------------------------------- save

    def _save(self) -> None:
        p = self._edited_profile()
        if not p:
            return
        try:
            self.ctx.payloads.build(self._sample_record(p), p)  # refuse configs that cannot build
        except Exception as e:
            self.banner.show_message("Not saved: " + error_text(e), "error")
            return
        saved = self.ctx.profiles.save(p)
        self.reload()
        self.banner.show_message(f"Saved as profile version {saved.version}. New prints use this QR setting.", "success")
