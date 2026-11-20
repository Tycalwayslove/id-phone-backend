import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.utils import utcnow
from app.integrations.payment import FakePay, sign_fake_notify
from app.models import Entitlement, Order, Payment, Refund
from tests.conftest import login
from tests.factories import make_plan, make_standard_plans
from tests.orders.helpers import latest_user_id, make_photo

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
    assert r.json()["code"] == "PAYMENT_SIGNATURE_INVALID"
    assert client.get(f"{API}/orders/{order_no}", headers=h).json()["status"] == "pending"


def test_wxpay_callback_marks_paid_and_is_idempotent(client, db):
    h, _ = _setup(client, db)
    order_no = _buy(client, h, "unlimited_99")["order_no"]
    body = _notify_body(db, order_no, amount_fen=9900)
    headers = {"X-Fake-Signature": sign_fake_notify(body), "Content-Type": "application/json"}
    for _ in range(2):
        r = client.post(f"{API}/callbacks/wxpay", content=body, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"code": "SUCCESS", "message": "成功"}
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
        assert r.status_code == 200, r.text
        assert r.json()["code"] == "SUCCESS"

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
    assert r.json()["code"] == "ORDER_NOT_PAYABLE"
    assert client.get(f"{API}/orders/{order_no}", headers=h).json()["status"] == "pending"


def test_wxpay_callback_unknown_order(client, db):
    body = json.dumps({"out_trade_no": "P_NONE", "transaction_id": "T", "amount_fen": 100}).encode()
    r = client.post(
        f"{API}/callbacks/wxpay", content=body, headers={"X-Fake-Signature": sign_fake_notify(body)}
    )
    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"


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
