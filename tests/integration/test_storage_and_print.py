import json

import pytest

from qrlabel.domain.errors import DuplicateJobError, PayloadError, ValidationError
from qrlabel.domain.models import PrintStatus
from qrlabel.infrastructure.ax.mock_source import MockDataSource
from qrlabel.infrastructure.config import DEFAULT_CONFIG, ConfigurationService
from qrlabel.infrastructure.printing.adapters import MockPrinterAdapter, WindowsSharedPrinterAdapter
from qrlabel.infrastructure.storage.repositories import (
    SqlitePrintJobRepository,
    SqliteProfileRepository,
    SqliteTemplateRepository,
)
from qrlabel.services.print_service import PrintService


# ----------------------------------------------------------------- repositories

def test_profile_versioning(db, profile):
    repo = SqliteProfileRepository(db)
    assert repo.save(profile).version == 1
    profile.row_limit = 50
    assert repo.save(profile).version == 2
    assert repo.get(profile.id).row_limit == 50
    assert repo.get(profile.id, 1).row_limit == 200
    assert [p.version for p in repo.list_latest()] == [2]


def test_template_roundtrip(db, template):
    repo = SqliteTemplateRepository(db)
    repo.save(template)
    assert repo.get(template.id) == template


# --------------------------------------------------------------------- printing

def _service(db):
    return PrintService(SqlitePrintJobRepository(db), "test", username="tester")


def test_print_records_to_mock(db, profile, template, tmp_path):
    svc = _service(db)
    adapter = MockPrinterAdapter(tmp_path / "out")
    jobs = svc.print_records(
        records=[{"ASSETID": "A1"}, {"ASSETID": "A2"}], profile=profile, template=template,
        adapter=adapter, copies=3, correlation_id="c1",
    )
    assert [j.status for j in jobs] == [PrintStatus.SPOOLER_ACCEPTED] * 2
    assert len(list((tmp_path / "out").glob("*.prn"))) == 2
    history = svc.jobs.list_recent()
    assert {j.document_ref for j in history} == {"A1", "A2"}
    assert all(j.copies == 3 and j.profile_version == profile.version and j.username == "tester" for j in history)
    statuses = [s for _, s, _ in svc.jobs.events(jobs[0].id)]
    assert statuses == ["Pending", "Submitting", "SpoolerAccepted"]


def test_duplicate_correlation_refused(db, profile, template, tmp_path):
    svc = _service(db)
    kw = dict(records=[{"ASSETID": "A1"}], profile=profile, template=template,
              adapter=MockPrinterAdapter(tmp_path), copies=1, correlation_id="same")
    svc.print_records(**kw)
    with pytest.raises(DuplicateJobError):
        svc.print_records(**kw)


def test_invalid_record_blocks_whole_batch(db, profile, template, tmp_path):
    svc = _service(db)
    adapter = MockPrinterAdapter(tmp_path)
    with pytest.raises(PayloadError):
        svc.print_records(records=[{"ASSETID": "A1"}, {"ASSETID": ""}], profile=profile, template=template,
                          adapter=adapter, copies=1, correlation_id="c2")
    assert adapter.sent == [] and svc.jobs.list_recent() == []


@pytest.mark.parametrize("failure", [PrintStatus.FAILED, PrintStatus.UNKNOWN_DELIVERY])
def test_stop_after_failure(db, profile, template, tmp_path, failure):
    svc = _service(db)
    jobs = svc.print_records(
        records=[{"ASSETID": "A1"}, {"ASSETID": "A2"}, {"ASSETID": "A3"}], profile=profile, template=template,
        adapter=MockPrinterAdapter(tmp_path, fail_with=failure), copies=1, correlation_id="c3",
    )
    assert [j.status for j in jobs] == [failure, PrintStatus.CANCELLED, PrintStatus.CANCELLED]
    assert svc.jobs.get(jobs[0].id).error_code == "MOCK"


def test_cancel_pending(db, profile, template, tmp_path):
    svc = _service(db)
    calls = iter([False, True, True])
    jobs = svc.print_records(
        records=[{"ASSETID": "A1"}, {"ASSETID": "A2"}, {"ASSETID": "A3"}], profile=profile, template=template,
        adapter=MockPrinterAdapter(tmp_path), copies=1, correlation_id="c4", should_cancel=lambda: next(calls),
    )
    assert [j.status for j in jobs] == [PrintStatus.SPOOLER_ACCEPTED, PrintStatus.CANCELLED, PrintStatus.CANCELLED]


def test_copies_limits(db, profile, template, tmp_path):
    with pytest.raises(ValidationError):
        _service(db).print_records(records=[{"ASSETID": "A"}], profile=profile, template=template,
                                   adapter=MockPrinterAdapter(tmp_path), copies=1000, correlation_id="c5")


def test_shared_path_validation():
    WindowsSharedPrinterAdapter(r"\\PC-01\TE200")
    for bad in ["TE200", r"\\PC-01", r"\\PC-01\a\b", ""]:
        with pytest.raises(Exception):
            WindowsSharedPrinterAdapter(bad)


# ---------------------------------------------------------------- mock source

def test_mock_source_search(profile):
    src = MockDataSource(["AssetTable", "AssetBook"])
    rows = src.search(profile, {"ASSETID": "0002"}, "smp")
    assert [r["ASSETID"] for r in rows] == ["SAMPLE-FA-00002"] + [f"SAMPLE-FA-0002{i}" for i in range(10)]
    assert set(rows[0]) == {"ASSETID", "NAME", "TECHINFO1", "PURCHID", "DIMENSION", "ACQUISITIONDATE",
                            "ACQUISITIONPRICE", "CREATEDDATE"}
    assert src.search(profile, {}, "other") == []


def test_mock_po_fallback_to_techinfo2(profile):
    src = MockDataSource(["AssetTable", "AssetBook"])
    rows = {r["ASSETID"]: r for r in src.search(profile, {}, "smp")}
    assert rows["SAMPLE-FA-00001"]["PURCHID"] == "100001_018"  # from AssetBook
    assert rows["SAMPLE-FA-00020"]["PURCHID"] == "900020_018"  # AssetBook empty -> TechInfo2
    assert [r["ASSETID"] for r in src.search(profile, {"PURCHID": "900020"}, "smp")] == ["SAMPLE-FA-00020"]


def test_config_v1_migrates_to_approve_assetbook(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"config_version": 1, "approved_sources": ["AssetTable"]}', encoding="utf-8")
    cfg = _fake_cs(p).load()
    assert cfg["config_version"] == 2 and cfg["approved_sources"] == ["AssetTable", "AssetBook"]
    assert (tmp_path / "config.json.bak-v1").exists()


def test_price_format_with_thousands():
    from decimal import Decimal

    from qrlabel.domain.models import FieldDef
    from qrlabel.services.formatting import format_value

    assert format_value(Decimal("347285.320000000000"), FieldDef("P", fmt=",2")) == "347,285.32"
    assert format_value(Decimal("0E-12"), FieldDef("P", fmt=",2")) == "0.00"


# ----------------------------------------------------------------------- config

def _fake_cs(path):
    return ConfigurationService(path, protect=lambda s: "ENC:" + s[::-1], unprotect=lambda s: s[4:][::-1] if s else "")


def test_config_defaults_and_atomic_save(tmp_path):
    cs = _fake_cs(tmp_path / "config.json")
    cfg = cs.load()
    assert cfg == DEFAULT_CONFIG and cfg is not DEFAULT_CONFIG
    cfg["database"]["server"] = "AXSQL01"
    cs.set_password(cfg, "S3cret!")
    cs.save(cfg)
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert "S3cret!" not in text
    loaded = cs.load()
    assert loaded["database"]["server"] == "AXSQL01"
    assert cs.get_password(loaded) == "S3cret!"
    assert not list(tmp_path.glob("*.tmp"))


def test_config_invalid_is_backed_up(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"config_version": 1, "printer": {"adapter": "laser"}}', encoding="utf-8")
    cfg = _fake_cs(p).load()
    assert cfg["printer"]["adapter"] == "mock"
    assert list(tmp_path.glob("config.json.invalid-*"))


def test_config_save_rejects_invalid(tmp_path):
    cs = _fake_cs(tmp_path / "c.json")
    cfg = cs.load()
    cfg["approved_sources"] = ["Asset; DROP"]
    with pytest.raises(ValidationError):
        cs.save(cfg)


def test_config_export_strips_secret(tmp_path):
    cs = _fake_cs(tmp_path / "c.json")
    cfg = cs.load()
    cs.set_password(cfg, "pw")
    cs.export_config(cfg, tmp_path / "export.json")
    assert json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))["database"]["password_dpapi"] == ""


def test_real_dpapi_roundtrip():
    from qrlabel.infrastructure.security import dpapi

    token = dpapi.protect("รหัส-123")
    assert "รหัส" not in token
    assert dpapi.unprotect(token) == "รหัส-123"


def test_mock_source_date_range(profile):
    from datetime import date

    src = MockDataSource(["AssetTable", "AssetBook"])
    rows = src.search(profile, {}, "smp", {"CREATEDDATE": (date(2026, 1, 4), date(2026, 1, 10))})
    assert [r["ASSETID"] for r in rows] == ["SAMPLE-FA-00001", "SAMPLE-FA-00002", "SAMPLE-FA-00003"]
