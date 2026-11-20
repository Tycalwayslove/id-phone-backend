import io
import os

import pytest
from PIL import Image, ImageDraw

from app.core.errors import AppError, ErrorCode
from app.modules.photos import imaging
from app.modules.photos.pipeline.face import Face
from tests.photos.helpers import jpeg_bytes, png_rgba_bytes


def _render(data, **kw):
    args = {
        "width_px": 358,
        "height_px": 441,
        "bg_color": "#438EDB",
        "dpi": 300,
        "max_kb": None,
        "watermarked": False,
    }
    return imaging.make_render(data, **(args | kw))


def test_render_size_and_dpi():
    out = Image.open(io.BytesIO(_render(jpeg_bytes())))
    assert out.format == "JPEG"
    assert out.size == (358, 441)
    assert round(out.info["dpi"][0]) == 300


def test_transparent_gets_background_color():
    out = Image.open(io.BytesIO(_render(png_rgba_bytes()))).convert("RGB")
    r, g, b = out.getpixel((10, 10))
    assert abs(r - 0x43) < 8 and abs(g - 0x8E) < 8 and abs(b - 0xDB) < 8


@pytest.mark.parametrize(("name", "hex_color"), [(" Blue ", "#438EDB"), ("dark_blue", "#1A3B8C")])
def test_legacy_background_name_matches_hex(name, hex_color):
    data = png_rgba_bytes()
    assert _render(data, bg_color=name) == _render(data, bg_color=hex_color)


def test_unknown_background_name_reports_validation_error():
    with pytest.raises(AppError) as error:
        _render(jpeg_bytes(), bg_color="rebeccapurple")
    assert error.value.code == ErrorCode.VALIDATION_ERROR


def test_watermark_changes_image():
    plain = Image.open(io.BytesIO(_render(jpeg_bytes()))).convert("RGB")
    marked = Image.open(io.BytesIO(_render(jpeg_bytes(), watermarked=True))).convert("RGB")
    assert plain.tobytes() != marked.tobytes()


def test_max_kb_lowers_quality():
    noise = Image.frombytes("RGB", (600, 800), os.urandom(600 * 800 * 3))
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    big = _render(buf.getvalue())
    small = _render(buf.getvalue(), max_kb=40)
    assert len(small) < len(big)


def test_inspect_rejects_bad_input():
    assert imaging.inspect_image(jpeg_bytes())[1:] == (600, 800)
    with pytest.raises(imaging.ImageInvalidError):
        imaging.inspect_image(b"not an image")
    with pytest.raises(imaging.ImageInvalidError):
        imaging.inspect_image(jpeg_bytes(200, 800))
    gif = io.BytesIO()
    Image.new("RGB", (400, 400)).save(gif, "GIF")
    with pytest.raises(imaging.ImageInvalidError):
        imaging.inspect_image(gif.getvalue())


@pytest.mark.parametrize("beauty_level", [0, 5])
def test_rgba_render_preserves_alpha_when_replacing_background(beauty_level):
    original = Image.new("RGBA", (96, 32), (255, 0, 0, 0))
    draw = ImageDraw.Draw(original)
    draw.rectangle((32, 0, 63, 31), fill=(255, 255, 255, 255))
    draw.rectangle((64, 0, 95, 31), fill=(0, 0, 0, 128))
    buf = io.BytesIO()
    original.save(buf, "PNG")

    result = _render(buf.getvalue(), width_px=96, height_px=32, bg_color="#4080C0", beauty_level=beauty_level)
    with Image.open(io.BytesIO(result)) as out:
        assert out.getpixel((16, 16)) == pytest.approx((64, 128, 192), abs=3)
        assert out.getpixel((48, 16)) == pytest.approx((255, 255, 255), abs=3)
        assert out.getpixel((80, 16)) == pytest.approx((32, 64, 96), abs=3)


@pytest.fixture
def textured_image():
    img = Image.frombytes("L", (64, 64), bytes([60, 180] * 32) * 64).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return img, buf.getvalue()


def test_auto_light_leaves_balanced_gray_unchanged(textured_image):
    original, data = textured_image
    legacy = io.BytesIO()
    original.save(legacy, "JPEG", quality=95, dpi=(300, 300), optimize=True)
    legacy.seek(0)

    result = _render(data, width_px=64, height_px=64, beauty_level=0)
    with Image.open(legacy) as expected, Image.open(io.BytesIO(result)) as out:
        assert out.tobytes() == expected.tobytes()


def test_crop_padding_is_not_a_foreground_mask_for_white_balance():
    warm = (224, 148, 95)
    buf = io.BytesIO()
    Image.new("RGB", (400, 500), warm).save(buf, "PNG")
    face = Face(0, 10, 160, 194, ((43, 67), (117, 67), (80, 109), (52, 144), (108, 144)), 0.95)

    result = _render(buf.getvalue(), width_px=350, height_px=450, face=face)
    with Image.open(io.BytesIO(result)) as out:
        assert out.getpixel((5, 5)) == pytest.approx((67, 142, 219), abs=3)
        assert out.getpixel((175, 225)) == pytest.approx(warm, abs=2)


def test_no_face_beauty_leaves_background_texture_alone(textured_image):
    _, data = textured_image
    baseline = _render(data, width_px=64, height_px=64, beauty_level=0)
    strong = _render(data, width_px=64, height_px=64, beauty_level=5)
    assert strong == baseline
