import copy

import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.services.profile_io import duplicate_profile, export_profile, import_profile
from qrlabel.services.profile_rules import new_field, pretty_label, suggest_type, validate_profile

COLUMNS = {
    "ASSETTABLE": {"ASSETID": "nvarchar", "NAME": "nvarchar", "TECHINFO1": "nvarchar", "TECHINFO2": "nvarchar",
                   "CREATEDDATE": "datetime", "DATAAREAID": "nvarchar", "NOTES": "ntext"},
    "ASSETBOOK": {"ASSETID": "nvarchar", "DATAAREAID": "nvarchar", "BOOKID": "nvarchar", "PURCHID": "nvarchar",
                  "DIMENSION": "nvarchar", "ACQUISITIONDATE": "datetime", "ACQUISITIONPRICE": "numeric"},
}


def test_default_profile_is_valid(profile):
    assert validate_profile(profile, COLUMNS, {"asset-qr-sample-40x30"}) == []


def test_missing_column_reported(profile):
    cols = copy.deepcopy(COLUMNS)
    del cols["ASSETBOOK"]["DIMENSION"]
    assert any("DIMENSION does not exist" in i for i in validate_profile(profile, cols))


def test_ntext_cannot_be_searched_or_sorted(profile):
    f = new_field("NOTES", "ntext", "", {f.column for f in profile.fields})
    assert f.searchable is False  # suggested off
    f.searchable = True
    profile.fields.append(f)
    profile.order_by = ["NOTES"]
    issues = validate_profile(profile, COLUMNS)
    assert any("cannot be searched" in i for i in issues) and any("Cannot sort by NOTES" in i for i in issues)


def test_qr_fields_must_exist(profile):
    profile.fields = [f for f in profile.fields if f.column != "DIMENSION"]
    assert any("QR uses fields" in i for i in validate_profile(profile, COLUMNS))


def test_lookup_rules(profile):
    profile.lookups[0].join = []
    assert any("choose the columns that link" in i for i in validate_profile(profile, COLUMNS))
    profile.lookups[0].join = [["NOPE", "ASSETID"]]
    assert any("NOPE does not exist" in i for i in validate_profile(profile, COLUMNS))
    profile.lookups[0].join = [["ASSETID", "ASSETID"]]
    profile.lookups[0].order_by = ["BOOKID; DROP"]
    assert any("not valid" in i for i in validate_profile(profile, COLUMNS))


def test_view_as_main_source(profile):
    """A DBA view with everything joined works like a table (option B)."""
    profile.source, profile.lookups = "V_NCR_ASSETLABEL", []
    profile.fields = [new_field(c, t, "", set()) for c, t in [("ASSETID", "nvarchar"), ("PO", "nvarchar")]]
    profile.qr.fields = ["ASSETID"]
    profile.order_by = ["ASSETID"]
    cols = {"V_NCR_ASSETLABEL": {"ASSETID": "nvarchar", "PO": "nvarchar", "DATAAREAID": "nvarchar"}}
    assert validate_profile(profile, cols) == []


def test_new_field_suggestions():
    f = new_field("ACQUISITIONDATE", "datetime", "AssetBook", set())
    assert (f.column, f.table, f.data_type, f.fmt, f.searchable) == ("ACQUISITIONDATE", "ASSETBOOK", "date", "%d/%m/%Y", False)
    g = new_field("NAME", "nvarchar", "AssetBook", {"NAME"})
    assert (g.column, g.source_column) == ("ASSETBOOK_NAME", "NAME")
    assert suggest_type("money") == "decimal" and suggest_type("bigint") == "int"
    assert pretty_label("PURCHID") == "Purchid" and pretty_label("DIMENSION2_") == "Dimension2"


def test_profile_export_import(profile, tmp_path):
    p = tmp_path / "p.json"
    export_profile(profile, p)
    again = import_profile(p)
    assert again.id != profile.id
    again.id = profile.id
    assert again == profile


def test_profile_import_rejects_bad_files(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"format": "something-else"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        import_profile(p)


def test_duplicate_profile(profile):
    d = duplicate_profile(profile)
    assert d.id != profile.id and d.name.startswith("Copy of")
    d.fields.pop()
    assert len(profile.fields) == len(d.fields) + 1
