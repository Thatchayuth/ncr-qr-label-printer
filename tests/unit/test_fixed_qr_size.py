from qrlabel.domain.layout import validate_template
from qrlabel.rendering.raster import qr_byte_capacity, qr_matrix, qr_version_of, rasterize_element
from qrlabel.rendering.tspl import TsplRenderer

SHORT = "Asset code : FA-IT-5-26-0001\r\nName : Printer Label 1 Set"  # needs a small QR
LONG = "x" * 300  # needs version 11 at ECC L


def test_capacity_table_matches_qr_spec():
    # byte-mode capacities from the QR standard
    assert qr_byte_capacity(9, "L") == 230
    assert qr_byte_capacity(10, "L") == 271
    assert qr_byte_capacity(13, "L") == 425
    assert qr_byte_capacity(13, "M") == 331


def test_auto_grows_fixed_stays():
    assert qr_version_of(qr_matrix(SHORT, "L")) < 13
    assert qr_version_of(qr_matrix(SHORT, "L", 13)) == 13


def test_same_size_for_short_and_long_data(template):
    qr = template.elements[0]
    qr.w_mm = qr.h_mm = 27.5
    qr.x_mm = 5
    qr.qr_version = 13
    a, wa = rasterize_element(qr, template, {}, SHORT, "L")
    b, wb = rasterize_element(qr, template, {}, LONG, "L")
    assert a.image.size == b.image.size and wa == [] and wb == []
    qr.qr_version = 0
    c, _ = rasterize_element(qr, template, {}, SHORT, "L")
    d, _ = rasterize_element(qr, template, {}, LONG, "L")
    assert c.image.size != d.image.size  # auto: sizes differ


def test_too_long_for_fixed_size_warns(template):
    qr = template.elements[0]
    qr.qr_version = 9
    _, warnings = rasterize_element(qr, template, {}, LONG, "L")
    assert any("too long for the fixed QR size" in w for w in warnings)


def test_fixed_size_forces_bitmap(template):
    template.qr_mode = "native"
    template.elements[0].qr_version = 5
    data, _ = TsplRenderer().render_job(template, [({"ASSETID": "A1"}, "A1")], copies=1)
    assert b"QRCODE" not in data


def test_invalid_version_rejected(template):
    template.elements[0].qr_version = 41
    assert any("QR size" in p for p in validate_template(template))
