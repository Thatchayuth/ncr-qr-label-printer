from qrlabel.app.defaults import bundled_templates
from qrlabel.domain.layout import validate_template

BUNDLED_ID = "985aa6dd0dda40c68aaff4fcf1b27d85"  # "New label" (v14 on the design PC)


def test_bundled_template_is_valid():
    templates, default = bundled_templates()
    assert default == BUNDLED_ID
    t = next(t for t in templates if t.id == BUNDLED_ID)
    assert t.name == "New label" and (t.width_mm, t.height_mm) == (38.1, 38.1)
    assert {e.kind for e in t.elements} == {"qr", "text", "image"}
    assert validate_template(t) == []


def test_new_install_uses_bundled_template(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext

    ctx = AppContext()
    assert [t.id for t in ctx.templates.list_latest()] == [BUNDLED_ID]
    assert ctx.profiles.get("asset").template_id == BUNDLED_ID
    # it can print straight away
    from qrlabel.infrastructure.printing.adapters import MockPrinterAdapter

    jobs = ctx.print_service.print_records(
        records=[{"ASSETID": "FA-IT-5-14-0020"}], profile=ctx.profiles.get("asset"),
        template=ctx.templates.get(BUNDLED_ID), adapter=MockPrinterAdapter(tmp_path / "out"), copies=1,
        correlation_id="seed-test",
    )
    assert jobs[0].template_id == BUNDLED_ID and jobs[0].status.value == "SpoolerAccepted"


def test_existing_install_keeps_its_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext
    from qrlabel.app.defaults import default_asset_template

    ctx = AppContext()
    own = default_asset_template()
    own.id, own.name = "my-own", "Own design"
    ctx.templates.save(own)
    again = AppContext()  # second start: nothing re-seeded or overwritten
    assert sorted(t.id for t in again.templates.list_latest()) == sorted([BUNDLED_ID, "my-own"])
    assert again.templates.get(BUNDLED_ID).version == 1


def test_new_install_binds_bundled_label(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext

    p = AppContext().profiles.get("asset")
    assert p.template_ids == [BUNDLED_ID] and p.template_id == BUNDLED_ID
