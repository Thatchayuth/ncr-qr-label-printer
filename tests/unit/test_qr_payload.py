from datetime import datetime
from decimal import Decimal

import pytest

from qrlabel.domain.errors import PayloadError
from qrlabel.domain.models import FieldDef, QrConfig
from qrlabel.services.formatting import build_label_values, format_value
from qrlabel.services.qr_payload import QrPayloadBuilder

B = QrPayloadBuilder()


def test_plain_asset_id(profile):
    p = B.build({"ASSETID": "FA-000123"}, profile)
    assert p.text == "FA-000123"
    assert p.byte_length == 9


def test_column_lookup_is_case_insensitive(profile):
    assert B.build({"ASSETID": "x1"}, profile).text == "x1"


def test_empty_asset_id_is_rejected(profile):
    with pytest.raises(PayloadError):
        B.build({"ASSETID": "   "}, profile)
    with pytest.raises(PayloadError):
        B.build({"ASSETID": None}, profile)


def test_control_characters_rejected(profile):
    with pytest.raises(PayloadError):
        B.build({"ASSETID": "A\r\nCLS"}, profile)


def test_thai_text_byte_length(profile):
    p = B.build({"ASSETID": "ทรัพย์1"}, profile)
    assert p.byte_length == len("ทรัพย์1".encode("utf-8"))


def test_max_bytes(profile):
    profile.qr.max_bytes = 5
    with pytest.raises(PayloadError):
        B.build({"ASSETID": "123456"}, profile)


def _multi(profile, fmt):
    profile.qr = QrConfig(format=fmt, fields=["ASSETID", "NAME"], delimiter="|", prefix="NCR:")
    return profile


def test_delimited_is_ordered_and_deterministic(profile):
    _multi(profile, "delimited")
    p = B.build({"NAME": "Desk", "ASSETID": "A1"}, profile)
    assert p.text == "NCR:A1|Desk"


def test_delimited_rejects_value_containing_delimiter(profile):
    _multi(profile, "delimited")
    with pytest.raises(PayloadError):
        B.build({"ASSETID": "A1", "NAME": "a|b"}, profile)


def test_json_payload(profile):
    _multi(profile, "json")
    p = B.build({"ASSETID": "A1", "NAME": "โต๊ะ"}, profile)
    assert p.text == 'NCR:{"Fixed asset number":"A1","Name":"โต๊ะ"}'


def test_plain_with_two_fields_is_an_error(profile):
    _multi(profile, "plain")
    with pytest.raises(PayloadError):
        B.build({"ASSETID": "A1", "NAME": "x"}, profile)


def test_format_values():
    assert format_value(Decimal("12.500")) == "12.5"
    assert format_value(Decimal("12.5"), FieldDef("X", fmt="2")) == "12.50"
    assert format_value(datetime(1900, 1, 1)) == ""  # AX empty date
    assert format_value(datetime(2026, 3, 4), FieldDef("D", fmt="%d/%m/%Y")) == "04/03/2026"
    assert format_value(None, FieldDef("X", default="-")) == "-"


def test_build_label_values_uppercases(profile):
    assert build_label_values(profile, {"assetid": " A1 "})["ASSETID"] == "A1"
