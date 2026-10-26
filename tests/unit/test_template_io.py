import json

import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.services.template_io import (
    FILE_FORMAT,
    duplicate_template,
    export_template,
    import_template,
    snap,
)


def test_export_import_roundtrip(template, tmp_path):
    path = tmp_path / "t.json"
    export_template(template, path)
    again = import_template(path)
    assert again.id != template.id  # never overwrites an existing template
    again.id = template.id
    assert again == template


def test_import_rejects_other_files(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(ValidationError):
        import_template(p)
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValidationError):
        import_template(p)


def test_import_rejects_invalid_layout(template, tmp_path):
    d = template.to_dict()
    d["elements"][0]["x_mm"] = 500
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"format": FILE_FORMAT, "format_version": 1, "template": d}), encoding="utf-8")
    with pytest.raises(ValidationError):
        import_template(p)


def test_import_rejects_wrong_types(template, tmp_path):
    d = template.to_dict()
    d["elements"][0]["w_mm"] = "abc"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"format": FILE_FORMAT, "format_version": 1, "template": d}), encoding="utf-8")
    with pytest.raises(ValidationError):
        import_template(p)


def test_duplicate(template):
    d = duplicate_template(template)
    assert d.id != template.id and d.name.startswith("Copy of")
    d.elements[0].x_mm = 3
    assert template.elements[0].x_mm == 10  # deep copy


@pytest.mark.parametrize("value,step,expected", [(3.26, 0.5, 3.5), (3.24, 0.5, 3.0), (7.3, 1, 7.0), (2.345, 0, 2.35)])
def test_snap(value, step, expected):
    assert snap(value, step) == expected
