import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.utils import utcnow
from app.integrations.receipt_providers import get_provider
from app.models import Provider, ProviderCallback, ProviderSpec
from app.modules.receipts import poller, repo, service
from tests.receipts.helpers import (
    FAKE_IDCARD,
    PROVIDER_CODE,
    create_app,
    create_body,
    current_attempt,
    get_application,
    jpeg_bytes,
    make_world,
    quota_used,
)

_KEY = "test-real-receipt-key"
_SIGN = hashlib.md5(_KEY.encode()).hexdigest()
_ORDER_NO = "20260616083012000001"
_IMAGE_URL = "https://cdn.example/receipt.jpg?download=test-signed-value"
_ACK = {"data": {}, "code": 0, "msg": "同步完成"}
_BASE = "/api/v1/receipt-applications"


@pytest.fixture
def real_channel(client, db, monkeypatch):
    def setup(*, adapter="zheying", timeout=False):
        world = make_world(client, db)
        provider = db.scalar(select(Provider).where(Provider.code == PROVIDER_CODE))
        provider.adapter = adapter
        provider_spec = db.scalar(select(ProviderSpec).where(ProviderSpec.provider_id == provider.id))
        provider_spec.param_mapping = {"name": "text_name", "idcard": "text_idcard"}
        db.flush()

        monkeypatch.setattr(settings, "receipt_mode", "real")
        monkeypatch.setattr(settings, f"{adapter}_app_key", _KEY)
        monkeypatch.setattr(settings, "public_base_url", "https://api.example")
        calls = []

        def handle(request):
            form = parse_qs(request.content.decode())
            assert form.pop("key") == [_KEY]
            calls.append((request.url.path, form))
            if request.url.path == "/receipt/make":
                return httpx.Response(200, json={"code": 0, "data": {"pic_id": "713"}})
            if timeout:
                raise httpx.ReadTimeout("timeout")
            order_no = str(int(_ORDER_NO) + sum(path == "/receipt/submit" for path, _ in calls) - 1)
            return httpx.Response(200, json={"code": 0, "data": {"order_no": order_no}})

        provider_client = httpx.Client(transport=httpx.MockTransport(handle))
        monkeypatch.setattr(
            service,
            "get_provider",
            lambda adapter, code, **kwargs: get_provider(adapter, code, client=provider_client, **kwargs),
        )
        return world, provider_client, calls

    clients = []

    def channel(**kwargs):
        world, provider_client, calls = setup(**kwargs)
        clients.append(provider_client)
        return world, calls

    yield channel
    for provider_client in clients:
        provider_client.close()


def _nonce(calls):
    path, form = calls[-1]
    assert path == "/receipt/submit"
    callback = httpx.URL(form["notice_url"][0])
    assert callback.copy_with(query=None) == f"https://api.example/api/v1/callbacks/receipt/{PROVIDER_CODE}"
    return callback.params["nonce"]


def _callback(client, nonce, state, *, order_no=_ORDER_NO, code=PROVIDER_CODE, sign=_SIGN, **fields):
    return client.post(
        f"/api/v1/callbacks/receipt/{code}",
        params={"nonce": nonce} if nonce is not None else None,
        data={"order_no": order_no, "status": str(state), "sign": sign, **fields},
    )


@pytest.mark.parametrize("adapter", ["zheying", "qianweiyun"])
def test_submit_binds_digest_and_order_and_replays_idempotently(client, db, real_channel, adapter):
    world, calls = real_channel(adapter=adapter)
    headers = {**world.headers, "Idempotency-Key": "real-submit"}
    response = client.post(_BASE, headers=headers, json=create_body(world))
    assert response.status_code == 200, response.text
    attempt = current_attempt(db, response.json()["app_no"])
    assert attempt.provider_order_no == _ORDER_NO
    assert attempt.status == "submitted"
    nonce = _nonce(calls)
    assert attempt.request_payload[repo.CALLBACK_NONCE_HASH] == hashlib.sha256(nonce.encode()).hexdigest()
    assert nonce not in str(attempt.request_payload)
    assert FAKE_IDCARD not in str(attempt.request_payload)
    assert json.loads(calls[-1][1]["param"][0]) == {"text_name": "张三", "text_idcard": FAKE_IDCARD}

    again = client.post(_BASE, headers=headers, json=create_body(world))
    assert again.json() == response.json()
    assert [path for path, _ in calls] == ["/receipt/make", "/receipt/submit"]


def test_callback_rejects_wrong_nonce_order_signature_provider_and_source(
    client, db, monkeypatch, real_channel
):
    world, calls = real_channel()
    app_no = create_app(client, world)["app_no"]
    nonce = _nonce(calls)
    db.add(Provider(code="other-channel", name="其他通道", adapter="zheying", status="enabled"))
    db.commit()
    for response in (
        _callback(client, None, 2),
        _callback(client, nonce + "-wrong", 2),
        _callback(client, nonce, 2, order_no="OTHER-ORDER"),
        _callback(client, nonce, 2, code="other-channel"),
        _callback(client, nonce, 2, sign="bad"),
    ):
        assert response.status_code == 401
        assert response.json()["code"] == "CALLBACK_SIGNATURE_INVALID"

    monkeypatch.setattr(settings, "receipt_callback_ip_allowlist", " 127.0.0.0/24,2001:db8::/32 ")
    response = client.post(
        f"/api/v1/callbacks/receipt/{PROVIDER_CODE}",
        params={"nonce": nonce},
        data={"order_no": _ORDER_NO, "status": "2", "sign": _SIGN},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert response.status_code == 401
    assert current_attempt(db, app_no).status == "submitted"


def test_completed_callback_queues_image_and_records_logistics_once(client, db, monkeypatch, real_channel):
    world, calls = real_channel()
    app_no = create_app(client, world)["app_no"]
    nonce = _nonce(calls)
    attempt = current_attempt(db, app_no)
    for _ in range(2):
        response = _callback(client, nonce, 3, image_receipt=_IMAGE_URL)
        assert response.status_code == 200, response.text
        assert response.json() == _ACK
    app = get_application(db, app_no)
    assert app.status == "completed"
    assert app.receipt_file_id is None
    assert attempt.next_poll_at is not None

    logistics = [{"express_name": "快递", "express_no": "0000123"}]
    for _ in range(2):
        assert _callback(client, nonce, 4, logistics_info=json.dumps(logistics)).json() == _ACK
    assert _callback(client, nonce, -1, reject_msg="迟到的驳回").json() == _ACK
    assert app.status == "completed"

    callbacks = {
        event.event_status: event
        for event in db.scalars(select(ProviderCallback).where(ProviderCallback.attempt_id == attempt.id))
    }
    assert set(callbacks) == {"3", "4", "-1"}
    assert callbacks["4"].process_result == "applied"
    assert callbacks["4"].payload["logistics_info"] == logistics
    assert callbacks["-1"].process_result == "stale"
    assert _SIGN not in str(callbacks["3"].payload)
    assert nonce not in str(callbacks["3"].payload)
    assert _IMAGE_URL not in str(callbacks["3"].payload)

    downloads = []

    def download(url):
        downloads.append(url)
        if len(downloads) == 1:
            raise TimeoutError("下载超时")
        return jpeg_bytes(), "image/jpeg", "jpg"

    monkeypatch.setattr(poller.receipt_image, "download", download)
    assert poller.poll_due(db) == 0
    assert attempt.next_poll_at > utcnow()
    assert app.receipt_file_id is None
    attempt.next_poll_at = utcnow() - timedelta(seconds=1)
    db.flush()
    assert poller.poll_due(db) == 1
    assert downloads == [_IMAGE_URL, _IMAGE_URL]
    assert attempt.next_poll_at is None
    assert app.receipt_file_id
    assert client.get(f"{_BASE}/{app_no}", headers=world.headers).json()["receipt_url"]
    assert repo.RECEIPT_IMAGE_URL not in callbacks["3"].payload
    assert poller.poll_due(db) == 0


@pytest.mark.parametrize("timeout", [False, True])
def test_poller_stops_after_two_hours_and_accepts_late_callback(client, db, real_channel, timeout):
    world, calls = real_channel(timeout=timeout)
    app_no = create_app(client, world)["app_no"]
    nonce = _nonce(calls)
    attempt = current_attempt(db, app_no)
    old_time = utcnow() - timedelta(hours=2, seconds=1)
    if timeout:
        assert attempt.status == "unknown"
        assert attempt.provider_order_no is None and attempt.submitted_at is None
        attempt.created_at = old_time
    else:
        assert attempt.status == "submitted"
        attempt.submitted_at = old_time
    attempt.next_poll_at = old_time
    db.flush()

    assert poller.poll_due(db) == 1
    assert attempt.status == "unknown"
    assert attempt.request_payload[repo.MANUAL_REVIEW_REQUIRED] is True
    assert attempt.next_poll_at is None and attempt.finished_at is None
    app = get_application(db, app_no)
    assert app.status == "processing"
    assert quota_used(db, app.entitlement_id) == 1

    assert _callback(client, nonce, 2).json() == _ACK
    assert attempt.provider_order_no == _ORDER_NO
    assert attempt.status == "unknown" and attempt.next_poll_at is None
    assert _callback(client, nonce, -1, reject_msg="背景不均匀").json() == _ACK
    assert get_application(db, app_no).status == "rejected"
    assert attempt.status == "rejected"
    assert repo.MANUAL_REVIEW_REQUIRED not in attempt.request_payload


def test_resubmit_mints_new_nonce_and_old_order_cannot_update_new_attempt(client, db, real_channel):
    world, calls = real_channel()
    app_no = create_app(client, world)["app_no"]
    old_nonce = _nonce(calls)
    assert _callback(client, old_nonce, -1).json() == _ACK
    response = client.post(f"{_BASE}/{app_no}/resubmit", headers=world.headers, json={})
    assert response.status_code == 200, response.text
    new_nonce = _nonce(calls)
    assert old_nonce != new_nonce
    assert _callback(client, new_nonce, 2).status_code == 401
    assert _callback(client, old_nonce, 3, image_receipt=_IMAGE_URL).json() == _ACK
    assert current_attempt(db, app_no).status == "submitted"
    assert get_application(db, app_no).status == "processing"
