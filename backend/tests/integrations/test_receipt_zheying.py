import hashlib
import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

from app.core.errors import AppError, ErrorCode
from app.integrations import receipt_providers
from app.integrations.receipt_providers import build_callback_url, get_provider
from app.integrations.receipt_providers.base import SubmitRequest
from app.integrations.receipt_providers.fake import FakeProvider
from app.integrations.receipt_providers.qianweiyun import QianweiyunProvider
from app.integrations.receipt_providers.zheying import ZheyingProvider

_KEY = "test-provider-key"
_SIGN = hashlib.md5(_KEY.encode()).hexdigest()
_ORDER_NO = "20210616134106190536"
_CALLBACK_URL = "https://ours.example/api/v1/callbacks/receipt/provider-a"
_FORM_HEADERS = {"content-type": "application/x-www-form-urlencoded"}


@pytest.fixture
def submit_request():
    return SubmitRequest(
        attempt_ref="attempt-a",
        provider_item_id="713",
        photo=b"\xfb\xff",
        photo_mime="image/jpeg",
        form={"text_city": "深圳"},
        region_code="440300",
    )


@pytest.fixture
def provider():
    def no_network(request):
        pytest.fail(f"Unexpected request for {request.url.path}")

    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        yield _provider(client)


def _provider(client):
    return ZheyingProvider(
        "provider-a",
        base_url="https://zheying.example",
        app_key=_KEY,
        callback_url=_CALLBACK_URL,
        client=client,
    )


def _body(status, **fields):
    return urlencode({"order_no": _ORDER_NO, "status": status, "sign": _SIGN, **fields}).encode()


@pytest.mark.parametrize(
    ("adapter", "cls", "host", "key", "order_no"),
    [
        ("zheying", ZheyingProvider, "zheying.example", _KEY, _ORDER_NO),
        ("qianweiyun", QianweiyunProvider, "qianweiyun.example", "test-qianweiyun-key", int(_ORDER_NO)),
    ],
)
def test_real_provider_submits_make_then_submit(
    monkeypatch, submit_request, adapter, cls, host, key, order_no
):
    monkeypatch.setattr(
        receipt_providers,
        "settings",
        SimpleNamespace(
            receipt_mode="real",
            public_base_url="https://ours.example/",
            zheying_api_base="https://zheying.example/",
            zheying_app_key=_KEY,
            qianweiyun_api_base="https://qianweiyun.example/",
            qianweiyun_app_key="test-qianweiyun-key",
        ),
    )
    expected = ["/receipt/make", "/receipt/submit"] * 2
    sent_nonces = []

    def handle(request):
        assert request.method == "POST"
        assert request.url == f"https://{host}{expected.pop(0)}"
        assert request.headers["content-type"] == _FORM_HEADERS["content-type"]
        form = parse_qs(request.content.decode())
        assert form.pop("key") == [key]
        if request.url.path == "/receipt/make":
            assert form == {"item_id": ["713"], "image": ["+/8="]}
            return httpx.Response(200, json={"code": 0, "data": {"pic_id": 123}})
        assert form.pop("pic_id") == ["123"]
        assert json.loads(form.pop("param")[0]) == submit_request.form
        url = httpx.URL(form.pop("notice_url")[0])
        sent_nonces.append(url.params["nonce"])
        assert url.copy_with(query=None) == _CALLBACK_URL
        assert not form
        return httpx.Response(200, json={"code": 0, "data": {"order_no": order_no}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = get_provider(adapter, "provider-a", client=client)
        assert isinstance(provider, cls)
        assert provider.submit(submit_request) == _ORDER_NO
        _, nonce = build_callback_url(_CALLBACK_URL)
        bound_provider = get_provider(adapter, "provider-a", client=client, callback_nonce=nonce)
        assert bound_provider.submit(submit_request) == _ORDER_NO
        assert not client.is_closed

    assert not expected
    assert sent_nonces[0] and sent_nonces[0] != nonce
    assert sent_nonces[1] == nonce


def test_build_callback_url_replaces_old_nonce_and_keeps_other_parameters():
    url, nonce = build_callback_url(f"{_CALLBACK_URL}?foo=bar&nonce=old")
    _, other_nonce = build_callback_url(_CALLBACK_URL)
    assert nonce and nonce != other_nonce
    assert httpx.URL(url).params.multi_items() == [("foo", "bar"), ("nonce", nonce)]


def test_fake_mode_keeps_provider_instances_by_code(monkeypatch):
    monkeypatch.setattr(receipt_providers, "settings", SimpleNamespace(receipt_mode="fake"))
    provider = get_provider("zheying", "t004-fake")
    assert isinstance(provider, FakeProvider)
    assert get_provider("qianweiyun", "t004-fake") is provider


def test_rejected_callback(provider):
    status, dedupe_key = provider.parse_callback(_FORM_HEADERS, _body(-1, reject_msg="背景不均匀"))
    assert status.result == "rejected"
    assert status.reject_reason == "背景不均匀"
    assert status.provider_order_no == _ORDER_NO
    assert dedupe_key == f"provider-a:{_ORDER_NO}:-1"


def test_completed_callback_keeps_receipt_url_for_async_download(provider):
    image_url = "https://cdn.example/receipt.png"
    status, key = provider.parse_callback(
        _FORM_HEADERS, _body(3, image_receipt=image_url, nonce="ignore-this", key=_KEY)
    )
    assert status.result == "completed"
    assert status.raw == {"status": "3", "image_receipt": image_url}
    assert status.receipt_image is None
    assert status.image_code is None
    assert status.official_expire_at is None
    assert key == f"provider-a:{_ORDER_NO}:3"


@pytest.mark.parametrize(
    "fields",
    [
        {"logistics_info": '[{"express_name":"快递","express_no":"000123"}]'},
        {"logistics_info": '{"express_name":"快递","express_no":"000123"}'},
        {"logistics_info[0][express_name]": "快递", "logistics_info[0][express_no]": "000123"},
    ],
)
def test_shipped_callback_keeps_logistics(provider, fields):
    status, key = provider.parse_callback(_FORM_HEADERS, _body(4, **fields))
    assert status.result == "completed"
    assert status.raw["logistics_info"] == [{"express_name": "快递", "express_no": "000123"}]
    assert key == f"provider-a:{_ORDER_NO}:4"


@pytest.mark.parametrize(("state", "result"), [(2, "processing"), (-2, "failed"), (99, "processing")])
def test_callback_maps_status(provider, caplog, state, result):
    with caplog.at_level(logging.WARNING):
        status, _ = provider.parse_callback(_FORM_HEADERS, _body(state, nonce="ignore-this"))
    assert status.result == result
    assert bool(caplog.records) == (state == 99)
    assert all(value not in caplog.text for value in (_KEY, _SIGN, "ignore-this"))


@pytest.mark.parametrize("sign", ["invalid", "", "错误签名", _SIGN.upper()])
def test_callback_rejects_invalid_signature(provider, sign):
    with pytest.raises(AppError) as caught:
        provider.parse_callback(_FORM_HEADERS, _body(3, sign=sign))
    assert caught.value.code == ErrorCode.CALLBACK_SIGNATURE_INVALID
    assert _SIGN not in str(caught.value)
    assert not sign or sign not in str(caught.value)


def test_callback_rejects_duplicate_signature(provider):
    with pytest.raises(AppError) as caught:
        provider.parse_callback(_FORM_HEADERS, _body(3) + f"&sign={_SIGN}".encode())
    assert caught.value.code == ErrorCode.CALLBACK_SIGNATURE_INVALID


@pytest.mark.parametrize("path", ["/receipt/make", "/receipt/submit"])
@pytest.mark.parametrize("failure", ["timeout", "business_error"])
def test_submit_stops_on_upstream_error(submit_request, caplog, path, failure):
    calls = []
    sensitive_message = f"{_KEY} {_SIGN} example-nonce"

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == path:
            if failure == "timeout":
                raise httpx.ReadTimeout(sensitive_message, request=request)
            return httpx.Response(200, json={"code": 42, "msg": sensitive_message})
        return httpx.Response(200, json={"code": 0, "data": {"pic_id": "123"}})

    error = TimeoutError if failure == "timeout" else AppError
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(error) as caught:
        _provider(client).submit(submit_request)

    if isinstance(caught.value, AppError):
        assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.__context__ is None
    assert all(value not in str(caught.value) + caplog.text for value in sensitive_message.split())
    assert calls == (["/receipt/make"] if path == "/receipt/make" else ["/receipt/make", "/receipt/submit"])


def test_submit_treats_missing_order_number_as_unknown(submit_request):
    responses = iter([{"code": 0, "data": {"pic_id": "123"}}, {"code": 0, "data": {}}])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=next(responses)))
    with httpx.Client(transport=transport) as client, pytest.raises(TimeoutError):
        _provider(client).submit(submit_request)


def test_query_returns_processing_without_a_network_call(provider):
    status = provider.query(_ORDER_NO)
    assert status.provider_order_no == _ORDER_NO
    assert status.result == "processing"


@pytest.mark.parametrize("provider_class", [ZheyingProvider, QianweiyunProvider])
def test_catalog_list_and_detail_parse_form_and_normalize_values(provider_class, caplog):
    row = {
        "name": "小一寸",
        "color": "['blue','white','red','tint','grey','gradient','dark_blue','unknown']",
        "width_px": "260",
        "height_px": "378",
        "width_mm": "22.5",
        "height_mm": "32",
        "dpi": "300",
        "file_size_msg": "20~80KB",
    }

    def handle(request):
        assert request.method == "POST"
        assert request.url.query == b""
        assert request.headers["content-type"] == _FORM_HEADERS["content-type"]
        form = parse_qs(request.content.decode())
        if request.url.path == "/item/list":
            assert form == {"key": [_KEY]}
            data = {"list": [{"item_id": "001", **row}]}
        else:
            assert request.url.path == "/item/get"
            assert form == {"key": [_KEY], "item_id": ["001"]}
            data = {
                "id": "001",
                **row,
                "file_size_min": "20",
                "file_size_max": "80",
                "sort": "2",
                "category": "证件照",
                "category_id": "4",
                "key": _KEY,
            }
        return httpx.Response(200, json={"code": 0, "data": data})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = provider_class(
            "catalog",
            base_url="https://catalog.example",
            app_key=_KEY,
            callback_url=_CALLBACK_URL,
            client=client,
        )
        (item,) = provider.list_items()
        detail = provider.get_item(item.provider_item_id)

    assert item.provider_item_id == detail.provider_item_id == "001"
    assert detail.name == item.name == "小一寸"
    assert (item.width_px, item.height_px, item.width_mm, item.height_mm, item.dpi) == (260, 378, 23, 32, 300)
    assert (
        item.bg_colors
        == detail.bg_colors
        == [
            "#438EDB",
            "#FFFFFF",
            "#FF0000",
            "#EAF1FB",
            "#BFBFBF",
            "#1A3B8C",
        ]
    )
    assert item.raw["color"] == detail.raw["color"] == row["color"]
    assert item.file_size_min_kb is None and item.file_size_max_kb is None
    assert (detail.file_size_min_kb, detail.file_size_max_kb, detail.sort) == (20, 80, 2)
    assert detail.raw["category_id"] == "4"
    assert "key" not in detail.raw and _KEY not in caplog.text
    assert "未知底色" in caplog.text


@pytest.mark.parametrize("method", ["list_items", "get_item"])
@pytest.mark.parametrize("failure", ["timeout", "business_error", "http_error"])
def test_catalog_errors_hide_upstream_messages(caplog, method, failure):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(_KEY, request=request)
        code, status = (42, 200) if failure == "business_error" else (0, 500)
        return httpx.Response(status, json={"code": code, "msg": _KEY})

    error = TimeoutError if failure == "timeout" else AppError
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(error) as caught:
        provider = _provider(client)
        provider.list_items() if method == "list_items" else provider.get_item("713")

    if isinstance(caught.value, AppError):
        assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.__context__ is None
    assert _KEY not in str(caught.value) + caplog.text


def test_catalog_rejects_color_expression():
    row = {
        "item_id": "1",
        "name": "示例",
        "color": "['white'] + ['blue']",
        "width_px": "200",
        "height_px": "300",
        "dpi": "300",
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 0, "data": {"list": [row]}}))
    with httpx.Client(transport=transport) as client, pytest.raises(AppError) as caught:
        _provider(client).list_items()
    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE


def test_clipimg_is_unavailable_in_real_mode(monkeypatch):
    monkeypatch.setattr(receipt_providers, "settings", SimpleNamespace(receipt_mode="real"))
    with pytest.raises(AppError) as caught:
        get_provider("clipimg", "clipimg")
    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE


def test_fake_catalog_is_repeatable_and_get_matches_list():
    fake = FakeProvider("zheying")
    rows = fake.list_items()
    assert len(rows) >= 10
    assert len({item.provider_item_id for item in rows}) == len(rows)
    assert fake.list_items() == rows
    assert fake.get_item(rows[0].provider_item_id) == rows[0]
