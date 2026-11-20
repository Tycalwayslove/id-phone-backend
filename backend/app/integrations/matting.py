"""抠图适配器，统一返回带透明通道的 PNG。"""

import io
from typing import Protocol

import httpx
from PIL import Image, ImageChops, ImageOps

from app.core.config import settings

DEFAULT_TIMEOUT_SECONDS = 5.0
BACKGROUND_TOLERANCE = 24


class MattingClient(Protocol):
    def matte(self, data: bytes) -> bytes:
        """接收原图字节并返回 RGBA PNG。外部服务调用超时抛 TimeoutError。"""
        ...


class FakeMatting:
    """开发联调用的纯色背景抠除，保留已有的透明通道。"""

    def matte(self, data: bytes) -> bytes:
        with Image.open(io.BytesIO(data)) as src:
            img = ImageOps.exif_transpose(src).convert("RGBA")
        if img.getchannel("A").getextrema()[0] == 255:
            rgb = img.convert("RGB")
            background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            red, green, blue = ImageChops.difference(rgb, background).split()
            distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            img.putalpha(distance.point(lambda value: 0 if value <= BACKGROUND_TOLERANCE else 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class RealMatting:
    def __init__(self, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def matte(self, data: bytes) -> bytes:
        try:
            return self._request(data, timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            raise TimeoutError("抠图服务调用超时") from exc

    def _request(self, data: bytes, *, timeout: float) -> bytes:
        raise NotImplementedError("正式抠图服务待接入")


def get_matting() -> MattingClient:
    if settings.matting_mode == "fake":
        return FakeMatting()
    return RealMatting(timeout_seconds=settings.matting_timeout_seconds)
