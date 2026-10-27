"""Scanning the journal number: '+' from the scanner becomes '_', search starts after the scan."""
import pytest

from qrlabel.app.defaults import JOURNAL_SOURCES, default_journal_profile
from qrlabel.domain.errors import ValidationError
from qrlabel.domain.models import DataProfile
from qrlabel.services.profile_rules import validate_profile
from qrlabel.services.query_builder import apply_replace, build_select, parse_replace

APPROVED = JOURNAL_SOURCES


def test_parse_and_apply_replace():
    assert parse_replace("+>_  ;>,") == [("+", "_"), (";", ",")]
    assert apply_replace("90959F+072", "+>_") == "90959F_072"
    assert apply_replace("A+1;B+2", "+>_ ;>,") == "A_1,B_2"
    assert apply_replace("x+y", "") == "x+y"
    assert apply_replace("ab", "a>") == "b"  # FROM> with nothing removes the character
    for bad in ("+_", ">_", "+>_>x"):
        with pytest.raises(ValidationError):
            parse_replace(bad)


def test_scanned_journal_searches_with_underscore():
    p = default_journal_profile()
    sql, params = build_select(p, {"JOURNALID": "90959F+072"}, "db1", approved_sources=APPROVED, virtual_company="vir")
    assert "a.[JOURNALID] LIKE ?" in sql
    assert params[-1] == "90959F\\_072%"  # '_' escaped: matched literally, not as a LIKE wildcard


def test_list_of_scans_is_replaced_too():
    _, params = build_select(default_journal_profile(), {"JOURNALID": "90959F+072, 90960F+072"}, "db1",
                             approved_sources=APPROVED, virtual_company="vir")
    assert params[-2:] == ["90959F_072", "90960F_072"]


def test_old_profiles_load_without_barcode_settings(profile):
    d = profile.to_dict()
    for f in d["fields"]:
        f.pop("barcode")
        f.pop("replace")
    loaded = DataProfile.from_dict(d)
    assert not any(f.barcode or f.replace for f in loaded.fields)


def test_validation():
    p = default_journal_profile()
    p.fields[0].replace = "+_"
    assert any("must look like FROM>TO" in i for i in validate_profile(p, None))
    p.fields[0].replace = "+>_"
    p.fields[0].searchable = False
    assert any("Barcode needs Search" in i for i in validate_profile(p, None))


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _type(watcher, edit, text, gap_ms, clock):
    for ch in text:
        clock.t += gap_ms / 1000
        edit.setText(edit.text() + ch)
        watcher._typed(edit.text())


def test_scan_watcher(qapp, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    from qrlabel.ui.pages import search_print

    clock = _Clock()
    monkeypatch.setattr(search_print.time, "monotonic", clock)
    edit = QLineEdit()
    hits = []
    w = search_print.ScanWatcher(edit, lambda: hits.append(edit.text()))

    _type(w, edit, "90959F+072", 5, clock)  # scanner: 5 ms per character
    w._idle()
    assert hits == ["90959F+072"]

    edit.clear()
    _type(w, edit, "90959F", 180, clock)  # a person typing: no automatic search
    w._idle()
    assert hits == ["90959F+072"]

    edit.clear()
    _type(w, edit, "90959F_072", 5, clock)
    edit.returnPressed.emit()  # scanner with Enter suffix: Enter searches, the idle timer does not again
    assert not w.timer.isActive()
    w._idle()
    assert len(hits) == 1


def test_replace_live(qapp):
    from PySide6.QtWidgets import QLineEdit

    from qrlabel.ui.pages.search_print import _replace_live

    edit = QLineEdit("90959F+072")
    edit.setCursorPosition(10)
    _replace_live(edit, edit.text(), "+>_")
    assert edit.text() == "90959F_072" and edit.cursorPosition() == 10


def test_tooltips_follow_the_field(qapp, profile):
    from qrlabel.ui.pages.search_print import search_tooltip

    j = default_journal_profile()
    journal, item = j.get_field("JOURNALID"), j.get_field("ITEMID")
    tip = search_tooltip(journal)
    assert "Search Journal" in tip and "90959F_072" in tip and "FA-IT" not in tip
    assert "Scan the barcode" in tip and "+ becomes _" in tip
    tip = search_tooltip(item, ["HW-F005", "AUSU06BSE01", "HW-F005"])
    assert "AUSU06BSE01..HW-F005" in tip and "FA-IT" not in tip and "Scan" not in tip
    assert "FA-IT-5-26-0001" in search_tooltip(profile.get_field("ASSETID"))
    other = search_tooltip(j.get_field("VOUCHER").__class__(column="XYZ", alias="Other", searchable=True))
    assert "ABC-001" in other
