import re

import pytest
from PIL import Image

from qrlabel.domain.errors import ValidationError
from qrlabel.domain.layout import mm_to_dots, validate_template
from qrlabel.domain.models import LabelElement, LabelTemplate
from qrlabel.rendering.raster import Placed, render_label_image
from qrlabel.rendering.tspl import TsplRenderer, bitmap_command, is_native_safe

R = TsplRenderer()


def test_mm_to_dots():
    assert mm_to_dots(25.4) == 203
    assert mm_to_dots(40) == 320


def test_header(template):
    head = R.header(template).decode("ascii")
    assert head.splitlines() == [
        "SIZE 40 mm,30 mm", "GAP 2 mm,0 mm", "DIRECTION 1", "REFERENCE 0,0", "DENSITY 8", "SPEED 4",
    ]


def test_bline_and_continuous(template):
    template.media = "bline"
    assert b"BLINE 2 mm,0 mm" in R.header(template)
    template.media = "continuous"
    assert b"GAP 0,0" in R.header(template)


def test_job_structure_bitmap_default(template):
    data, warnings = R.render_job(template, [({"ASSETID": "FA-000123"}, "FA-000123")], copies=2)
    assert warnings == []
    assert data.count(b"CLS\r\n") == 1
    assert data.count(b"BITMAP ") == 2  # QR + text
    assert data.endswith(b"PRINT 1,2\r\n")
    assert b"FA-000123" not in data  # data only travels as pixels in bitmap mode


def test_multiple_labels(template):
    data, _ = R.render_job(template, [({"ASSETID": "A1"}, "A1"), ({"ASSETID": "A2"}, "A2")], copies=1)
    assert data.count(b"CLS\r\n") == 2 and data.count(b"PRINT 1,1") == 2
    assert data.count(b"SIZE ") == 1


def test_native_mode_for_safe_ascii(template):
    template.qr_mode, template.text_mode = "native", "native"
    data, _ = R.render_job(template, [({"ASSETID": "FA-000123"}, "FA-000123")], copies=1)
    text = data.decode("ascii")
    assert re.search(r'QRCODE \d+,\d+,M,\d+,A,0,"FA-000123"', text)
    assert re.search(r'TEXT \d+,\d+,"\d",0,1,1,"FA-000123"', text)


@pytest.mark.parametrize("evil", ['A"\r\nPRINT 1,99', "ทดสอบ", "A\\B", 'x"y'])
def test_unsafe_data_falls_back_to_bitmap(template, evil):
    template.qr_mode, template.text_mode = "native", "native"
    data, warnings = R.render_job(template, [({"ASSETID": evil}, evil)], copies=1)
    assert b"QRCODE" not in data and b"TEXT " not in data
    assert data.count(b"PRINT ") == 1
    assert any("bitmap" in w for w in warnings)


def test_is_native_safe():
    assert is_native_safe("FA-0001/2")
    assert not is_native_safe("")
    assert not is_native_safe('a"b')
    assert not is_native_safe("ก")


def test_bitmap_padding_is_white():
    img = Image.new("1", (10, 2), 0)  # all black, width not multiple of 8
    cmd = bitmap_command(Placed(img, 5, 6))
    head, body = cmd[:-2].split(b",0,", 1)
    assert head == b"BITMAP 5,6,2,2"
    assert body == bytes([0x00, 0x3F, 0x00, 0x3F])  # 0 = black dots, padding bits = 1 (white)


def test_copies_validation(template):
    with pytest.raises(ValidationError):
        R.render_job(template, [({"ASSETID": "A"}, "A")], copies=0)


def test_invalid_template_refused(template):
    template.elements[0].x_mm = 35  # QR now runs off the label
    assert validate_template(template)
    with pytest.raises(ValidationError):
        R.render_job(template, [({"ASSETID": "A"}, "A")], copies=1)


def test_default_template_valid(template):
    assert validate_template(template) == []


def test_real_length_asset_id_auto_fits(template):
    # longest AssetId seen in AX test DB is 17 chars, e.g. MACH_EQUIP0000001
    _, warnings = R.render_job(template, [({"ASSETID": "MACH_EQUIP0000001"}, "MACH_EQUIP0000001")], copies=1)
    assert warnings == []


def test_native_text_steps_down_font(template):
    template.text_mode = "native"
    data, warnings = R.render_job(template, [({"ASSETID": "MACH_EQUIP0000001"}, "x")], copies=1)
    assert b'"3",0,1,1,"MACH_EQUIP0000001"' in data and warnings == []  # 17 x 16 dots fits 296
    template.elements[1].w_mm = 25  # 200 dots: font 3 (272) too wide -> font 2 (204) too -> font 1
    data, _ = R.render_job(template, [({"ASSETID": "MACH_EQUIP0000001"}, "x")], copies=1)
    assert b'"1",0,1,1,"MACH_EQUIP0000001"' in data


def test_text_overflow_warning(template):
    long_id = "VERY-LONG-ASSET-IDENTIFIER-0000000001"
    _, warnings = R.render_job(template, [({"ASSETID": long_id}, long_id)], copies=1)
    assert any("does not fit" in w for w in warnings)


def test_preview_image_size_and_qr_decodes(template):
    img, warnings = render_label_image(template, {"ASSETID": "FA-000123"}, "FA-000123")
    assert img.size == (320, 240) and warnings == []
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    big = img.resize((img.width * 3, img.height * 3), Image.Resampling.NEAREST)
    padded = Image.new("L", (big.width + 80, big.height + 80), 255)
    padded.paste(big, (40, 40))
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(np.array(padded))
    assert text == "FA-000123"


def test_shapes_native(template):
    template.elements.append(LabelElement(kind="rect", x_mm=1, y_mm=1, w_mm=38, h_mm=28, thickness_mm=0.25))
    template.elements.append(LabelElement(kind="line", x_mm=1, y_mm=22.5, w_mm=38, h_mm=0, thickness_mm=0.25))
    data, _ = R.render_job(template, [({"ASSETID": "A"}, "A")], copies=1)
    assert b"BOX 8,8,312,232,2" in data
    assert b"BAR 8,180,304,2" in data


def test_template_roundtrip(template):
    again = LabelTemplate.from_dict(template.to_dict())
    assert again == template


def test_small_qr_modules_warn(template):
    from qrlabel.app.defaults import default_asset_qr  # noqa: F401  (long multi-line payload)

    long_text = "Asset code : FA-IT-5-14-0020\r\n" + "Name : " + "พาซิชั่น แผงชุดครึ่งกระจก-ลาย ยาว 380xสูง 160 ซม. " * 2
    template.elements[0].w_mm = template.elements[0].h_mm = 15
    _, warnings = R.render_job(template, [({"ASSETID": "A"}, long_text)], copies=1, ecc="M")
    assert any("hard to scan" in w for w in warnings)
    _, warnings = R.render_job(template, [({"ASSETID": "A"}, "FA-IT-5-14-0020")], copies=1)
    assert not any("hard to scan" in w for w in warnings)
