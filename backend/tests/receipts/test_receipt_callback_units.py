import io
import logging
import socket
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.core.schemas import OkResponse
from app.core.utils import utcnow
from app.models import ReceiptAttempt
from app.modules.receipts import poller, receipt_image, repo, service
from app.modules.receipts.router import _ReceiptAccessLogFilter, callback_router
from app.modules.receipts.schemas import ReceiptProviderAck


@pytest.mark.parametrize(
    ("reply", "expected"),
    [(ReceiptProviderAck(), {"data": {}, "code": 0, "msg": "同步完成"}), (OkResponse(), {"ok": True})],
)
def test_route_serializes_provider_replies_and_accepts_single_nonce(monkeypatch, reply, expected):
    calls = []

    def handle_callback(db, **kwargs):
        calls.append(kwargs)
        return reply

    monkeypatch.setattr(service, "handle_callback", handle_callback)
    app = FastAPI()
    app.dependency_overrides[get_db] = object
    app.include_router(callback_router)
    with TestClient(app) as client:
        first = client.post("/receipt/example", params={"nonce": "one"}, content=b"status=2")
        duplicate = client.post("/receipt/example?nonce=one&nonce=two", content=b"status=2")

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json() == expected
    assert [call["nonce"] for call in calls] == ["one", None]
    assert calls[0]["body"] == b"status=2"


def test_access_log_strips_receipt_callback_query_string():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:4321", "POST", "/api/v1/callbacks/receipt/example?nonce=sensitive", "1.1", 200),
        None,
    )
    assert _ReceiptAccessLogFilter().filter(record)
    assert "POST /api/v1/callbacks/receipt/example HTTP/1.1" in record.getMessage()
    assert "sensitive" not in record.getMessage()


def test_callback_allowlist_supports_addresses_and_cidrs(monkeypatch):
    monkeypatch.setattr(settings, "receipt_callback_ip_allowlist", " 192.0.2.7, 2001:db8::/32 ")
    service._check_callback_ip("192.0.2.7")
    service._check_callback_ip("2001:db8::1")
    for rejected in ("192.0.2.8", None):
        with pytest.raises(AppError) as caught:
            service._check_callback_ip(rejected)
        assert caught.value.code == ErrorCode.CALLBACK_SIGNATURE_INVALID


@pytest.mark.parametrize("minutes_old", [119, 120])
def test_order_number_unavailable_reschedules_until_deadline(monkeypatch, minutes_old):
    now = utcnow()
    monkeypatch.setattr(poller, "utcnow", lambda: now)
    monkeypatch.setattr(settings, "receipt_mode", "real")
    attempt = ReceiptAttempt(status="unknown", created_at=now - timedelta(minutes=minutes_old))
    poller._poll_status(MagicMock(), attempt)
    if minutes_old == 120:
        assert attempt.next_poll_at is None
        assert attempt.request_payload[repo.MANUAL_REVIEW_REQUIRED] is True
    else:
        assert attempt.next_poll_at == now + timedelta(minutes=1)
        assert attempt.request_payload is None


def test_query_timeout_after_deadline_marks_manual_review(monkeypatch):
    monkeypatch.setattr(settings, "receipt_mode", "real")
    adapter = MagicMock()
    adapter.query.side_effect = TimeoutError
    monkeypatch.setattr(poller, "get_provider", lambda *args: adapter)
    attempt = ReceiptAttempt(
        status="submitted", provider_order_no="example", submitted_at=utcnow() - timedelta(hours=3)
    )

    poller._poll_status(MagicMock(), attempt)

    assert attempt.next_poll_at is None
    assert attempt.status == "unknown"
    assert attempt.request_payload[repo.MANUAL_REVIEW_REQUIRED] is True


def test_receipt_image_download_pins_public_address_and_detects_real_mime(monkeypatch):
    def addresses(*args, **kwargs):
        return [
            (socket.AF_INET, None, None, None, ("127.0.0.1", 443)),
            (socket.AF_INET, None, None, None, ("8.8.8.8", 443)),
        ]

    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    conn = MagicMock()
    response = conn.getresponse.return_value.__enter__.return_value
    response.status = 200
    response.read.return_value = buf.getvalue()
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(receipt_image.socket, "getaddrinfo", addresses)
    monkeypatch.setattr(receipt_image, "_ReceiptImageConnection", connect)

    assert receipt_image.download("https://cdn.example/a.jpg?query=example") == (
        buf.getvalue(),
        "image/png",
        "png",
    )
    connect.assert_called_once_with("cdn.example", "8.8.8.8")
    conn.request.assert_called_once_with("GET", "/a.jpg?query=example")
    conn.close.assert_called_once()


@pytest.mark.parametrize(
    "url",
    ["https://192.168.0.5/test.jpg", "https://[::1]/test.jpg", "http://cdn.example/test.jpg"],
)
def test_receipt_image_rejects_private_addresses_and_unencrypted_urls(monkeypatch, url):
    connect = MagicMock()
    monkeypatch.setattr(receipt_image, "_ReceiptImageConnection", connect)
    with pytest.raises(ValueError, match="回执图片地址"):
        receipt_image.download(url)
    connect.assert_not_called()
