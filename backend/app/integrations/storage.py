"""文件存储：照片原图、抠图、导出图、回执图都放这里。

local 模式（默认）存在本机目录，下载走 /files/{key}?exp=&sig= 签名链接；
oss 模式存阿里云 OSS，下载走 OSS V4 预签名链接。业务代码只使用 get_storage() 返回的对象。
"""

import hmac
import re
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlencode

import httpx

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


_OSS_ALGORITHM = "OSS4-HMAC-SHA256"
_OSS_UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"


class OssStorage:
    """使用 Bucket.Endpoint 虚拟主机地址和 OSS V4 签名读写私有对象。"""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        access_key_secret: str,
        region: str = "",
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise ValueError("OSS_BUCKET 缺失或格式无效")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", access_key_id):
            raise ValueError("OSS_ACCESS_KEY_ID 缺失或格式无效")
        if not access_key_secret or not access_key_secret.isascii():
            raise ValueError("OSS_ACCESS_KEY_SECRET 缺失或格式无效")
        endpoint = endpoint.strip()
        try:
            base = httpx.URL(endpoint if "://" in endpoint else f"https://{endpoint}")
        except httpx.InvalidURL:
            raise ValueError("OSS_ENDPOINT 格式无效") from None
        if (
            base.scheme not in ("http", "https")
            or not base.host
            or base.userinfo
            or base.raw_path != b"/"
            or base.fragment
        ):
            raise ValueError("OSS_ENDPOINT 必须是 OSS 服务地址")

        self._region = region.strip() or self._region_from_endpoint(base.host)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", self._region):
            raise ValueError("OSS_REGION 缺失或格式无效")
        self.bucket = bucket
        self._base = base.copy_with(host=f"{bucket}.{base.host}")
        self._host = self._base.netloc.decode("ascii")
        self._access_key_id = access_key_id
        self._signing_secret = f"aliyun_v4{access_key_secret}".encode("ascii")
        self._client = client if client is not None else httpx.Client(timeout=10.0)

    @staticmethod
    def _region_from_endpoint(host: str) -> str:
        match = re.fullmatch(r"oss-([a-z]{2}(?:-[a-z0-9]+)+?)\.aliyuncs\.com", host)
        return match[1].removesuffix("-internal") if match else ""

    def _object_path(self, key: str) -> str:
        # URL 客户端和浏览器会折叠点路径，拒绝它们以免访问到另一个对象。
        if not key or key.startswith(("/", "\\")) or {".", ".."}.intersection(key.split("/")):
            raise ValueError("OSS 对象键无效")
        return "/" + quote(key, safe="/")

    def _signing_scope(self) -> tuple[str, str]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return timestamp, f"{timestamp[:8]}/{self._region}/oss/aliyun_v4_request"

    def _signature(
        self, method: str, path: str, query: str, headers: dict[str, str], timestamp: str, scope: str
    ) -> str:
        # 请求 URL 中 Bucket 在 Host，V4 的 canonical URI 仍包含 Bucket。
        canonical_headers = "".join(f"{name}:{value.strip()}\n" for name, value in sorted(headers.items()))
        canonical = "\n".join(
            (method, f"/{self.bucket}{path}", query, canonical_headers, "host", _OSS_UNSIGNED_PAYLOAD)
        )
        string_to_sign = "\n".join(
            (_OSS_ALGORITHM, timestamp, scope, sha256(canonical.encode("ascii")).hexdigest())
        )
        signing_key = self._signing_secret
        for component in scope.split("/"):
            signing_key = hmac.digest(signing_key, component.encode("ascii"), "sha256")
        return hmac.digest(signing_key, string_to_sign.encode("ascii"), "sha256").hex()

    def _request(
        self, method: str, key: str, *, data: bytes | None = None, mime: str | None = None
    ) -> httpx.Response:
        path = self._object_path(key)
        timestamp, scope = self._signing_scope()
        headers = {
            "host": self._host,
            "x-oss-content-sha256": _OSS_UNSIGNED_PAYLOAD,
            "x-oss-date": timestamp,
        }
        if mime is not None:
            headers["content-type"] = mime
            headers["x-oss-object-acl"] = "private"
        signature = self._signature(method, path, "", headers, timestamp, scope)
        headers["authorization"] = (
            f"{_OSS_ALGORITHM} Credential={self._access_key_id}/{scope},"
            f"AdditionalHeaders=host,Signature={signature}"
        )
        request = httpx.Request(
            method, self._base.copy_with(raw_path=path.encode("ascii")), headers=headers, content=data
        )
        try:
            response = self._client.send(request, auth=None, follow_redirects=False)
        except httpx.TimeoutException:
            error = TimeoutError("OSS 请求超时")
        except httpx.HTTPError:
            error = OSError("OSS 请求失败")
        else:
            if response.status_code == 404 and method == "GET":
                raise FileNotFoundError("OSS 对象不存在")
            if response.is_success or (response.status_code == 404 and method == "DELETE"):
                return response
            # OSS 的错误响应可能回显鉴权信息，仅保留方法和状态码。
            raise OSError(f"OSS {method} 失败（HTTP {response.status_code}）")
        # 离开 except 后抛出，避免把含原始请求的异常挂到异常链上。
        raise error

    def put(self, key: str, data: bytes, mime: str) -> None:
        self._request("PUT", key, data=data, mime=mime)

    def get(self, key: str) -> bytes:
        return self._request("GET", key).content

    def delete(self, key: str) -> None:
        self._request("DELETE", key)

    def url(self, key: str, expires_in: int = 600) -> str:
        if not 1 <= expires_in <= 604_800:
            raise ValueError("OSS 签名链接有效期须为 1 到 604800 秒")
        path = self._object_path(key)
        timestamp, scope = self._signing_scope()
        query = urlencode(
            sorted(
                {
                    "x-oss-additional-headers": "host",
                    "x-oss-credential": f"{self._access_key_id}/{scope}",
                    "x-oss-date": timestamp,
                    "x-oss-expires": str(expires_in),
                    "x-oss-signature-version": _OSS_ALGORITHM,
                }.items()
            ),
            quote_via=quote,
        )
        signature = self._signature("GET", path, query, {"host": self._host}, timestamp, scope)
        return str(
            self._base.copy_with(raw_path=f"{path}?{query}&x-oss-signature={signature}".encode("ascii"))
        )


_local: LocalStorage | None = None
_oss: OssStorage | None = None


def get_storage() -> Storage:
    global _local, _oss
    if settings.storage_mode == "oss":
        if _oss is None:
            _oss = OssStorage(
                endpoint=settings.oss_endpoint,
                bucket=settings.oss_bucket,
                access_key_id=settings.oss_access_key_id,
                access_key_secret=settings.oss_access_key_secret,
                region=settings.oss_region,
            )
        return _oss
    if _local is None:
        _local = LocalStorage(settings.local_storage_dir)
    return _local
