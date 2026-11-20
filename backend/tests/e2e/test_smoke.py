"""证件照、回执和后台退款的端到端冒烟测试。"""

import io
import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.utils import utcnow
from app.integrations import storage
from app.integrations.receipt_providers.fake import sign_fake_callback
from app.models import File, NotifyTask, Order, Payment, Photo
from app.workers import runner
from tests.admin.helpers import PASSWORD, make_admin
from tests.factories import make_plan, make_provider_for, make_spec
from tests.photos.helpers import upload
from tests.receipts.helpers import FAKE_IDCARD, current_attempt, get_application

API = "/api/v1"
ADMIN = f"{API}/admin"


def _ok(response: Response):
    assert response.status_code == 200, f"{response.request.method} {response.request.url.path}"
    return response.json()


def _assert_image(client: TestClient, url: str, mime: str, size: tuple[int, int]) -> None:
    response = client.get(url)
    assert response.status_code == 200, "签名图片链接无法访问"
    assert response.headers["content-type"] == mime
    with Image.open(io.BytesIO(response.content)) as image:
        image.load()
        assert image.size == size


@pytest.fixture
def fake_services(monkeypatch, tmp_path, caplog):
    # 微信、支付和回执的 fake 模式由 tests/conftest.py 设置。
    monkeypatch.setattr(settings, "matting_mode", "fake")
    monkeypatch.setattr(settings, "notify_channels", "mini_subscribe")
    monkeypatch.setattr(settings, "mini_subscribe_mode", "fake")
    monkeypatch.setattr(settings, "mini_subscribe_templates", {})
    monkeypatch.setattr(storage, "_local", storage.LocalStorage(str(tmp_path)))
    caplog.set_level(logging.WARNING, logger="httpx")


def _run_worker(
    client: TestClient,
    db: Session,
    caplog: pytest.LogCaptureFixture,
    headers: dict[str, str],
    purchase: dict,
    app_no: str,
    entitlement_id: int,
) -> None:
    # 造出真实待处理记录，无需等待订单和上传自然过期。
    unpaid = _ok(client.post(f"{API}/orders", headers=headers, json=purchase))
    assert unpaid["status"] == "pending"
    order = db.scalars(select(Order).where(Order.order_no == unpaid["order_no"])).one()
    orphan_upload = _ok(upload(client, headers))
    orphan = db.get(File, orphan_upload["file_id"])
    assert orphan is not None and orphan.status == "active"
    assert storage.get_storage().get(orphan.storage_key)
    order.expire_at = utcnow() - timedelta(minutes=1)
    orphan.created_at = utcnow() - timedelta(days=2)
    db.commit()

    application_id = get_application(db, app_no).id
    task = db.scalars(
        select(NotifyTask).where(
            NotifyTask.application_id == application_id, NotifyTask.event == "receipt_completed"
        )
    ).one()
    assert task.status == "pending"
    with caplog.at_level(logging.ERROR, logger=runner.__name__):
        runner.run_once(db)
    assert not [record.getMessage() for record in caplog.records if record.name == runner.__name__]

    db.refresh(task)
    assert task.status == "sent" and task.sent_at is not None
    assert task.result == {"mode": "fake"}
    db.refresh(order)
    payment_status = db.scalars(select(Payment.status).where(Payment.order_id == order.id)).one()
    assert (order.status, payment_status) == ("closed", "closed")
    reminder = db.scalars(
        select(NotifyTask).where(
            NotifyTask.entitlement_id == entitlement_id, NotifyTask.event == "entitlement_expiring"
        )
    ).one()
    assert (reminder.step, reminder.status) == (7, "pending")
    db.refresh(orphan)
    assert orphan.status == "purged" and orphan.purged_at is not None
    with pytest.raises(FileNotFoundError):
        storage.get_storage().get(orphan.storage_key)


def test_photo_receipt_renewal_and_refund(
    client: TestClient, db: Session, fake_services, caplog: pytest.LogCaptureFixture
):
    spec = make_spec(db, "t015_idcard")
    provider = make_provider_for(db, spec, "t015_zheying")
    # 七天保管期让新权益进入 worker 的七天提醒窗口。
    plan = make_plan(
        db, "t015_photo", 3990, {"storage_days": 7, "photo_scope": 1, "receipt_quota": 1, "spec_change": 1}
    )
    dimensions = (spec.width_px, spec.height_px)

    login = _ok(client.post(f"{API}/auth/wechat-mini/login", json={"code": "dev:t015-smoke"}))
    user_id = login["user"]["id"]
    assert user_id > 0 and login["user"]["is_new"] is True
    assert datetime.fromisoformat(login["expires_at"]) > utcnow()
    headers = {"Authorization": f"Bearer {login['token']}"}
    profile = _ok(client.post(f"{API}/me/phone", headers=headers, json={"code": "phone:13800001234"}))
    assert profile["id"] == user_id and profile["has_phone"] is True
    if profile["phone_masked"] != "138****1234":
        pytest.fail("绑定后手机号脱敏结果异常")

    uploaded = _ok(upload(client, headers))
    assert (uploaded["width"], uploaded["height"]) == (600, 800)
    created = _ok(
        client.post(
            f"{API}/photos", headers=headers, json={"file_id": uploaded["file_id"], "source": "upload"}
        )
    )
    photo_id = created["id"]
    photo_url = f"{API}/photos/{photo_id}"
    assert (created["status"], created["source"]) == ("active", "upload")
    assert created["access"]["active"] is False
    _assert_image(client, created["original_url"], "image/jpeg", (600, 800))
    photo = db.get(Photo, photo_id)
    assert photo.original_file_id == uploaded["file_id"] and photo.check_result == {"status": "passed"}
    assert photo.matting_file_id is not None
    matte = db.get(File, photo.matting_file_id)
    assert (matte.kind, matte.mime) == ("matting", "image/png")
    with Image.open(io.BytesIO(storage.get_storage().get(matte.storage_key))) as image:
        assert image.mode == "RGBA" and image.getchannel("A").getextrema() == (0, 0)

    render_body = {"spec_code": spec.code, "bg_color": "#438EDB"}
    preview = _ok(client.post(f"{photo_url}/renders", headers=headers, json=render_body))
    assert preview["watermarked"] is True and preview["spec_code"] == spec.code
    assert preview["bg_color"] == render_body["bg_color"]
    assert (preview["width_px"], preview["height_px"]) == dimensions
    _assert_image(client, preview["preview_url"], "image/jpeg", dimensions)

    plans = _ok(client.get(f"{API}/plans"))
    offered = next(item for item in plans if item["code"] == plan.code)
    assert offered["price_fen"] == plan.price_fen
    assert offered["benefits"]["receipt_quota"] == 1 and offered["benefits"]["storage_days"] == 7
    purchase = {"plan_code": offered["code"], "photo_id": photo_id}
    order_headers = {**headers, "Idempotency-Key": "t015-initial-order"}
    order = _ok(client.post(f"{API}/orders", headers=order_headers, json=purchase))
    order_no = order["order_no"]
    assert order["status"] == "pending" and order["total_fen"] == plan.price_fen
    assert order["paid_fen"] == 0 and order["pay_params"]["mode"] == "fake"
    assert order["pay_params"]["amount_fen"] == plan.price_fen
    assert _ok(client.post(f"{API}/orders", headers=order_headers, json=purchase)) == order

    paid = _ok(client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=headers))
    assert (paid["order_no"], paid["status"], paid["paid_fen"]) == (order_no, "paid", plan.price_fen)
    assert paid["paid_at"]
    (entitlement,) = _ok(client.get(f"{API}/entitlements", headers=headers))["items"]
    entitlement_id = entitlement["id"]
    entitlement_url = f"{API}/entitlements/{entitlement_id}"
    ends_at = datetime.fromisoformat(entitlement["ends_at"])
    assert ends_at == datetime.fromisoformat(paid["paid_at"]) + timedelta(days=7)
    assert (entitlement["plan_code"], entitlement["photo_id"]) == (plan.code, photo_id)
    assert entitlement["is_active"] and entitlement["can_renew"] and entitlement["receipt_quota_left"] == 1
    detail = _ok(client.get(photo_url, headers=headers))
    assert detail["access"]["active"] and detail["access"]["access_until"] == entitlement["ends_at"]

    render = _ok(client.post(f"{photo_url}/renders", headers=headers, json=render_body))
    assert render["watermarked"] is False and render["id"] != preview["id"]
    download = _ok(client.get(f"{photo_url}/renders/{render['id']}/download", headers=headers))
    assert datetime.fromisoformat(download["expires_at"]) > utcnow()
    _assert_image(client, download["url"], "image/jpeg", dimensions)

    templates = _ok(client.get(f"{API}/notify/templates", headers=headers))
    template_id = next(item["template_id"] for item in templates if item["event"] == "receipt_completed")
    subscriptions = f"{API}/notify/subscriptions"
    assert _ok(client.post(subscriptions, headers=headers, json={"accepted": [template_id]})) == {
        "quota": {template_id: 1}
    }
    receipt_path = f"{API}/receipt-applications"
    application = _ok(
        client.post(
            receipt_path,
            headers={**headers, "Idempotency-Key": "t015-receipt"},
            json={
                "photo_id": photo_id,
                "spec_code": spec.code,
                "form": {"name": "张三", "idcard": FAKE_IDCARD},
            },
        )
    )
    app_no = application["app_no"]
    assert (application["photo_id"], application["spec_code"]) == (photo_id, spec.code)
    assert application["entitlement_id"] == entitlement_id
    assert application["status"] == "processing"
    if application["receipt_url"] is not None:
        pytest.fail("办理中的申请已返回回执链接")
    if application["form_masked"]["idcard"] != "110***********0019":
        pytest.fail("回执表单身份证号脱敏结果异常")
    (attempt,) = application["attempts"]
    assert attempt["status"] == "submitted"
    provider_order_no = current_attempt(db, app_no).provider_order_no
    assert provider_order_no.startswith("FAKE-")
    callback = json.dumps({"provider_order_no": provider_order_no, "result": "completed"}).encode()
    assert _ok(
        client.post(
            f"{API}/callbacks/receipt/{provider.code}",
            content=callback,
            headers={"X-Fake-Signature": sign_fake_callback(callback), "Content-Type": "application/json"},
        )
    ) == {"ok": True}
    completed = _ok(client.get(f"{receipt_path}/{app_no}", headers=headers))
    assert completed["status"] == "completed" and completed["attempts"][0]["status"] == "completed"
    assert completed["completed_at"] and completed["image_code"]
    _assert_image(client, completed["receipt_url"], "image/png", (600, 400))
    assert _ok(client.get(entitlement_url, headers=headers))["receipt_quota_left"] == 0

    _run_worker(client, db, caplog, headers, purchase, app_no, entitlement_id)
    assert _ok(client.post(subscriptions, headers=headers, json={"accepted": []})) == {
        "quota": {template_id: 0}
    }

    renewal = _ok(
        client.post(
            f"{API}/orders",
            headers={**headers, "Idempotency-Key": "t015-renewal"},
            json={"plan_code": plan.code, "renew_entitlement_id": entitlement_id},
        )
    )
    renewal_no = renewal["order_no"]
    assert renewal_no != order_no and renewal["status"] == "pending"
    (renewal_item,) = renewal["items"]
    assert (renewal_item["item_type"], renewal_item["photo_id"]) == ("renew", photo_id)
    renewal_paid = _ok(client.post(f"{API}/dev/orders/{renewal_no}/simulate-paid", headers=headers))
    assert (renewal_paid["status"], renewal_paid["paid_fen"]) == ("paid", plan.price_fen)
    (renewed,) = _ok(client.get(f"{API}/entitlements", headers=headers))["items"]
    assert renewed["id"] == entitlement_id and renewed["receipt_quota_used"] == 1
    assert datetime.fromisoformat(renewed["ends_at"]) == ends_at + timedelta(days=7)

    admin = make_admin(db, "t015_owner", "owner")
    signed_in = _ok(
        client.post(f"{ADMIN}/auth/login", json={"username": admin.username, "password": PASSWORD})
    )
    assert signed_in["admin"] == {"id": admin.id, "username": admin.username, "role": "owner"}
    (admin_order,) = _ok(client.get(f"{ADMIN}/orders", params={"order_no": order_no}))["items"]
    assert (admin_order["order_no"], admin_order["user_id"], admin_order["status"]) == (
        order_no,
        user_id,
        "paid",
    )
    admin_order_url = f"{ADMIN}/orders/{order_no}"
    order_detail = _ok(client.get(admin_order_url))
    (payment,) = order_detail["payments"]
    assert payment["status"] == "success" and payment["out_trade_no"] == order["pay_params"]["out_trade_no"]
    (admin_receipt,) = _ok(client.get(f"{ADMIN}/receipt-applications", params={"app_no": app_no}))["items"]
    assert (admin_receipt["app_no"], admin_receipt["user_id"], admin_receipt["status"]) == (
        app_no,
        user_id,
        "completed",
    )
    admin_receipt_detail = _ok(client.get(f"{ADMIN}/receipt-applications/{app_no}"))
    assert admin_receipt_detail["image_code"] == completed["image_code"]
    assert admin_receipt_detail["attempts"][0]["provider_code"] == provider.code
    overview = _ok(client.get(f"{ADMIN}/stats/overview"))
    assert (overview["user_count"], overview["order_count"], overview["paid_order_count"]) == (1, 3, 2)
    assert overview["paid_total_fen"] == plan.price_fen * 2
    assert overview["receipt_count"] == overview["receipt_counts_by_status"]["completed"] == 1

    request_id = uuid4()
    refund_body = {"request_id": str(request_id), "amount_fen": plan.price_fen, "reason": "冒烟测试退款"}
    csrf = {"X-CSRF-Token": signed_in["csrf_token"]}
    refund_url = f"{admin_order_url}/refunds"
    refund = _ok(client.post(refund_url, headers=csrf, json=refund_body))
    assert (refund["status"], refund["order_status"]) == ("success", "refunded")
    assert refund["order_no"] == order_no and refund["out_refund_no"] == f"RA{request_id.hex}"
    assert refund["order_refunded_fen"] == plan.price_fen and refund["operator"] == admin.username
    assert _ok(client.post(refund_url, headers=csrf, json=refund_body)) == refund
    refunded = _ok(client.get(admin_order_url))
    assert (refunded["status"], refunded["refunded_fen"]) == ("refunded", plan.price_fen)
    (recorded_refund,) = refunded["refunds"]
    assert recorded_refund["out_refund_no"] == refund["out_refund_no"]
    revoked = _ok(client.get(entitlement_url, headers=headers))
    assert revoked["is_active"] is False and revoked["can_renew"] is False

    logs = _ok(client.get(f"{ADMIN}/audit-logs", params={"admin_id": admin.id, "action": "refund.create"}))
    (audit,) = logs["items"]
    original_order_id = db.scalars(select(Order.id).where(Order.order_no == order_no)).one()
    assert (audit["admin_username"], audit["target_type"], audit["target_id"]) == (
        admin.username,
        "order",
        original_order_id,
    )
    assert audit["before"]["status"] == "paid" and audit["before"]["refunded_fen"] == 0
    assert audit["after"]["status"] == "refunded" and audit["after"]["refunded_fen"] == plan.price_fen
    assert audit["after"]["out_refund_no"] == refund["out_refund_no"]
