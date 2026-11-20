import traceback
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import httpx
import pytest

from app.integrations import storage
from app.integrations.storage import LocalStorage, OssStorage, get_storage

BUCKET = "photos-example"
ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"
HOST = f"{BUCKET}.{ENDPOINT}"
ACCESS_KEY_ID = "OSSExampleId"
ACCESS_KEY_SECRET = "OSSExampleSecret"
TIMESTAMP = "20241203T034420Z"
CREDENTIAL = f"{ACCESS_KEY_ID}/20241203/cn-hangzhou/oss/aliyun_v4_request"
KEY = "test/u12/证件 +%?#.png"
OBJECT_PATH = b"/test/u12/%E8%AF%81%E4%BB%B6%20%2B%25%3F%23.png"

# 按阿里云 V4 规范手写 canonical request，再用 Ruby OpenSSL 独立计算的向量。
SIGNATURES = {
    "PUT": "7649a72054bb76c7b2be6241629dd0993f68c8cb912eb6dc595d4106bd647545",
    "GET": "23c3aafe96e83a6396ed925983e417b4a77dcb0e8805661fcc7862dc98ff40a3",
    "DELETE": "148281f313ce3b8582ff72ae9c31b60f571dcf9a2d2cbc658d05f50e9c255cc8",
}


@pytest.fixture
def oss_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[httpx.MockTransport], OssStorage]]:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 12, 3, 3, 44, 20, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(storage, "datetime", FixedDateTime)
    clients = []

    def create(transport: httpx.MockTransport) -> OssStorage:
        client = httpx.Client(transport=transport)
        clients.append(client)
        return OssStorage(ENDPOINT, BUCKET, ACCESS_KEY_ID, ACCESS_KEY_SECRET, client=client)

    yield create
    for client in clients:
        client.close()


def test_oss_object_requests(oss_factory):
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.scheme == "https"
        assert request.headers["host"] == HOST
        assert request.url.raw_path == OBJECT_PATH
        assert request.headers["x-oss-date"] == TIMESTAMP
        assert request.headers["x-oss-content-sha256"] == "UNSIGNED-PAYLOAD"
        assert request.headers["authorization"] == (
            f"OSS4-HMAC-SHA256 Credential={CREDENTIAL},AdditionalHeaders=host,"
            f"Signature={SIGNATURES[request.method]}"
        )
        if request.method == "PUT":
            assert request.headers["content-type"] == "image/png"
            assert request.headers["x-oss-object-acl"] == "private"
            assert request.content == b"photo bytes"
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(200, content=b"photo bytes")
        return httpx.Response(204)

    oss = oss_factory(httpx.MockTransport(handle))
    assert oss.bucket == BUCKET
    assert oss.put(KEY, b"photo bytes", "image/png") is None
    assert oss.get(KEY) == b"photo bytes"
    assert oss.delete(KEY) is None
    assert [request.method for request in requests] == ["PUT", "GET", "DELETE"]


def test_oss_presigned_download(oss_factory):
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("生成签名链接无需连接 OSS")

    oss = oss_factory(httpx.MockTransport(handle))
    url = httpx.URL(oss.url(KEY, 900))
    assert url.scheme == "https"
    assert url.host == HOST
    assert url.raw_path.split(b"?", 1)[0] == OBJECT_PATH
    assert dict(url.params) == {
        "x-oss-additional-headers": "host",
        "x-oss-credential": CREDENTIAL,
        "x-oss-date": TIMESTAMP,
        "x-oss-expires": "900",
        "x-oss-signature-version": "OSS4-HMAC-SHA256",
        "x-oss-signature": "4dc6e6025e4271c636f0e1860c4e58af5747b67c2aafe24190ebf9793e6cb190",
    }
    assert ACCESS_KEY_SECRET not in str(url)
    assert httpx.URL(oss.url(KEY)).params["x-oss-expires"] == "600"


@pytest.mark.parametrize("expires_in", [0, 604_801])
def test_oss_rejects_unsupported_expiry(oss_factory, expires_in):
    oss = oss_factory(httpx.MockTransport(lambda request: httpx.Response(200)))
    with pytest.raises(ValueError, match="有效期"):
        oss.url(KEY, expires_in)


def test_oss_not_found_matches_local_storage(oss_factory, tmp_path):
    oss = oss_factory(httpx.MockTransport(lambda request: httpx.Response(404)))
    for backend in (LocalStorage(str(tmp_path)), oss):
        with pytest.raises(FileNotFoundError):
            backend.get(KEY)
        assert backend.delete(KEY) is None
    with pytest.raises(OSError, match="HTTP 404"):
        oss.put(KEY, b"photo bytes", "image/png")


def test_oss_timeout_hides_credentials(oss_factory, caplog):
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"{ACCESS_KEY_ID} {ACCESS_KEY_SECRET}", request=request)

    oss = oss_factory(httpx.MockTransport(handle))
    with pytest.raises(TimeoutError, match="OSS 请求超时") as exc:
        oss.get(KEY)
    assert exc.value.__context__ is None
    captured = caplog.text + "".join(traceback.format_exception(exc.value))
    assert ACCESS_KEY_ID not in captured
    assert ACCESS_KEY_SECRET not in captured


def test_oss_error_response_hides_credentials(oss_factory, caplog):
    caplog.set_level("INFO", logger="httpx")
    oss = oss_factory(
        httpx.MockTransport(lambda request: httpx.Response(403, text=f"{ACCESS_KEY_ID} {ACCESS_KEY_SECRET}"))
    )
    with pytest.raises(OSError, match="HTTP 403") as exc:
        oss.get(KEY)
    captured = caplog.text + "".join(traceback.format_exception(exc.value))
    assert ACCESS_KEY_ID not in captured
    assert ACCESS_KEY_SECRET not in captured


def test_get_storage_selects_oss_with_configured_region(monkeypatch):
    monkeypatch.setattr(storage, "_oss", None)
    monkeypatch.setattr(storage.settings, "storage_mode", "oss")
    monkeypatch.setattr(storage.settings, "oss_endpoint", "https://oss-accelerate.aliyuncs.com/")
    monkeypatch.setattr(storage.settings, "oss_bucket", BUCKET)
    monkeypatch.setattr(storage.settings, "oss_access_key_id", ACCESS_KEY_ID)
    monkeypatch.setattr(storage.settings, "oss_access_key_secret", ACCESS_KEY_SECRET)
    monkeypatch.setattr(storage.settings, "oss_region", "cn-shanghai")

    oss = get_storage()
    assert isinstance(oss, OssStorage)
    assert oss.bucket == BUCKET
    assert get_storage() is oss
    assert "/cn-shanghai/oss/aliyun_v4_request" in httpx.URL(oss.url(KEY)).params["x-oss-credential"]

    monkeypatch.setattr(storage.settings, "storage_mode", "local")
    assert isinstance(get_storage(), LocalStorage)
