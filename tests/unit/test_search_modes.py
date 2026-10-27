"""Phase 7: per-field search mode and 'search value required'."""
import copy
from datetime import date

import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.domain.models import DataProfile
from qrlabel.infrastructure.ax.mock_source import MOCK_COMPANY, MockDataSource
from qrlabel.services.profile_rules import validate_profile
from qrlabel.services.query_builder import build_select, has_criteria, parse_text_filter

APPROVED = ["AssetTable", "AssetBook"]


def _mode(profile, column, mode):
    profile.get_field(column).search_mode = mode
    return profile


def test_default_mode_is_contains(profile):
    assert all(f.search_mode == "contains" for f in profile.fields)
    old = profile.to_dict()
    for f in old["fields"]:
        f.pop("search_mode")
    old.pop("require_criteria")
    loaded = DataProfile.from_dict(old)  # profiles saved before Phase 7 still load
    assert loaded.get_field("ASSETID").search_mode == "contains" and loaded.require_criteria is False


@pytest.mark.parametrize("mode, where, param", [
    ("contains", r"a.[ASSETID] LIKE ? ESCAPE '\'", r"%FA\_1%"),
    ("starts", r"a.[ASSETID] LIKE ? ESCAPE '\'", r"FA\_1%"),
    ("exact", "(a.[ASSETID] IN (?))", "FA_1"),
])
def test_single_value_sql(profile, mode, where, param):
    sql, params = build_select(_mode(profile, "ASSETID", mode), {"ASSETID": "FA_1"}, "db1", approved_sources=APPROVED)
    assert where in sql and params == ["db1", param]


@pytest.mark.parametrize("mode", ["contains", "starts", "exact"])
def test_lists_and_ranges_are_exact_in_every_mode(profile, mode):
    sql, params = build_select(_mode(profile, "ASSETID", mode), {"ASSETID": "A, B..C"}, "db1", approved_sources=APPROVED)
    assert "LIKE" not in sql and params == ["db1", "A", "B", "C"]


def test_filter_matches_like_sql():
    assert parse_text_filter("fa-1", mode="starts").matches("FA-10")
    assert not parse_text_filter("fa-1", mode="starts").matches("XFA-1")
    assert parse_text_filter("fa-1", mode="exact").matches("FA-1")
    assert not parse_text_filter("fa-1", mode="exact").matches("FA-10")
    with pytest.raises(ValidationError):
        parse_text_filter("x", mode="fuzzy")


def test_sample_source_uses_the_mode(profile):
    src = MockDataSource(APPROVED)
    starts = _mode(copy.deepcopy(profile), "ASSETID", "starts")
    exact = _mode(copy.deepcopy(profile), "ASSETID", "exact")
    assert len(src.search(profile, {"ASSETID": "FA-0000"}, MOCK_COMPANY)) == 9  # sample ids: SAMPLE-FA-00001...
    assert src.search(starts, {"ASSETID": "FA-0000"}, MOCK_COMPANY) == []
    assert len(src.search(starts, {"ASSETID": "sample-fa-0000"}, MOCK_COMPANY)) == 9
    assert [r["ASSETID"] for r in src.search(exact, {"ASSETID": "sample-fa-00001"}, MOCK_COMPANY)] == ["SAMPLE-FA-00001"]
    assert src.search(exact, {"ASSETID": "SAMPLE-FA-0000"}, MOCK_COMPANY) == []


def test_required_criteria(profile):
    profile.require_criteria = True
    for criteria, ranges in (({}, None), ({"ASSETID": "  "}, {"CREATEDDATE": (None, None)})):
        assert not has_criteria(criteria, ranges)
        with pytest.raises(ValidationError, match="at least one search value"):
            build_select(profile, criteria, "db1", approved_sources=APPROVED, ranges=ranges)
        with pytest.raises(ValidationError):
            MockDataSource(APPROVED).search(profile, criteria, MOCK_COMPANY, ranges)
    build_select(profile, {"ASSETID": "FA"}, "db1", approved_sources=APPROVED)
    profile.get_field("CREATEDDATE").range_search = True
    build_select(profile, {}, "db1", approved_sources=APPROVED, ranges={"CREATEDDATE": (date(2024, 1, 1), None)})


def test_validation(profile):
    profile.get_field("ASSETID").search_mode = "fuzzy"
    for f in profile.fields:
        if f.column != "ASSETID":
            f.searchable = f.range_search = False
    assert any("unknown search mode" in i for i in validate_profile(profile, None))
    profile.get_field("ASSETID").search_mode = "starts"
    profile.get_field("ASSETID").searchable = False
    profile.require_criteria = True
    assert any("Search value required" in i for i in validate_profile(profile, None))
