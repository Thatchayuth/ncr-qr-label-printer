import json

import pytest
from PIL import Image, ImageDraw

from qrlabel.domain.errors import ValidationError
from qrlabel.domain.layout import mm_to_dots, validate_template
from qrlabel.domain.models import LabelElement
from qrlabel.rendering.images import decode_image, load_image_file
from qrlabel.rendering.raster import rasterize_element, render_label_image
from qrlabel.rendering.tspl import TsplRenderer
from qrlabel.services.template_io import FILE_FORMAT, export_template, import_template
from qrlabel.ui.designer.canvas import smart_guides


def px(img):
    return list(img.convert("L").tobytes())


@pytest.fixture
def logo_file(tmp_path):
    """Transparent PNG, 200x100: black square on the left, red circle on the right."""
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 90, 90], fill=(0, 0, 0, 255))
    d.ellipse([110, 10, 190, 90], fill=(200, 0, 0, 255))
    path = tmp_path / "logo.png"
    img.save(path)
    return path


def test_load_flattens_transparency_to_white(logo_file):
    data, w, h = load_image_file(logo_file)
    assert (w, h) == (200, 100)
    img = decode_image(data)
    assert img.mode == "L"
    assert img.getpixel((0, 0)) == 255  # transparent corner became white
    assert img.getpixel((50, 50)) == 0  # black square stays black


def test_load_rejects_non_images(tmp_path):
    p = tmp_path / "x.png"
    p.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_image_file(p)


def test_image_fits_box_keeping_aspect(template, logo_file):
    data, _, _ = load_image_file(logo_file)
    el = LabelElement(kind="image", x_mm=2, y_mm=2, w_mm=20, h_mm=20, image_data=data)
    placed, warnings = rasterize_element(el, template, {}, None)
    assert warnings == []
    box = mm_to_dots(20)
    assert placed.image.size == (box, box)
    bw = placed.image.convert("L")
    # 2:1 picture in a square box: top and bottom quarters stay white
    assert min(px(bw.crop((0, 0, box, box // 4 - 2)))) == 255
    assert min(px(bw.crop((0, box // 4 + 2, box // 2, box * 3 // 4 - 2)))) == 0


def test_image_printed_as_bitmap(template, logo_file):
    data, _, _ = load_image_file(logo_file)
    template.elements.append(LabelElement(kind="image", x_mm=1, y_mm=1, w_mm=8, h_mm=4, image_data=data))
    out, warnings = TsplRenderer().render_job(template, [({"ASSETID": "A"}, "A")], copies=1)
    assert out.count(b"BITMAP ") == 3 and warnings == []


def test_image_without_data_is_invalid(template):
    template.elements.append(LabelElement(kind="image", x_mm=1, y_mm=1, w_mm=5, h_mm=5))
    assert any("no image" in p for p in validate_template(template))


def test_dither_option_changes_grey_rendering(template, tmp_path):
    grey = Image.new("L", (40, 40), 128)
    p = tmp_path / "grey.png"
    grey.save(p)
    data, _, _ = load_image_file(p)
    el = LabelElement(kind="image", x_mm=1, y_mm=1, w_mm=5, h_mm=5, image_data=data)
    hard, _ = rasterize_element(el, template, {}, None)
    el.dither = True
    dithered, _ = rasterize_element(el, template, {}, None)
    hard_black = px(hard.image).count(0)
    dither_black = px(dithered.image).count(0)
    assert hard_black in (0, len(px(hard.image)))  # 50% grey is all one colour without dithering
    assert 0 < dither_black < len(px(dithered.image))  # pattern of dots with dithering


def test_template_with_image_roundtrip(template, logo_file, tmp_path):
    data, _, _ = load_image_file(logo_file)
    template.elements.append(LabelElement(kind="image", x_mm=1, y_mm=1, w_mm=8, h_mm=4, image_data=data))
    path = tmp_path / "t.json"
    export_template(template, path)
    again = import_template(path)
    assert again.elements[-1].image_data == data
    img, _ = render_label_image(again, {"ASSETID": "A"}, "A")
    assert img.size == (mm_to_dots(40), mm_to_dots(30))


def test_import_rejects_damaged_image(template, tmp_path):
    d = template.to_dict()
    d["elements"].append(LabelElement(kind="image", x_mm=1, y_mm=1, w_mm=5, h_mm=5, image_data="!!notbase64").__dict__)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"format": FILE_FORMAT, "format_version": 1, "template": d}), encoding="utf-8")
    with pytest.raises(ValidationError):
        import_template(p)


# ------------------------------------------------------------------- guides

def test_smart_guides_snap_to_centre_within_tolerance():
    # 10 x 6 element on a 40 x 30 label: centre lines at x=20, y=15
    x, y, v, h = smart_guides(14.6, 11.7, 10, 6, [20.0], [15.0], tol=0.5)
    assert (x, y) == (15.0, 12.0) and v == [20.0] and h == [15.0]


def test_smart_guides_ignore_far_targets():
    x, y, v, h = smart_guides(5.0, 3.0, 10, 6, [20.0], [15.0], tol=0.5)
    assert (x, y, v, h) == (5.0, 3.0, [], [])


def test_smart_guides_pick_nearest_target():
    x, _, v, _ = smart_guides(13.0, 0, 4, 2, [15.4, 20.0], [], tol=0.6)
    assert v == [15.4] and x == pytest.approx(13.4)
