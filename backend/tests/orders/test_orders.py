import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError, ErrorCode
from app.core.idempotency import _hash
from app.core.utils import utcnow
from app.integrations.payment import FakePay, OrderQuery, PayNotify, RefundResult, sign_fake_notify
from app.models import (
    Entitlement,
    EntitlementQuota,
    IdempotencyKey,
    Order,
    OrderItem,
    Payment,
    PlanBenefit,
    Refund,
)
from app.modules.orders import service
from tests.conftest import login
from tests.factories import make_plan, make_standard_plans
from tests.orders.helpers import grant_plan, latest_user_id, make_photo

API = "/api/v1"


def _buy(client, headers, plan_code, **body):
    r = client.post(f"{API}/orders", json={"plan_code": plan_code, **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _setup(client, db, code="dev:alice"):
    make_standard_plans(db)
    h = login(client, code)
    return h, latest_user_id(db)


def test_plans_list_public(client, db):
    make_standard_plans(db)
    make_plan(db, "hidden_plan", 100, {}, status="off_sale")
    r = client.get(f"{API}/plans")
    assert r.status_code == 200
    plans = {p["code"]: p for p in r.json()}
    assert set(plans) == {"single_19_9", "photo_year_39_9", "addon_receipt_10", "unlimited_99"}
    assert plans["photo_year_39_9"]["price_fen"] == 3990
    assert plans["photo_year_39_9"]["benefits"]["spec_change"] == 1
    assert plans["addon_receipt_10"]["benefits"]["storage_days"] == 0
    assert plans["addon_receipt_10"]["benefits"]["attach_to_parent"] == 1


def test_create_requires_login(client, db):
    make_standard_plans(db)
    r = client.post(f"{API}/orders", json={"plan_code": "unlimited_99"})
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_buy_39_9_then_simulate_paid(client, db):
    h, uid = _setup(client, db)
    photo = make_photo(db, uid)

    created = _buy(client, h, "photo_year_39_9", photo_id=photo.id)
    assert created["status"] == "pending"
    assert created["total_fen"] == 3990
    assert created["pay_params"]["mode"] == "fake"
    assert created["items"][0]["photo_id"] == photo.id
    assert client.get(f"{API}/entitlements", headers=h).json() == []

    r = client.post(f"{API}/dev/orders/{created['order_no']}/simulate-paid", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"
    assert r.json()["paid_fen"] == 3990

    ents = client.get(f"{API}/entitlements", headers=h).json()
    assert len(ents) == 1
    ent = ents[0]
    assert ent["photo_id"] == photo.id
    assert ent["plan_code"] == "photo_year_39_9"
    assert ent["receipt_quota_total"] == 1
    assert ent["receipt_quota_left"] == 1
    assert ent["spec_change"] is True
    assert ent["is_active"] is True
    db.refresh(photo)
    assert photo.access_until is not None


def test_photo_required_for_single_plan(client, db):
    h, _ = _setup(client, db)
    r = client.post(f"{API}/orders", json={"plan_code": "photo_year_39_9"}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_other_users_photo_rejected(client, db):
    h, _ = _setup(client, db)
    login(client, "dev:bob")
    bob_photo = make_photo(db, latest_user_id(db))
    r = client.post(
        f"{API}/orders", json={"plan_code": "photo_year_39_9", "photo_id": bob_photo.id}, headers=h
    )
    assert r.status_code == 404
    assert r.json()["code"] == "PHOTO_NOT_FOUND"


def test_plan_not_available(client, db):
    h, _ = _setup(client, db)
    make_plan(db, "old_plan", 500, {"storage_days": 1}, status="off_sale")
    r = client.post(f"{API}/orders", json={"plan_code": "old_plan"}, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "PLAN_NOT_AVAILABLE"
    r = client.post(f"{API}/orders", json={"plan_code": "no_such_plan"}, headers=h)
    assert r.json()["code"] == "PLAN_NOT_AVAILABLE"


def test_idempotency_key_same_request_same_order(client, db):
    h, _ = _setup(client, db)
    headers = {**h, "Idempotency-Key": "key-1"}
    body = {"plan_code": "unlimited_99"}
    a = client.post(f"{API}/orders", json=body, headers=headers)
    b = client.post(f"{API}/orders", json=body, headers=headers)
    assert a.status_code == b.status_code == 200
    assert a.json()["order_no"] == b.json()["order_no"]
    assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_idempotency_key_different_body_conflict(client, db):
    h, uid = _setup(client, db)
    p1, p2 = make_photo(db, uid), make_photo(db, uid)
    headers = {**h, "Idempotency-Key": "key-2"}
    a = client.post(
        f"{API}/orders", json={"plan_code": "photo_year_39_9", "photo_id": p1.id}, headers=headers
    )
    assert a.status_code == 200
    b = client.post(
        f"{API}/orders", json={"plan_code": "photo_year_39_9", "photo_id": p2.id}, headers=headers
    )
    assert b.status_code == 409
    assert b.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_order_replays_idempotency_record_created_before_renewal(client, db):
    headers, user_id = _setup(client, db)
    order = _buy(client, headers, "unlimited_99")
    db.add(
        IdempotencyKey(
            user_id=user_id,
            scope="orders.create",
            key="legacy-key",
            request_hash=_hash(
                {"plan_code": "unlimited_99", "photo_id": None, "parent_entitlement_id": None}
            ),
            response_status=200,
            response_body={k: v for k, v in order.items() if k != "refund_pending"},
        )
    )
    db.flush()

    retry = _buy(client, {**headers, "Idempotency-Key": "legacy-key"}, "unlimited_99")
    assert retry == order
    assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_simulate_paid_twice_is_idempotent(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    url = f"{API}/dev/orders/{order_no}/simulate-paid"
    assert client.post(url, headers=h).status_code == 200
    r = client.post(url, headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "paid"
    assert db.scalar(select(func.count()).select_from(Entitlement)) == 1


def test_cancel_pending_order(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    r = client.post(f"{API}/orders/{order_no}/cancel", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    pay = db.scalar(select(Payment))
    assert pay.status == "closed"
    # 再取消、再支付都不行
    r = client.post(f"{API}/orders/{order_no}/cancel", headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_CANCELLABLE"
    r = client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_PAYABLE"


def test_cannot_cancel_paid_order(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=h)
    r = client.post(f"{API}/orders/{order_no}/cancel", headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_CANCELLABLE"


def test_other_users_order_is_404(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    bob = login(client, "dev:bob")
    for method, url in [
        ("get", f"{API}/orders/{order_no}"),
        ("post", f"{API}/orders/{order_no}/cancel"),
        ("post", f"{API}/dev/orders/{order_no}/simulate-paid"),
    ]:
        r = getattr(client, method)(url, headers=bob)
        assert r.status_code == 404, url
        assert r.json()["code"] == "ORDER_NOT_FOUND"
    assert client.get(f"{API}/orders", headers=bob).json()["items"] == []


def _notify_body(db, order_no, *, amount_fen, transaction_id="WX123"):
    order = db.scalar(select(Order).where(Order.order_no == order_no))
    pay = db.scalar(select(Payment).where(Payment.order_id == order.id))
    return json.dumps(
        {
            "out_trade_no": pay.out_trade_no,
            "transaction_id": transaction_id,
            "amount_fen": amount_fen,
            "success": True,
        }
    ).encode()


def test_wxpay_callback_bad_signature(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    body = _notify_body(db, order_no, amount_fen=9900)
    r = client.post(f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": "bad"})
    assert r.status_code == 401
    assert r.json() == {"code": "FAIL", "message": "支付通知签名不正确"}
    assert client.get(f"{API}/orders/{order_no}", headers=h).json()["status"] == "pending"


def test_wxpay_callback_marks_paid_and_is_idempotent(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    body = _notify_body(db, order_no, amount_fen=9900)
    headers = {"X-Fake-Signature": sign_fake_notify(body), "Content-Type": "application/json"}
    for _ in range(2):
        r = client.post(f"{API}/callbacks/wxpay", content=body, headers=headers)
        assert r.status_code == 204, r.text
        assert r.content == b""
    assert client.get(f"{API}/orders/{order_no}", headers=h).json()["status"] == "paid"
    assert len(client.get(f"{API}/entitlements", headers=h).json()) == 1


@pytest.mark.parametrize(("refund_status", "order_status"), [("success", "refunded"), ("pending", "closed")])
def test_wxpay_callback_for_closed_order_refunds_once(
    client, db, monkeypatch, caplog, refund_status, order_status
):
    h, _ = _setup(client, db)
    order = _buy(client, h, "unlimited_99")
    order_no = order["order_no"]
    cancelled = client.post(f"{API}/orders/{order_no}/cancel", headers=h)
    assert cancelled.json()["status"] == "closed"
    calls = []

    def refund(self, **kwargs):
        calls.append(kwargs)
        return refund_status

    monkeypatch.setattr(FakePay, "refund", refund)
    body = _notify_body(db, order_no, amount_fen=9900)
    headers = {"X-Fake-Signature": sign_fake_notify(body)}
    for _ in range(2):
        r = client.post(f"{API}/callbacks/wxpay", content=body, headers=headers)
        assert r.status_code == 204, r.text
        assert r.content == b""

    detail = client.get(f"{API}/orders/{order_no}", headers=h).json()
    assert detail["status"] == order_status and detail["paid_fen"] == 9900
    assert detail["refunded_fen"] == (9900 if refund_status == "success" else 0)
    assert client.get(f"{API}/entitlements", headers=h).json() == []
    payment = db.scalars(select(Payment)).one()
    assert payment.status == "success" and payment.transaction_id == "WX123"
    record = db.scalars(select(Refund)).one()
    assert (record.operator, record.status, record.amount_fen) == ("system", refund_status, 9900)
    assert len(calls) == 1
    assert calls[0]["out_refund_no"] == record.out_refund_no
    assert calls[0]["refund_fen"] == calls[0]["total_fen"] == 9900
    events = [r for r in caplog.records if r.name == "app.orders" and "refund.auto_closed_order" in r.message]
    assert len(events) == 1 and record.out_refund_no in events[0].message


def test_wxpay_callback_amount_mismatch(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    body = _notify_body(db, order_no, amount_fen=1)
    r = client.post(
        f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": sign_fake_notify(body)}
    )
    assert r.status_code == 409
    assert r.json() == {"code": "FAIL", "message": "支付金额与订单金额不一致"}
    assert client.get(f"{API}/orders/{order_no}", headers=h).json()["status"] == "pending"


def test_wxpay_callback_unknown_order(client, db):
    body = json.dumps({"out_trade_no": "P_NONE", "transaction_id": "T", "amount_fen": 100}).encode()
    r = client.post(
        f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": sign_fake_notify(body)}
    )
    assert r.status_code == 404
    assert r.json() == {"code": "FAIL", "message": "订单不存在"}


def test_unlimited_99_covers_all_photos(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=h)
    ent = client.get(f"{API}/entitlements", headers=h).json()[0]
    assert ent["photo_id"] is None
    assert ent["receipt_quota_total"] == 10
    assert ent["one_person"] is True
    paid_at = db.scalar(select(Order.paid_at))
    assert db.scalar(select(Entitlement.ends_at)) == paid_at + timedelta(days=365)


def test_addon_follows_parent(client, db):
    h, uid = _setup(client, db)
    photo = make_photo(db, uid)
    first = _buy(client, h, "photo_year_39_9", photo_id=photo.id)["order_no"]
    client.post(f"{API}/dev/orders/{first}/simulate-paid", headers=h)
    parent = client.get(f"{API}/entitlements", headers=h).json()[0]

    addon_no = _buy(client, h, "addon_receipt_10", parent_entitlement_id=parent["id"])["order_no"]
    detail = client.get(f"{API}/orders/{addon_no}", headers=h).json()
    assert detail["items"][0]["item_type"] == "addon"
    assert detail["items"][0]["photo_id"] == photo.id
    client.post(f"{API}/dev/orders/{addon_no}/simulate-paid", headers=h)

    ents = {e["plan_code"]: e for e in client.get(f"{API}/entitlements", headers=h).json()}
    assert set(ents) == {"photo_year_39_9", "addon_receipt_10"}
    assert ents["addon_receipt_10"]["ends_at"] == parent["ends_at"]
    assert ents["addon_receipt_10"]["photo_id"] == photo.id
    assert ents["addon_receipt_10"]["receipt_quota_total"] == 1


def test_addon_needs_valid_parent(client, db):
    h, _ = _setup(client, db)
    r = client.post(f"{API}/orders", json={"plan_code": "addon_receipt_10"}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"

    bob = login(client, "dev:bob")
    bob_no = _buy(client, bob, "unlimited_99")["order_no"]
    client.post(f"{API}/dev/orders/{bob_no}/simulate-paid", headers=bob)
    bob_ent = client.get(f"{API}/entitlements", headers=bob).json()[0]
    r = client.post(
        f"{API}/orders",
        json={"plan_code": "addon_receipt_10", "parent_entitlement_id": bob_ent["id"]},
        headers=h,
    )
    assert r.status_code == 404
    assert r.json()["code"] == "ENTITLEMENT_NOT_FOUND"


@pytest.mark.parametrize("already_expired", [False, True])
def test_renewal_extends_original_entitlement_once_using_checkout_snapshot(
    client, db, monkeypatch, already_expired
):
    plans = make_standard_plans(db)
    headers = login(client)
    user_id = latest_user_id(db)
    photo = make_photo(db, user_id)
    now = utcnow()
    original_paid_at = now - timedelta(days=370) if already_expired else now
    ent = grant_plan(db, user_id, plans["photo_year_39_9"], photo_id=photo.id, paid_at=original_paid_at)
    original_end = ent.ends_at
    if already_expired:
        ent.status = "expired"
    quota = db.scalar(select(EntitlementQuota).where(EntitlementQuota.entitlement_id == ent.id))
    quota.used = 1
    db.flush()
    monkeypatch.setattr(service, "utcnow", lambda: now)
    url = f"{API}/entitlements/{ent.id}"
    before = client.get(url, headers=headers).json()
    assert before["can_renew"] and before["is_active"] is not already_expired

    renewal_plan = make_plan(
        db, "renew_photo", 700, {"storage_days": 30, "photo_scope": 1, "receipt_quota": 5}
    )
    request_headers = {**headers, "Idempotency-Key": "renew-photo"}
    created = _buy(client, request_headers, renewal_plan.code, renew_entitlement_id=ent.id)
    assert created["items"][0]["item_type"] == "renew"
    assert created["items"][0]["photo_id"] == photo.id
    assert _buy(client, request_headers, renewal_plan.code, renew_entitlement_id=ent.id) == created

    storage = db.scalar(
        select(PlanBenefit).where(
            PlanBenefit.plan_id == renewal_plan.id, PlanBenefit.benefit_type == "storage_days"
        )
    )
    storage.int_value = 90
    db.flush()
    order_no = created["order_no"]
    body = _notify_body(db, order_no, amount_fen=700)
    for _ in range(2):
        response = client.post(
            f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": sign_fake_notify(body)}
        )
        assert response.status_code == 204, response.text

    db.refresh(ent)
    db.refresh(photo)
    db.refresh(quota)
    expected_end = max(now, original_end) + timedelta(days=30)
    assert ent.status == "active" and ent.starts_at == original_paid_at and ent.ends_at == expected_end
    assert ent.plan_id == plans["photo_year_39_9"].id
    assert photo.access_until == expected_end
    assert (quota.total, quota.used) == (1, 1)
    assert db.scalar(select(func.count()).select_from(Entitlement)) == 1
    assert client.get(url, headers=headers).json()["is_active"]
    order = client.get(f"{API}/orders/{order_no}", headers=headers).json()
    assert (order["status"], order["refund_pending"]) == ("paid", False)
    item = db.scalar(select(OrderItem).where(OrderItem.item_type == "renew"))
    assert item.snapshot["renew_entitlement_id"] == ent.id
    assert item.snapshot["renewal_ledger"] == {
        "storage_days": 30,
        "applied_at": now.isoformat(),
        "previous_ends_at": original_end.isoformat(),
        "ends_at": expected_end.isoformat(),
    }


def test_renewal_rejects_other_users_and_incompatible_plans(client, db):
    plans = make_standard_plans(db)
    headers = login(client)
    user_id = latest_user_id(db)
    target = grant_plan(db, user_id, plans["unlimited_99"])
    old = grant_plan(db, user_id, plans["unlimited_99"], paid_at=utcnow() - timedelta(days=396))
    revoked = grant_plan(db, user_id, plans["unlimited_99"])
    revoked.status = "revoked"
    addon = grant_plan(db, user_id, plans["addon_receipt_10"], parent_entitlement_id=target.id)
    other_headers = login(client, "dev:bob")
    no_storage = make_plan(db, "no_storage", 100, {"receipt_quota": 1})

    def renew(ent, plan, headers=headers, **kwargs):
        response = client.post(
            f"{API}/orders",
            headers=headers,
            json={"plan_code": plan, "renew_entitlement_id": ent.id, **kwargs},
        )
        return response.json()["code"]

    assert renew(target, "unlimited_99", headers=other_headers) == "ENTITLEMENT_NOT_FOUND"
    assert renew(target, "unlimited_99", parent_entitlement_id=target.id) == "VALIDATION_ERROR"
    assert renew(target, "unlimited_99", photo_id=1) == "VALIDATION_ERROR"
    for plan_code in ("addon_receipt_10", "photo_year_39_9", no_storage.code):
        assert renew(target, plan_code) == "PLAN_NOT_AVAILABLE"
    for ineligible in (old, revoked, addon):
        assert not client.get(f"{API}/entitlements/{ineligible.id}", headers=headers).json()["can_renew"]
        assert renew(ineligible, "unlimited_99") == "ENTITLEMENT_EXPIRED"


@pytest.mark.parametrize("parent_status", ["expired", "revoked"])
def test_invalid_addon_payment_starts_one_full_refund_and_audits(
    client, db, monkeypatch, caplog, parent_status
):
    plans = make_standard_plans(db)
    headers = login(client)
    user_id = latest_user_id(db)
    parent = grant_plan(db, user_id, plans["unlimited_99"], paid_at=utcnow() - timedelta(days=364))
    order_no = _buy(client, headers, "addon_receipt_10", parent_entitlement_id=parent.id)["order_no"]
    if parent_status == "expired":
        parent.ends_at = utcnow() - timedelta(seconds=1)
    else:
        parent.status = "revoked"
    db.flush()
    submissions = []

    def refund(**kwargs):
        submissions.append(kwargs)
        return "pending"

    gateway = SimpleNamespace(
        parse_notify=FakePay().parse_notify, refund=refund, query_refund=lambda out_refund_no: None
    )
    monkeypatch.setattr(service.settings, "pay_mode", "wechat")
    monkeypatch.setattr(service, "get_payment", lambda: gateway)
    body = _notify_body(db, order_no, amount_fen=1000)
    for _ in range(2):
        response = client.post(
            f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": sign_fake_notify(body)}
        )
        assert response.status_code == 204, response.text

    order = db.scalar(select(Order).where(Order.order_no == order_no))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    record = db.scalars(select(Refund)).one()
    request_id = uuid5(NAMESPACE_URL, f"idphone:payment:{payment.out_trade_no}:entitlement-unavailable")
    assert record.out_refund_no == f"RA{request_id.hex}"
    assert (record.operator, record.status, record.amount_fen) == ("system", "pending", 1000)
    assert submissions == []
    record.updated_at = utcnow() - timedelta(minutes=5)
    db.commit()
    assert service.poll_pending_refunds(db) == 0  # 已提交微信，仍等退款结果
    assert len(submissions) == 1 and submissions[0]["out_refund_no"] == record.out_refund_no
    assert submissions[0]["refund_fen"] == submissions[0]["total_fen"] == 1000
    events = [
        r
        for r in caplog.records
        if r.name == "app.orders" and "refund.auto_entitlement_unavailable" in r.message
    ]
    assert len(events) == 1 and record.out_refund_no in events[0].message
    assert db.scalars(select(Entitlement.id)).all() == [parent.id]
    assert payment.status == "success"

    detail_url = f"{API}/orders/{order_no}"
    detail = client.get(detail_url, headers=headers).json()
    assert (detail["status"], detail["refund_pending"], detail["refunded_fen"]) == ("paid", True, 0)
    result = RefundResult(
        payment.out_trade_no, record.out_refund_no, payment.transaction_id, 1000, 1000, "success"
    )
    gateway.parse_refund_notify = lambda headers, body: result
    for _ in range(2):
        assert client.post(f"{API}/callbacks/wxpay/refund").status_code == 204
    detail = client.get(detail_url, headers=headers).json()
    assert (detail["status"], detail["refund_pending"], detail["refunded_fen"]) == ("refunded", False, 1000)
    assert parent.status == ("active" if parent_status == "expired" else "revoked")


def test_renewal_payment_after_grace_period_is_refunded(client, db, monkeypatch):
    plans = make_standard_plans(db)
    headers = login(client)
    now = utcnow()
    parent = grant_plan(db, latest_user_id(db), plans["unlimited_99"], paid_at=now - timedelta(days=395))
    end = parent.ends_at
    monkeypatch.setattr(service, "utcnow", lambda: now)
    order_no = _buy(client, headers, "unlimited_99", renew_entitlement_id=parent.id)["order_no"]
    monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(seconds=1))

    response = client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "refunded"
    assert response.json()["refunded_fen"] == 9900
    db.refresh(parent)
    assert parent.ends_at == end
    item = db.scalar(select(OrderItem).where(OrderItem.item_type == "renew"))
    assert "renewal_ledger" not in item.snapshot


def test_pending_order_expires_on_read(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    order = db.scalar(select(Order).where(Order.order_no == order_no))
    order.expire_at = utcnow() - timedelta(minutes=1)
    db.flush()
    r = client.get(f"{API}/orders/{order_no}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert db.scalar(select(Payment.status)) == "closed"


def test_orders_list_cursor_pagination(client, db):
    h, _ = _setup(client, db)
    nos = [_buy(client, h, "unlimited_99")["order_no"] for _ in range(3)]
    p1 = client.get(f"{API}/orders", params={"limit": 2}, headers=h).json()
    assert [o["order_no"] for o in p1["items"]] == [nos[2], nos[1]]
    assert p1["next_cursor"]
    p2 = client.get(f"{API}/orders", params={"limit": 2, "cursor": p1["next_cursor"]}, headers=h).json()
    assert [o["order_no"] for o in p2["items"]] == [nos[0]]
    assert p2["next_cursor"] is None


def _buy_paid_and_enable_wechat(client, db, monkeypatch):
    headers, _ = _setup(client, db)
    order_no = _buy(client, headers, "unlimited_99")["order_no"]
    assert client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=headers).status_code == 200
    payment = db.scalars(select(Payment)).one()
    monkeypatch.setattr(service.settings, "pay_mode", "wechat")
    return order_no, payment


def test_wechat_refund_callback_applies_once_and_validates_local_payment(client, db, monkeypatch):
    order_no, payment = _buy_paid_and_enable_wechat(client, db, monkeypatch)
    submissions = []
    results = []

    def submit(**kwargs):
        submissions.append(kwargs)
        return "pending"

    gateway = SimpleNamespace(refund=submit, parse_refund_notify=lambda headers, body: results[-1])
    monkeypatch.setattr(service, "get_payment", lambda: gateway)
    request_id = uuid4()
    refund = service.refund_order(
        db, order_no=order_no, request_id=request_id, amount_fen=9900, reason="原申请", operator="admin"
    ).refund
    db.commit()
    assert refund.out_refund_no == f"RA{request_id.hex}"
    assert refund.status == "pending"
    assert db.scalar(select(Entitlement.status)) == "active"
    assert db.scalar(select(Order.refunded_fen)) == 0
    assert len(submissions) == 1

    with pytest.raises(AppError) as exc:
        service.refund_order(
            db, order_no=order_no, request_id=uuid4(), amount_fen=1, reason="超出余额", operator="admin"
        )
    assert exc.value.code == ErrorCode.REFUND_NOT_ALLOWED
    db.rollback()

    result = RefundResult(
        payment.out_trade_no, refund.out_refund_no, payment.transaction_id, 9900, 9900, "success"
    )
    results.append(replace(result, refund_fen=100))
    url = f"{API}/callbacks/wxpay/refund"
    response = client.post(url, content=b"notification")
    assert response.status_code == 409
    assert response.json() == {"code": "FAIL", "message": "微信退款结果与本地流水不一致"}
    assert db.scalar(select(Order.refunded_fen)) == 0

    for notice in (result, result, replace(result, status="failed")):
        results.append(notice)
        response = client.post(url, content=b"notification")
        assert response.status_code == 204
        assert response.content == b""
    assert db.scalar(select(Order.refunded_fen)) == 9900
    assert db.scalar(select(Order.status)) == "refunded"
    assert db.scalar(select(Entitlement.status)) == "revoked"
    assert refund.status == "success" and refund.finished_at is not None


def test_wechat_refund_query_retries_original_number_and_polls_terminal_state(client, db, monkeypatch):
    order_no, payment = _buy_paid_and_enable_wechat(client, db, monkeypatch)
    submissions = []
    queries = []

    def submit(**kwargs):
        submissions.append(kwargs)
        return "pending"

    def query(out_refund_no):
        queries.append(out_refund_no)
        if len(queries) == 1:
            return None
        return RefundResult(
            payment.out_trade_no, out_refund_no, payment.transaction_id, 2200, 9900, "success"
        )

    gateway = SimpleNamespace(refund=submit, query_refund=query)
    monkeypatch.setattr(service, "get_payment", lambda: gateway)
    request = dict(order_no=order_no, request_id=uuid4(), amount_fen=2200, reason="原申请", operator="admin")
    first = service.refund_order(db, **request)
    db.commit()
    replay = service.refund_order(db, **{**request, "reason": "修改原因"})
    assert replay.refund.id == first.refund.id
    assert replay.before is None
    assert replay.refund.status == "pending"
    assert len(submissions) == 2 and submissions[0] == submissions[1]
    assert queries == [first.refund.out_refund_no]
    replay.refund.updated_at = utcnow() - timedelta(minutes=5)
    db.commit()

    assert service.poll_pending_refunds(db) == 1
    assert replay.refund.status == "success"
    assert replay.order.status == "part_refunded"
    assert replay.order.refunded_fen == 2200
    assert db.scalar(select(Entitlement.status)) == "active"
    assert service.poll_pending_refunds(db) == 0
    assert queries == [first.refund.out_refund_no] * 2


def test_wechat_cancel_waits_for_remote_close_and_detail_can_recover_payment(client, db, monkeypatch):
    headers, _ = _setup(client, db)
    order_no = _buy(client, headers, "unlimited_99")["order_no"]
    payment = db.scalars(select(Payment)).one()
    monkeypatch.setattr(service.settings, "pay_mode", "wechat")

    def close(out_trade_no):
        assert out_trade_no == payment.out_trade_no
        raise AppError(ErrorCode.ORDER_NOT_CANCELLABLE)

    def query(out_trade_no):
        assert out_trade_no == payment.out_trade_no
        return OrderQuery("SUCCESS", PayNotify(out_trade_no, "WX123", 9900, True, {}))

    gateway = SimpleNamespace(close_order=close, query_order=query)
    monkeypatch.setattr(service, "get_payment", lambda: gateway)
    url = f"{API}/orders/{order_no}"
    assert client.post(f"{API}/dev/orders/{order_no}/simulate-paid", headers=headers).status_code == 409
    assert client.post(url + "/cancel", headers=headers).status_code == 409
    assert db.scalar(select(Order.status)) == "pending"
    assert db.scalar(select(Payment.status)) == "pending"

    assert client.get(url, headers=headers).json()["status"] == "paid"
    assert db.scalar(select(Payment.transaction_id)) == "WX123"
    assert len(client.get(f"{API}/entitlements", headers=headers).json()) == 1


def test_wechat_closed_refund_releases_reserved_balance(client, db, monkeypatch):
    order_no, payment = _buy_paid_and_enable_wechat(client, db, monkeypatch)
    gateway = SimpleNamespace(refund=lambda **kwargs: "pending")
    monkeypatch.setattr(service, "get_payment", lambda: gateway)
    request = dict(order_no=order_no, amount_fen=9900, reason="整单退款", operator="admin")
    first = service.refund_order(db, request_id=uuid4(), **request)
    db.commit()
    assert first.refund.status == "pending"
    result = RefundResult(
        payment.out_trade_no, first.refund.out_refund_no, payment.transaction_id, 9900, 9900, "failed"
    )
    gateway.parse_refund_notify = lambda headers, body: result
    response = client.post(f"{API}/callbacks/wxpay/refund", content=b"notification")
    assert response.status_code == 204
    assert first.refund.status == "failed"
    assert first.refund.finished_at is not None
    assert first.order.status == "paid"
    assert first.order.refunded_fen == 0

    next_refund = service.refund_order(db, request_id=uuid4(), **request).refund
    assert next_refund.status == "pending"
    assert next_refund.out_refund_no != first.refund.out_refund_no
