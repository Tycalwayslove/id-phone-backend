import io
import os

import pytest
from PIL import Image

from app.modules.photos import imaging
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
