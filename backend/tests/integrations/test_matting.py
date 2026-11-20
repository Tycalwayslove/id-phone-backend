import io
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageDraw

from app.integrations import matting


def test_fake_matting_removes_background_and_keeps_subject(monkeypatch):
    monkeypatch.setattr(matting, "settings", SimpleNamespace(matting_mode="fake", matting_timeout_seconds=5))
    original = Image.new("RGB", (32, 32), (240, 240, 240))
    draw = ImageDraw.Draw(original)
    draw.rectangle((0, 16, 31, 31), fill=(228, 232, 236))
    draw.rectangle((8, 8, 23, 23), fill=(80, 120, 160))
    buf = io.BytesIO()
    original.save(buf, "PNG")

    result = matting.get_matting().matte(buf.getvalue())
    with Image.open(io.BytesIO(result)) as out:
        assert out.format == "PNG"
        assert out.mode == "RGBA"
        assert out.size == original.size
        assert out.getpixel((0, 0))[3] == 0
        assert out.getpixel((30, 30))[3] == 0
        assert out.getpixel((16, 16)) == (80, 120, 160, 255)


def test_fake_matting_preserves_existing_alpha():
    original = Image.new("RGBA", (32, 32), (80, 90, 100, 0))
    original.putpixel((16, 16), (80, 90, 100, 128))
    original.putpixel((16, 17), (80, 90, 100, 255))
    buf = io.BytesIO()
    original.save(buf, "PNG")

    result = matting.FakeMatting().matte(buf.getvalue())
    with Image.open(io.BytesIO(result)) as out:
        assert out.tobytes() == original.tobytes()


def test_real_matting_is_a_stub(monkeypatch):
    monkeypatch.setattr(matting.settings, "matting_mode", "zheying")

    with pytest.raises(NotImplementedError):
        matting.get_matting().matte(b"original")


def test_real_matting_raises_builtin_timeout_error(monkeypatch):
    monkeypatch.setattr(
        matting, "settings", SimpleNamespace(matting_mode="zheying", matting_timeout_seconds=2)
    )

    def timeout_request(self, data, *, timeout):
        assert data == b"original"
        assert timeout == 2
        raise httpx.ReadTimeout("upstream read timed out")

    monkeypatch.setattr(matting.RealMatting, "_request", timeout_request)

    with pytest.raises(TimeoutError) as exc:
        matting.get_matting().matte(b"original")
    assert isinstance(exc.value.__cause__, httpx.ReadTimeout)
