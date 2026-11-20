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
from app.integrations.receipt_providers.clipimg import ClipimgProvider
from app.integrations.receipt_providers.fake import FakeProvider
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
        ("clipimg", ClipimgProvider, "clipimg.example", "test-clipimg-key", int(_ORDER_NO)),
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
            clipimg_api_base="https://clipimg.example/",
            clipimg_app_key="test-clipimg-key",
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
    assert get_provider("clipimg", "t004-fake") is provider


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
