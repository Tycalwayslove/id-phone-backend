"""照片测试的本地工具：造图片字节、模拟权益。"""

import io
from types import SimpleNamespace

from PIL import Image


def jpeg_bytes(w: int = 600, h: int = 800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 80)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def png_rgba_bytes(w: int = 600, h: int = 800) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # 全透明
    img.save(buf, "PNG")
    return buf.getvalue()


def set_access(monkeypatch, *, active: bool, spec_change: bool = True) -> None:
    """替换 entitlements.service.photo_access，让测试不依赖权益模块的实现。"""

    def fake(db, user_id, photo_id):
        return SimpleNamespace(active=active, access_until=None, spec_change=spec_change)

    monkeypatch.setattr("app.modules.entitlements.service.photo_access", fake)


def upload(client, headers, data: bytes | None = None, *, name="a.jpg", mime="image/jpeg"):
    return client.post("/api/v1/uploads", files={"file": (name, data or jpeg_bytes(), mime)}, headers=headers)


def make_photo(client, headers) -> int:
    file_id = upload(client, headers).json()["file_id"]
    r = client.post("/api/v1/photos", json={"file_id": file_id, "source": "upload"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]
