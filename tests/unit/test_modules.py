"""Parts of the program chosen in the installer: Asset labels and/or Stock labels."""
import json

import pytest

from qrlabel.app.defaults import DEFAULT_PROFILE_ID, JOURNAL_PROFILE_ID, bundled_template_id, bundled_templates
from qrlabel.app.modules import (
    apply_install_options,
    clean_modules,
    enabled_modules,
    ensure_modules,
    hidden_profile_ids,
    read_install_options,
)

STOCK_ID = "25c45638326c4a489b36112d4c1e8c09"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path / "data"))
    from qrlabel.app.context import AppContext

    return AppContext()


def _options(tmp_path, modules):
    f = tmp_path / "install-options.json"
    f.write_text(json.dumps({"modules": modules}), encoding="utf-8")
    return f


def test_clean_modules():
    assert clean_modules(["journal", "asset", "x"]) == ["asset", "journal"]
    assert clean_modules([]) == ["asset", "journal"]  # never nothing
    assert clean_modules(None) == ["asset", "journal"]


def test_read_install_options(tmp_path):
    assert read_install_options(None) is None
    assert read_install_options(tmp_path / "missing.json") is None
    assert read_install_options(_options(tmp_path, ["journal"])) == ["journal"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_install_options(bad) is None
    bom = tmp_path / "bom.json"  # Inno Setup / Notepad may write a BOM
    bom.write_bytes(b"\xef\xbb\xbf" + b'{"modules": ["asset"]}')
    assert read_install_options(bom) == ["asset"]


def test_bundled_stock_label():
    assert bundled_template_id("journal") == STOCK_ID
    templates, _ = bundled_templates()
    t = next(t for t in templates if t.id == STOCK_ID)
    assert (t.width_mm, t.height_mm) == (100.0, 32.0)
    fields = {e.field for e in t.elements if e.field} | {"INVENTSIZEID"}
    assert {"ITEMID", "QTY", "UNITID", "ITEMNAME", "INVENTBATCHID", "NOTES"} <= fields
    assert any("{INVENTSIZEID}" in e.text for e in t.elements)


def test_default_is_everything(ctx):
    assert enabled_modules(ctx) == ["asset", "journal"]
    assert hidden_profile_ids(ctx) == set()
    assert ctx.profiles.get(JOURNAL_PROFILE_ID) is not None


def test_installer_choice_stock_only(ctx, tmp_path):
    assert apply_install_options(ctx, _options(tmp_path, ["journal"])) is True
    assert enabled_modules(ctx) == ["journal"]
    assert hidden_profile_ids(ctx) == {DEFAULT_PROFILE_ID}


def test_same_choice_again_keeps_admin_change(ctx, tmp_path):
    f = _options(tmp_path, ["journal"])
    apply_install_options(ctx, f)
    ctx.config["modules"] = ["asset", "journal"]  # admin changed it in Application Settings
    ctx.save_config()
    assert apply_install_options(ctx, f) is False  # re-install / upgrade with the same choice
    assert enabled_modules(ctx) == ["asset", "journal"]
    assert apply_install_options(ctx, _options(tmp_path, ["asset"])) is True  # a new choice wins
    assert enabled_modules(ctx) == ["asset"]


def test_choice_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path / "data"))
    from qrlabel.app.context import AppContext

    apply_install_options(AppContext(), _options(tmp_path, ["asset"]))
    assert enabled_modules(AppContext()) == ["asset"]


def test_asset_only_install_has_no_journal_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path / "data"))
    import qrlabel.app.modules as modules

    monkeypatch.setattr(modules, "install_options_path", lambda: _options(tmp_path, ["asset"]))
    from qrlabel.app.context import AppContext

    ctx = AppContext()
    assert enabled_modules(ctx) == ["asset"]
    assert ctx.profiles.get(JOURNAL_PROFILE_ID) is None
    assert "INVENTJOURNALTRANS" not in {s.upper() for s in ctx.config["approved_sources"]}
    ctx.config["modules"] = ["asset", "journal"]  # admin turns Stock labels on later
    ensure_modules(ctx)
    assert ctx.profiles.get(JOURNAL_PROFILE_ID).template_ids == [STOCK_ID]


def test_search_page_offers_only_enabled_profiles(ctx, tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from qrlabel.ui.pages.search_print import SearchPrintPage

    page = SearchPrintPage(ctx)
    page.reload()
    assert {page.profile_combo.itemData(i) for i in range(page.profile_combo.count())} == {DEFAULT_PROFILE_ID, JOURNAL_PROFILE_ID}
    apply_install_options(ctx, _options(tmp_path, ["journal"]))
    page.reload()
    assert [page.profile_combo.itemData(i) for i in range(page.profile_combo.count())] == [JOURNAL_PROFILE_ID]
