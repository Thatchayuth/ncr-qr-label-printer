"""Phase 8: fixed filters, related-table fixed values / virtual company, abs format, journal profile."""
from decimal import Decimal

import pytest

from qrlabel.app.defaults import JOURNAL_PROFILE_ID, JOURNAL_SOURCES, default_journal_profile
from qrlabel.domain.errors import ValidationError
from qrlabel.domain.models import DataProfile, FieldDef
from qrlabel.infrastructure.ax.mock_source import MOCK_COMPANY, MockDataSource
from qrlabel.services.formatting import format_value
from qrlabel.services.profile_rules import validate_profile
from qrlabel.services.query_builder import build_select, format_pairs, parse_pairs, uses_virtual_company

APPROVED = ["AssetTable", "AssetBook"] + JOURNAL_SOURCES


def test_journal_profile_sql_and_parameter_order():
    p = default_journal_profile()
    sql, params = build_select(p, {"ITEMID": "MCAB"}, "db1", approved_sources=APPROVED, virtual_company="vir")
    assert "FROM [dbo].[INVENTJOURNALTRANS] AS a" in sql
    assert "x1.[INVENTDIMID] = a.[INVENTDIMID] AND x1.[DATAAREAID] = ?" in sql
    assert "x3.[ITEMID] = a.[ITEMID] AND x3.[MODULETYPE] = ? AND x3.[DATAAREAID] = ?" in sql
    assert "WHERE a.[DATAAREAID] = ? AND a.[JOURNALTYPE] = ? AND a.[ITEMID] LIKE ?" in sql
    assert "VIRTUALDATAAREALIST" not in sql  # resolved before the query (a subquery made it slow)
    # placeholders in text order: InventDim, InventTable, InventTableModule, then WHERE
    assert params == ["vir", "vir", "0", "vir", "db1", "2", "MCAB%"]
    assert sql.endswith("ORDER BY a.[TRANSDATE] DESC, a.[JOURNALID] DESC, a.[LINENUM] ASC")


def test_virtual_company_falls_back_to_company():
    _, params = build_select(default_journal_profile(), {"VOUCHER": "1"}, "db9", approved_sources=APPROVED)
    assert params[:4] == ["db9", "db9", "0", "db9"]


def test_journal_profile_settings():
    p = default_journal_profile(["tpl"])
    assert uses_virtual_company(p) and p.require_criteria
    assert [f.column for f in p.searchable_fields] == ["JOURNALID", "VOUCHER", "ITEMID"]  # Journal first (scanned)
    assert p.fields[0].barcode and p.fields[0].replace == "+>_"
    assert all(f.search_mode == "starts" for f in p.searchable_fields)
    assert p.template_ids == ["tpl"] and p.template_id == "tpl"
    assert validate_profile(p, None) == []
    assert DataProfile.from_dict(p.to_dict()) == p
    with pytest.raises(ValidationError, match="at least one search value"):
        build_select(p, {}, "db1", approved_sources=APPROVED)


def test_asset_profile_unchanged(profile):
    assert not uses_virtual_company(profile) and profile.filters == []
    sql, params = build_select(profile, {"ASSETID": "FA"}, "db1", approved_sources=APPROVED)
    assert params == ["db1", "%FA%"]


def test_fixed_values_are_parameters_and_checked():
    p = default_journal_profile()
    p.filters = [["JOURNALTYPE", "2'; DROP TABLE X --"]]
    sql, params = build_select(p, {"ITEMID": "A"}, "db1", approved_sources=APPROVED)
    assert "DROP" not in sql and "2'; DROP TABLE X --" in params
    for bad in ([["JOURNAL TYPE", "2"]], [["JOURNALTYPE", ""]], [["JOURNALTYPE"]], [["DATAAREAID", "@VIRTUAL"]]):
        p.filters = bad
        with pytest.raises(ValidationError):
            build_select(p, {"ITEMID": "A"}, "db1", approved_sources=APPROVED)
        assert validate_profile(p, None)


def test_virtual_needs_company_column():
    p = default_journal_profile()
    p.dataarea_column = ""
    assert any("@VIRTUAL needs a company column" in i for i in validate_profile(p, None))
    with pytest.raises(ValidationError):
        build_select(p, {"ITEMID": "A"}, "", approved_sources=APPROVED)


def test_fixed_value_columns_checked_against_database():
    p = default_journal_profile()
    cols = {"INVENTJOURNALTRANS": {c: "nvarchar" for c in
                                   ["VOUCHER", "ITEMID", "QTY", "NOTES", "JOURNALID", "LINENUM", "TRANSDATE", "INVENTDIMID", "DATAAREAID"]},
            "INVENTDIM": {c: "nvarchar" for c in ["INVENTDIMID", "DATAAREAID", "INVENTSIZEID", "INVENTBATCHID", "INVENTLOCATIONID",
                                                  "WMSLOCATIONID", "INVENTSERIALID", "CONFIGID", "INVENTCOLORID"]},
            "INVENTTABLE": {"ITEMID": "nvarchar", "ITEMNAME": "nvarchar", "DATAAREAID": "nvarchar"},
            "INVENTTABLEMODULE": {"ITEMID": "nvarchar", "UNITID": "nvarchar", "DATAAREAID": "nvarchar"}}
    issues = validate_profile(p, cols)
    assert "Fixed filter: column JOURNALTYPE does not exist in INVENTJOURNALTRANS." in issues
    assert "Related table INVENTTABLEMODULE: fixed-value column MODULETYPE does not exist." in issues
    cols["INVENTJOURNALTRANS"]["JOURNALTYPE"] = "int"
    cols["INVENTTABLEMODULE"]["MODULETYPE"] = "int"
    assert validate_profile(p, cols) == []


def test_parse_and_format_pairs():
    pairs = parse_pairs(" moduletype = 0 , DATAAREAID=@virtual ")
    assert pairs == [["MODULETYPE", "0"], ["DATAAREAID", "@VIRTUAL"]]
    assert format_pairs(pairs) == "MODULETYPE=0, DATAAREAID=@VIRTUAL"
    assert parse_pairs("") == []
    for bad in ("MODULETYPE", "BAD COL=1", "X="):
        with pytest.raises(ValidationError):
            parse_pairs(bad)


@pytest.mark.parametrize("value, fmt, text", [
    (Decimal("-30.000000"), "abs", "30"),
    (Decimal("-5.990000"), "abs", "5.99"),
    (Decimal("-1234.5"), "abs,2", "1,234.50"),
    (Decimal("-1234.5"), "abs 2", "1234.50"),
    (Decimal("-2"), "", "-2"),
])
def test_abs_format(value, fmt, text):
    assert format_value(value, FieldDef(column="QTY", data_type="decimal", fmt=fmt)) == text


def test_sample_source_applies_fixed_filter(profile):
    src = MockDataSource(APPROVED)
    every = src.search(profile, {}, MOCK_COMPANY)
    profile.filters = [["ASSETID", "sample-fa-00002"]]
    assert [r["ASSETID"] for r in src.search(profile, {}, MOCK_COMPANY)] == ["SAMPLE-FA-00002"]
    assert len(every) > 1


def test_install_journal_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext
    from qrlabel.app.modules import install_journal_profile

    ctx = AppContext()  # both parts are on by default: the journal profile is created on start
    p = ctx.profiles.get(JOURNAL_PROFILE_ID)
    assert p.template_ids == ["25c45638326c4a489b36112d4c1e8c09"]  # bundled STOCK label
    again = AppContext()
    assert {s.upper() for s in JOURNAL_SOURCES} <= {s.upper() for s in again.config["approved_sources"]}
    assert install_journal_profile(again) is False  # never overwrites an existing (maybe edited) profile
    assert again.profiles.get(JOURNAL_PROFILE_ID).version == 1
