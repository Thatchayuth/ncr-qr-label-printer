import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.services.query_builder import build_select, escape_like, quote_ident

APPROVED = ["AssetTable", "AssetBook"]


def test_basic_select(profile):
    sql, params = build_select(profile, {"ASSETID": "FA-1"}, "dat", approved_sources=APPROVED)
    assert sql == (
        "SELECT TOP (200) a.[ASSETID] AS [ASSETID], a.[NAME] AS [NAME], a.[TECHINFO1] AS [TECHINFO1], "
        "COALESCE(NULLIF(l1.[PURCHID], ''), a.[TECHINFO2]) AS [PURCHID], l1.[DIMENSION] AS [DIMENSION], "
        "l1.[ACQUISITIONDATE] AS [ACQUISITIONDATE], l1.[ACQUISITIONPRICE] AS [ACQUISITIONPRICE], "
        "a.[CREATEDDATE] AS [CREATEDDATE] "
        "FROM [dbo].[AssetTable] AS a "
        "OUTER APPLY (SELECT TOP 1 x1.[ACQUISITIONDATE], x1.[ACQUISITIONPRICE], x1.[DIMENSION], x1.[PURCHID] "
        "FROM [dbo].[ASSETBOOK] AS x1 WHERE x1.[ASSETID] = a.[ASSETID] AND x1.[DATAAREAID] = a.[DATAAREAID] "
        "ORDER BY x1.[ACQUISITIONPRICE] DESC, x1.[BOOKID] ASC) AS l1 "
        "WHERE a.[DATAAREAID] = ? AND a.[ASSETID] LIKE ? ESCAPE '\\' ORDER BY a.[ASSETID] ASC"
    )
    assert params == ["dat", "%FA-1%"]


def test_search_on_lookup_field_with_fallback(profile):
    sql, params = build_select(profile, {"PURCHID": "140520"}, "db1", approved_sources=APPROVED)
    assert "COALESCE(NULLIF(l1.[PURCHID], ''), a.[TECHINFO2]) LIKE ? ESCAPE '\\'" in sql
    assert params == ["db1", "%140520%"]


def test_lookup_table_must_be_approved(profile):
    with pytest.raises(ValidationError):
        build_select(profile, {}, "db1", approved_sources=["AssetTable"])


def test_lookup_columns_checked_against_database(profile):
    allowed = {"AssetTable": ["ASSETID", "NAME", "TECHINFO1", "TECHINFO2", "CREATEDDATE", "DATAAREAID"],
               "AssetBook": ["ASSETID", "DATAAREAID", "BOOKID", "PURCHID", "DIMENSION", "ACQUISITIONDATE"]}
    with pytest.raises(ValidationError):  # ACQUISITIONPRICE missing in the "database"
        build_select(profile, {}, "db1", approved_sources=APPROVED, allowed_columns=allowed)
    allowed["AssetBook"].append("ACQUISITIONPRICE")
    build_select(profile, {}, "db1", approved_sources=APPROVED, allowed_columns=allowed)


def test_bad_fallback_and_sort_rejected(profile):
    profile.fields[3].fallback = "a.b.c"
    with pytest.raises(ValidationError):
        build_select(profile, {}, "db1", approved_sources=APPROVED)
    profile.fields[3].fallback = ""
    profile.lookups[0].order_by = ["BOOKID; DROP"]
    with pytest.raises(ValidationError):
        build_select(profile, {}, "db1", approved_sources=APPROVED)


def test_user_input_never_in_sql(profile):
    evil = "x' OR '1'='1"  # single value -> LIKE parameter
    sql, params = build_select(profile, {"ASSETID": evil}, "dat", approved_sources=APPROVED)
    assert "'1'" not in sql
    assert params[1] == f"%{evil}%"
    evil = "x'; DROP TABLE AssetTable; --"  # ';' splits into a list -> IN parameters
    sql, params = build_select(profile, {"ASSETID": evil}, "dat", approved_sources=APPROVED)
    assert "DROP" not in sql
    assert params[1:] == ["x'", "DROP TABLE AssetTable", "--"]


def test_like_wildcards_escaped():
    assert escape_like("50%_[a]\\") == "50\\%\\_\\[a]\\\\"


def test_empty_criteria_returns_top_n(profile):
    sql, params = build_select(profile, {"ASSETID": "  "}, "dat", approved_sources=APPROVED)
    assert "LIKE" not in sql and params == ["dat"]


def test_company_required(profile):
    with pytest.raises(ValidationError):
        build_select(profile, {}, "", approved_sources=APPROVED)


def test_unapproved_source(profile):
    profile.source = "SalesTable"
    with pytest.raises(ValidationError):
        build_select(profile, {}, "dat", approved_sources=APPROVED)


@pytest.mark.parametrize("bad", ["ASSETID]; DROP", "a b", "1abc", "", "x" * 129, "AS-SET"])
def test_bad_identifiers(bad):
    with pytest.raises(ValidationError):
        quote_ident(bad)


def test_unknown_column_rejected_when_schema_known(profile):
    with pytest.raises(ValidationError):
        build_select(profile, {}, "dat", approved_sources=APPROVED, allowed_columns=["NAME", "DATAAREAID"])


def test_non_searchable_field_rejected(profile):
    profile.fields[0].searchable = False
    with pytest.raises(ValidationError):
        build_select(profile, {"ASSETID": "x"}, "dat", approved_sources=APPROVED)


def test_row_limit_bounds(profile):
    profile.row_limit = 100000
    with pytest.raises(ValidationError):
        build_select(profile, {}, "dat", approved_sources=APPROVED)


def test_date_range_inclusive(profile):
    from datetime import date, datetime

    sql, params = build_select(profile, {}, "db1", approved_sources=APPROVED,
                               ranges={"CREATEDDATE": (date(2026, 1, 1), date(2026, 1, 31))})
    assert "a.[CREATEDDATE] >= ? AND a.[CREATEDDATE] < ?" in sql
    assert params == ["db1", datetime(2026, 1, 1), datetime(2026, 2, 1)]


def test_date_range_open_ended_and_empty(profile):
    from datetime import date

    sql, params = build_select(profile, {}, "db1", approved_sources=APPROVED,
                               ranges={"CREATEDDATE": (None, date(2026, 1, 31))})
    assert ">=" not in sql and "[CREATEDDATE] < ?" in sql
    sql, _ = build_select(profile, {}, "db1", approved_sources=APPROVED, ranges={"CREATEDDATE": (None, None)})
    assert "CREATEDDATE] <" not in sql


def test_date_range_validation(profile):
    from datetime import date

    with pytest.raises(ValidationError):
        build_select(profile, {}, "db1", approved_sources=APPROVED,
                     ranges={"CREATEDDATE": (date(2026, 2, 1), date(2026, 1, 1))})
    with pytest.raises(ValidationError):  # not a range field
        build_select(profile, {}, "db1", approved_sources=APPROVED, ranges={"NAME": (date(2026, 1, 1), None)})


def test_no_company_filter_when_policy_disabled(profile):
    profile.dataarea_column = ""
    sql, params = build_select(profile, {}, "", approved_sources=APPROVED)
    assert "a.[DATAAREAID] = ?" not in sql and params == []


# ------------------------------------------------------------ list / range


from qrlabel.services.query_builder import parse_text_filter  # noqa: E402


def test_parse_single_is_contains():
    assert parse_text_filter(" FA-IT ").contains == "FA-IT"


def test_parse_range_and_list():
    f = parse_text_filter("A-0001..A-0003, A-0010; A-0010\r\nA-0020")
    assert f.contains is None
    assert f.ranges == (("A-0001", "A-0003"),)
    assert f.exact == ("A-0010", "A-0020")  # duplicates removed, order kept


def test_parse_range_variants():
    assert parse_text_filter("B...A").ranges == (("A", "B"),)  # three dots, reversed bounds
    assert parse_text_filter("A .. B").ranges == (("A", "B"),)
    with pytest.raises(ValidationError):
        parse_text_filter("A..")
    with pytest.raises(ValidationError):
        parse_text_filter("A..B..C")


def test_parse_limits():
    with pytest.raises(ValidationError):
        parse_text_filter(",".join(str(i) for i in range(201)))
    with pytest.raises(ValidationError):
        parse_text_filter("x" * 101 + ",y")


def test_matches_case_insensitive():
    f = parse_text_filter("fa-0001..fa-0003, FA-0010")
    assert f.matches("FA-0002") and f.matches("fa-0010")
    assert not f.matches("FA-0004") and not f.matches(None)


def test_sql_for_range_and_list(profile):
    sql, params = build_select(profile, {"ASSETID": "A1..A3, B7, B9"}, "db1", approved_sources=APPROVED)
    assert "(a.[ASSETID] IN (?, ?) OR (a.[ASSETID] >= ? AND a.[ASSETID] <= ?))" in sql
    assert params == ["db1", "B7", "B9", "A1", "A3"]
    assert "LIKE" not in sql


def test_sql_list_values_are_parameters(profile):
    evil = "x') OR 1=1 --, y"
    sql, params = build_select(profile, {"ASSETID": evil}, "db1", approved_sources=APPROVED)
    assert "OR 1=1" not in sql and "x') OR 1=1 --" in params
