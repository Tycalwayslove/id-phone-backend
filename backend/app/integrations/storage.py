"""文件存储：照片原图、抠图、导出图、回执图都放这里。

local 模式（默认）存在本机目录，下载走 /files/{key}?exp=&sig= 签名链接；
oss 模式存阿里云 OSS（待接入）。业务代码只用 get_storage() 返回的对象，不关心存在哪。
"""

import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from app.core.config import settings
from app.core.security import sign


class Storage(Protocol):
    bucket: str

    def put(self, key: str, data: bytes, mime: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def url(self, key: str, expires_in: int = 600) -> str: ...


def build_key(
    *,
    user_id: int,
    owner: str,
    kind: str,
    file_id: int,
    ext: str,
    spec_code: str | None = None,
    bg: str | None = None,
    beauty: int | None = None,
) -> str:
    """按命名规则生成存储路径：
    {env}/u{user_id}/{owner}/{kind}[_{spec_code}_{bg}_b{beauty}]_f{file_id}.{ext}
    owner 是 p<photo_id> 或 a<app_id>。
    """
    variant = f"_{spec_code}_{(bg or 'none').lstrip('#')}_b{beauty or 0}" if spec_code else ""
    return f"{settings.app_env}/u{user_id}/{owner}/{kind}{variant}_f{file_id}.{ext.lstrip('.')}"


def url_signature(key: str, exp: int) -> str:
    return sign(f"file:{key}:{exp}")


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.bucket = "local"

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("非法路径")
        return p

    def put(self, key: str, data: bytes, mime: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url(self, key: str, expires_in: int = 600) -> str:
        exp = int(time.time()) + expires_in
        return f"{settings.public_base_url}/files/{quote(key)}?exp={exp}&sig={url_signature(key, exp)}"


_local: LocalStorage | None = None


def get_storage() -> Storage:
    global _local
    if settings.storage_mode == "oss":
        raise NotImplementedError("OSS 存储待接入：需要 OSS 账号后实现")
    if _local is None:
        _local = LocalStorage(settings.local_storage_dir)
    return _local
