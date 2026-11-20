import base64
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.integrations.payment import PAY_NOTIFY_PATH, REFUND_NOTIFY_PATH, WechatPay

APP_ID = "wx-test-app"
MCH_ID = "1900000001"
KEY_ID = "PUB_KEY_ID_123"
API_KEY = "a" * 32
TRADE_NO = "P20261119999999"
REFUND_NO = "RA" + "f" * 32
TRANSACTION_ID = "4200000000000001"
ALGORITHM = "WECHATPAY2-SHA256-RSA2048"
ORDER_PATH = "/v3/pay/transactions/out-trade-no/"
REFUND_PATH = "/v3/refund/domestic/refunds"


@pytest.fixture(scope="module")
def key_files(tmp_path_factory):
    directory = tmp_path_factory.mktemp("wxpay")
    merchant = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_path = directory / "merchant.pem"
    merchant_path.write_bytes(
        merchant.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Test Platform")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(platform.public_key())
        .serial_number(0xABCDEF)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(platform, hashes.SHA256())
    )
    cert_path = directory / "platform.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    public_path = directory / "public.pem"
    public_path.write_bytes(
        public_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return SimpleNamespace(
        merchant=merchant.public_key(),
        merchant_path=str(merchant_path),
        platform=platform,
        cert_path=str(cert_path),
        public_key=public_key,
        public_path=str(public_path),
    )


@pytest.fixture
def config(key_files):
    return Settings(
        _env_file=None,
        pay_mode="wechat",
        wx_mini_app_id=APP_ID,
        public_base_url="https://example.com",
        wxpay_mch_id=MCH_ID,
        wxpay_api_v3_key=API_KEY,
        wxpay_cert_serial="ABC123",
        wxpay_private_key_path=key_files.merchant_path,
        wxpay_platform_cert_path=key_files.cert_path,
        wxpay_public_key_path=key_files.public_path,
        wxpay_public_key_id=KEY_ID,
    )


def _sign_headers(key, body, *, serial=KEY_ID, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = "response-nonce"
    message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body + b"\n"
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return {
        "Wechatpay-Serial": serial,
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce,
        "Wechatpay-Signature": base64.b64encode(signature).decode(),
        "Wechatpay-Signature-Type": ALGORITHM,
    }


def _signed_response(key_files, data=None, *, status=200):
    body = b"" if data is None else json.dumps(data).encode()
    return httpx.Response(status, content=body, headers=_sign_headers(key_files.public_key, body))


def _assert_signed_request(key_files, request):
    scheme, authorization = request.headers["Authorization"].split(" ", 1)
    assert scheme == ALGORITHM
    attributes = dict(field.split("=", 1) for field in authorization.split(","))
    attrs = {name: value.strip('"') for name, value in attributes.items()}
    assert attrs["mchid"] == MCH_ID
    assert attrs["serial_no"] == "ABC123"
    assert request.headers["Wechatpay-Serial"] == KEY_ID
    assert request.url.host == "api.mch.weixin.qq.com"
    message = (
        request.method.encode()
        + b"\n"
        + request.url.raw_path
        + f"\n{attrs['timestamp']}\n{attrs['nonce_str']}\n".encode()
        + request.content
        + b"\n"
    )
    key_files.merchant.verify(
        base64.b64decode(attrs["signature"]), message, padding.PKCS1v15(), hashes.SHA256()
    )


def _payment_payload(**overrides):
    return {
        "appid": APP_ID,
        "mchid": MCH_ID,
        "trade_state": "SUCCESS",
        "out_trade_no": TRADE_NO,
        "transaction_id": TRANSACTION_ID,
        "amount": {"total": 9900, "payer_total": 9800, "currency": "CNY"},
        **overrides,
    }


def _refund_payload(**overrides):
    return {
        "mchid": MCH_ID,
        "out_trade_no": TRADE_NO,
        "out_refund_no": REFUND_NO,
        "transaction_id": TRANSACTION_ID,
        "amount": {"total": 9900, "refund": 2500},
        **overrides,
    }


def _notify_body(kind, event, payload, *, api_key=API_KEY, aad=None):
    aad = kind if aad is None else aad
    nonce = b"cryptononce1"
    encrypted = AESGCM(api_key.encode()).encrypt(nonce, json.dumps(payload).encode(), aad.encode())
    return json.dumps(
        {
            "resource_type": "encrypt-resource",
            "event_type": event,
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "original_type": kind,
                "associated_data": aad,
                "nonce": nonce.decode(),
                "ciphertext": base64.b64encode(encrypted).decode(),
            },
        },
        indent=2,
    ).encode()


def test_jsapi_uses_signed_request_and_returns_signed_pay_params(config, key_files):
    expiry = datetime(2027, 1, 1, 12, tzinfo=UTC)

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/v3/pay/transactions/jsapi"
        _assert_signed_request(key_files, request)
        assert json.loads(request.content) == {
            "appid": APP_ID,
            "mchid": MCH_ID,
            "description": "证件照套餐",
            "out_trade_no": TRADE_NO,
            "notify_url": "https://example.com" + PAY_NOTIFY_PATH,
            "amount": {"total": 9900, "currency": "CNY"},
            "payer": {"openid": "fake-openid"},
            "time_expire": "2027-01-01T12:00:00+00:00",
        }
        return _signed_response(key_files, {"prepay_id": "wx_prepaid"})

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    params = pay.create_prepay(
        out_trade_no=TRADE_NO,
        amount_fen=9900,
        description="证件照套餐",
        openid="fake-openid",
        expire_at=expiry,
    )
    assert params["package"] == "prepay_id=wx_prepaid"
    assert params["signType"] == "RSA"
    message = f"{APP_ID}\n{params['timeStamp']}\n{params['nonceStr']}\n{params['package']}\n"
    key_files.merchant.verify(
        base64.b64decode(params["paySign"]), message.encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_query_signs_path_and_query_string_and_close_verifies_empty_response(config, key_files):
    def handler(request):
        _assert_signed_request(key_files, request)
        if request.method == "GET":
            assert request.url.raw_path.decode() == f"{ORDER_PATH}{TRADE_NO}?mchid={MCH_ID}"
            assert request.content == b""
            return _signed_response(key_files, _payment_payload())
        assert request.method == "POST"
        assert request.url.path == f"{ORDER_PATH}{TRADE_NO}/close"
        assert json.loads(request.content) == {"mchid": MCH_ID}
        return _signed_response(key_files, status=204)

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    result = pay.query_order(TRADE_NO)
    assert result.trade_state == "SUCCESS"
    assert result.payment.amount_fen == 9900
    pay.close_order(TRADE_NO)


@pytest.mark.parametrize(
    ("trade_state", "error_code"), [("CLOSED", None), ("SUCCESS", ErrorCode.ORDER_NOT_CANCELLABLE)]
)
def test_close_uses_query_when_result_uncertain(config, key_files, trade_state, error_code):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(204)  # 缺少签名，必须通过查单确认。
        return _signed_response(key_files, _payment_payload(trade_state=trade_state))

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    if error_code is None:
        pay.close_order(TRADE_NO)
    else:
        with pytest.raises(AppError) as exc:
            pay.close_order(TRADE_NO)
        assert exc.value.code == error_code


def test_query_rejects_modified_success_response(config, key_files):
    def handler(request):
        original = json.dumps(_payment_payload()).encode()
        return httpx.Response(
            200, content=original + b" ", headers=_sign_headers(key_files.public_key, original)
        )

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    with pytest.raises(AppError) as exc:
        pay.query_order(TRADE_NO)
    assert exc.value.code == ErrorCode.INTERNAL_ERROR


@pytest.mark.parametrize("signing_mode", ["platform", "public_key", "migration"])
def test_decrypt_payment_notify_with_certificate_or_public_key(config, key_files, signing_mode):
    if signing_mode == "public_key":
        config.wxpay_platform_cert_path = ""
    if signing_mode == "platform":
        config.wxpay_public_key_path = config.wxpay_public_key_id = ""
    body = _notify_body("transaction", "TRANSACTION.SUCCESS", _payment_payload(), aad="")
    if signing_mode == "public_key":
        headers = _sign_headers(key_files.public_key, body)
    else:
        headers = _sign_headers(key_files.platform, body, serial="ABCDEF")
    notify = WechatPay(config).parse_notify(headers, body)
    assert (notify.out_trade_no, notify.transaction_id, notify.amount_fen, notify.success) == (
        TRADE_NO,
        TRANSACTION_ID,
        9900,
        True,
    )


@pytest.mark.parametrize(
    "failure", ["serial", "expired", "future", "sigtest", "body", "unsigned", "algorithm"]
)
def test_rejects_untrusted_notifications(config, key_files, failure):
    body = _notify_body("transaction", "TRANSACTION.SUCCESS", _payment_payload())
    headers = _sign_headers(key_files.public_key, body)
    if failure == "serial":
        headers["Wechatpay-Serial"] = "PUB_KEY_ID_UNKNOWN"
    elif failure in ("expired", "future"):
        timestamp = int(time.time()) + (400 if failure == "future" else -400)
        headers = _sign_headers(key_files.public_key, body, timestamp=timestamp)
    elif failure == "sigtest":
        headers["Wechatpay-Signature"] = "WECHATPAY/SIGNTEST/test"
    elif failure == "body":
        body += b" "
    elif failure == "unsigned":
        headers.pop("Wechatpay-Signature")
    else:
        headers["Wechatpay-Signature-Type"] = "OTHER"
    with pytest.raises(AppError) as exc:
        WechatPay(config).parse_notify(headers, body)
    assert exc.value.code == ErrorCode.PAYMENT_SIGNATURE_INVALID


@pytest.mark.parametrize(
    ("payload", "api_key"),
    [
        (_payment_payload(), "b" * 32),
        (_payment_payload(appid="wrong"), API_KEY),
        (_payment_payload(mchid="wrong"), API_KEY),
        (_payment_payload(amount={"total": "9900", "currency": "CNY"}), API_KEY),
    ],
)
def test_rejects_signed_notifications_with_invalid_resources(config, key_files, payload, api_key):
    body = _notify_body("transaction", "TRANSACTION.SUCCESS", payload, api_key=api_key)
    with pytest.raises(AppError) as exc:
        WechatPay(config).parse_notify(_sign_headers(key_files.public_key, body), body)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_refund_acceptance_remains_pending_until_query(config, key_files):
    def handler(request):
        _assert_signed_request(key_files, request)
        if request.method == "POST":
            assert request.url.path == REFUND_PATH
            assert json.loads(request.content) == {
                "out_trade_no": TRADE_NO,
                "out_refund_no": REFUND_NO,
                "reason": "退款",
                "notify_url": "https://example.com" + REFUND_NOTIFY_PATH,
                "amount": {"refund": 2500, "total": 9900, "currency": "CNY"},
            }
        else:
            assert request.url.path == f"{REFUND_PATH}/{REFUND_NO}"
        return _signed_response(key_files, _refund_payload(status="SUCCESS"))

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    assert (
        pay.refund(
            out_trade_no=TRADE_NO, out_refund_no=REFUND_NO, refund_fen=2500, total_fen=9900, reason="退款"
        )
        == "pending"
    )
    result = pay.query_refund(REFUND_NO)
    assert (result.status, result.refund_fen, result.total_fen) == ("success", 2500, 9900)


def test_refund_timeout_retains_pending_and_missing_refund_can_be_retried(config):
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("response timed out")
        return httpx.Response(404, json={"code": "RESOURCE_NOT_EXISTS"})

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    assert (
        pay.refund(
            out_trade_no=TRADE_NO, out_refund_no=REFUND_NO, refund_fen=2500, total_fen=9900, reason="退款"
        )
        == "pending"
    )
    assert pay.query_refund(REFUND_NO) is None


@pytest.mark.parametrize(
    ("state", "status"), [("SUCCESS", "success"), ("CLOSED", "failed"), ("ABNORMAL", "pending")]
)
def test_refund_notification_validates_payload_and_event(config, key_files, state, status):
    payload = _refund_payload(refund_status=state)
    body = _notify_body("refund", f"REFUND.{state}", payload)
    pay = WechatPay(config)
    result = pay.parse_refund_notify(_sign_headers(key_files.public_key, body), body)
    assert (result.out_refund_no, result.status, result.refund_fen) == (REFUND_NO, status, 2500)

    wrong_merchant = _notify_body("refund", f"REFUND.{state}", {**payload, "mchid": "wrong"})
    with pytest.raises(AppError) as exc:
        pay.parse_refund_notify(_sign_headers(key_files.public_key, wrong_merchant), wrong_merchant)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_callback_routes_acknowledge_only_after_handling_raw_body(config, key_files, monkeypatch):
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.modules.orders import service
    from app.modules.orders.router import callback_router

    app = FastAPI()
    app.include_router(callback_router, prefix="/api/v1/callbacks")
    db = Mock()
    app.dependency_overrides[get_db] = lambda: db
    pay = WechatPay(config)
    mark_paid = Mock()
    monkeypatch.setattr(service, "get_payment", lambda: pay)
    monkeypatch.setattr(service, "mark_paid", mark_paid)
    payment_body = _notify_body("transaction", "TRANSACTION.SUCCESS", _payment_payload())
    headers = _sign_headers(key_files.public_key, payment_body)
    with TestClient(app) as client:
        response = client.post(PAY_NOTIFY_PATH, content=payment_body, headers=headers)
        assert response.status_code == 204
        assert response.content == b""
        mark_paid.assert_called_once()
        db.commit.assert_called_once()

        response = client.post(PAY_NOTIFY_PATH, content=payment_body + b" ", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"code": "FAIL", "message": "支付通知签名不正确"}

        refund_body = _notify_body("refund", "REFUND.SUCCESS", _refund_payload(refund_status="SUCCESS"))
        monkeypatch.setattr(service.repo, "refund_by_no", lambda db, number: None)
        response = client.post(
            REFUND_NOTIFY_PATH, content=refund_body, headers=_sign_headers(key_files.public_key, refund_body)
        )
        assert response.status_code == 404
        assert response.json() == {"code": "FAIL", "message": "退款单不存在"}
        db.commit.assert_called_once()
        assert db.rollback.call_count == 2


@pytest.mark.parametrize(("signed", "expected"), [(False, "pending"), (True, "failed")])
def test_only_verified_refund_rejection_releases_reservation(config, key_files, signed, expected):
    def handler(request):
        failure = {"code": "PARAM_ERROR"}
        if signed:
            return _signed_response(key_files, failure, status=400)
        return httpx.Response(400, json=failure)

    pay = WechatPay(config, transport=httpx.MockTransport(handler))
    assert (
        pay.refund(
            out_trade_no=TRADE_NO, out_refund_no=REFUND_NO, refund_fen=2500, total_fen=9900, reason="退款"
        )
        == expected
    )
