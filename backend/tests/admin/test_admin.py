from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.payment import FakePay
from app.main import app
from app.models import Entitlement, ReceiptApplication
from scripts.check_api_docs import find_problems
from tests.admin.helpers import API, PASSWORD, admin_login, entitlement_statuses, make_admin, user_buys
from tests.conftest import login
from tests.factories import make_provider_for, make_spec, make_standard_plans
from tests.orders.helpers import latest_user_id, make_photo
from tests.receipts.helpers import (
    PROVIDER_CODE,
    create_app,
    get_application,
    make_world,
    quota_used,
    simulate,
)

NEW_PLAN = {
    "code": "new_plan",
    "name": "新套餐",
    "price_fen": 5000,
    "status": "on_sale",
    "sort": 5,
    "display": {},
    "benefits": {"storage_days": 30, "receipt_quota": 2},
}


def _audit(client: TestClient, **params) -> list[dict]:
    r = client.get(f"{API}/audit-logs", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _refund_body(amount_fen: int, reason: str = "用户重复购买") -> dict:
    return {"request_id": str(uuid4()), "amount_fen": amount_fen, "reason": reason}


# ---------- 登录与会话 ----------


def test_login_success_sets_cookie_and_csrf(client: TestClient, db: Session):
    make_admin(db, "boss", "owner")
    r = client.post(f"{API}/auth/login", json={"username": "boss", "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["csrf_token"]
    assert body["admin"]["username"] == "boss" and body["admin"]["role"] == "owner"
    cookie = r.headers["set-cookie"].lower()
    assert "admin_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/admin" in cookie
    # 令牌不在响应体里
    assert "token" not in {k for k in body if k != "csrf_token"}
    assert client.get(f"{API}/me").status_code == 200


def test_login_failures_share_one_error(client: TestClient, db: Session):
    make_admin(db, "boss", "owner")
    make_admin(db, "gone", "owner", status="disabled")
    for username, password in [("boss", "wrong-password"), ("nobody", PASSWORD), ("gone", PASSWORD)]:
        r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
        assert r.status_code == 401
        assert r.json()["code"] == "ADMIN_LOGIN_FAILED"


def test_login_rate_limited_after_five_failures(client: TestClient, db: Session):
    make_admin(db, "boss", "owner")
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"username": "boss", "password": "wrong-password"})
        assert r.json()["code"] == "ADMIN_LOGIN_FAILED"
    r = client.post(f"{API}/auth/login", json={"username": "boss", "password": PASSWORD})
    assert r.status_code == 429
    assert r.json()["code"] == "RATE_LIMITED"


def test_requires_login(client: TestClient):
    r = client.get(f"{API}/me")
    assert r.status_code == 401 and r.json()["code"] == "AUTH_REQUIRED"
    r = client.get(f"{API}/users")
    assert r.json()["code"] == "AUTH_REQUIRED"
    r = client.get(f"{API}/me", headers={"Cookie": "admin_session=not-a-real-token"})
    assert r.status_code == 401 and r.json()["code"] == "AUTH_INVALID"


def test_write_requires_csrf_token(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    r = client.post(f"{API}/plans", json=NEW_PLAN)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_DENIED"
    r = client.post(f"{API}/plans", json=NEW_PLAN, headers={"X-CSRF-Token": "wrong"})
    assert r.json()["code"] == "PERMISSION_DENIED"
    r = client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf)
    assert r.status_code == 200, r.text


def test_logout_revokes_session(client: TestClient, db: Session):
    admin_login(client, db)
    token = client.cookies.get("admin_session")
    assert token
    assert client.post(f"{API}/auth/logout").json() == {"ok": True}
    # 即使有人保留了旧令牌，服务端也已吊销
    r = client.get(f"{API}/me", headers={"Cookie": f"admin_session={token}"})
    assert r.status_code == 401 and r.json()["code"] == "AUTH_INVALID"
    # 再退出一次也成功
    assert client.post(f"{API}/auth/logout").status_code == 200


def test_me_permissions_by_role(client: TestClient, db: Session):
    admin_login(client, db, "op", "operator")
    me = client.get(f"{API}/me").json()
    assert me["role"] == "operator"
    assert "plan:read" in me["permissions"] and "plan:write" not in me["permissions"]
    client.post(f"{API}/auth/logout")

    admin_login(client, db, "boss", "owner")
    perms = client.get(f"{API}/me").json()["permissions"]
    assert "plan:write" in perms and "refund:create" in perms and "*" not in perms


# ---------- 套餐 ----------


def test_finance_cannot_write_plans(client: TestClient, db: Session):
    csrf = admin_login(client, db, "fin", "finance")
    assert client.get(f"{API}/plans").status_code == 200
    r = client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_DENIED"
    r = client.patch(f"{API}/plans/anything", json={"price_fen": 1}, headers=csrf)
    assert r.json()["code"] == "PERMISSION_DENIED"


def test_owner_creates_updates_and_offlines_plan(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    r = client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["benefits"] == {"storage_days": 30, "receipt_quota": 2}
    assert "new_plan" in {p["code"] for p in client.get("/api/v1/plans").json()}

    r = client.patch(
        f"{API}/plans/new_plan",
        json={"price_fen": 4500, "benefits": {"storage_days": 60}},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    assert r.json()["price_fen"] == 4500
    assert r.json()["benefits"] == {"storage_days": 60}  # 整体替换，没写的被删除

    r = client.patch(f"{API}/plans/new_plan", json={"status": "off_sale"}, headers=csrf)
    assert r.json()["status"] == "off_sale"
    assert "new_plan" not in {p["code"] for p in client.get("/api/v1/plans").json()}
    listed = {p["code"]: p for p in client.get(f"{API}/plans").json()}
    assert listed["new_plan"]["status"] == "off_sale"  # 后台仍能看到下架的

    logs = _audit(client, action="plan.update")
    assert len(logs) == 2
    assert any(lg["before"].get("price_fen") == 5000 and lg["after"]["price_fen"] == 4500 for lg in logs)
    assert _audit(client, action="plan.create")[0]["target_type"] == "plan"


def test_plan_validation(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    bad = {**NEW_PLAN, "benefits": {"made_up": 1}}
    r = client.post(f"{API}/plans", json=bad, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf).status_code == 200
    r = client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf)
    assert (r.status_code, r.json()) == (409, {"code": "CONFLICT", "message": "数据已存在"})
    r = client.patch(f"{API}/plans/nope", json={"name": "x"}, headers=csrf)
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_plan_change_does_not_affect_sold_entitlement(client: TestClient, db: Session):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    csrf = admin_login(client, db)
    r = client.patch(
        f"{API}/plans/photo_year_39_9",
        json={"price_fen": 100, "benefits": {"storage_days": 1, "photo_scope": 1}},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    snap = db.scalars(select(Entitlement.benefits_snapshot)).all()
    assert len(snap) == 1 and snap[0]["storage_days"] == 365 and snap[0]["receipt_quota"] == 1
    assert entitlement_statuses(db, order_no) == ["active"]


# ---------- 退款 ----------


def test_full_refund_revokes_entitlements_and_audits(client: TestClient, db: Session):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    assert entitlement_statuses(db, order_no) == ["active"]
    csrf = admin_login(client, db, "fin", "finance")

    r = client.post(f"{API}/orders/{order_no}/refunds", json=_refund_body(3990), headers=csrf)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["operator"] == "fin"
    assert body["order_status"] == "refunded" and body["order_refunded_fen"] == 3990

    detail = client.get(f"{API}/orders/{order_no}").json()
    assert detail["status"] == "refunded" and detail["refunded_fen"] == 3990
    assert len(detail["payments"]) == 1 and detail["payments"][0]["status"] == "success"
    assert detail["refunds"][0]["amount_fen"] == 3990
    assert entitlement_statuses(db, order_no) == ["revoked"]

    logs = _audit(client, action="refund.create")
    assert len(logs) == 1
    assert logs[0]["target_type"] == "order"
    assert logs[0]["before"]["status"] == "paid" and logs[0]["after"]["status"] == "refunded"
    assert logs[0]["admin_username"] == "fin"

    # 已全额退款，不能再退
    r = client.post(f"{API}/orders/{order_no}/refunds", json=_refund_body(1, "再退"), headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "REFUND_NOT_ALLOWED"


def test_partial_refunds_and_over_refund(client: TestClient, db: Session):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    csrf = admin_login(client, db, "fin", "finance")
    url = f"{API}/orders/{order_no}/refunds"

    r = client.post(url, json=_refund_body(1000, "部分退款"), headers=csrf)
    assert r.status_code == 200 and r.json()["order_status"] == "part_refunded"
    assert entitlement_statuses(db, order_no) == ["active"]  # 没退完，权益保留

    r = client.post(url, json=_refund_body(3000, "超额"), headers=csrf)  # 剩余 2990
    assert r.status_code == 409 and r.json()["code"] == "REFUND_NOT_ALLOWED"
    assert client.get(f"{API}/orders/{order_no}").json()["refunded_fen"] == 1000

    r = client.post(url, json=_refund_body(2990, "退完"), headers=csrf)
    assert r.json()["order_status"] == "refunded"
    assert entitlement_statuses(db, order_no) == ["revoked"]


def test_full_refund_cancels_open_applications_and_revokes_addons(client: TestClient, db: Session):
    world = make_world(client, db)
    main_order = client.get("/api/v1/orders", headers=world.headers).json()["items"][0]["order_no"]
    main_app = create_app(client, world)

    def buy_addon(parent_id: int) -> str:
        r = client.post(
            "/api/v1/orders",
            headers=world.headers,
            json={"plan_code": "addon_receipt_10", "parent_entitlement_id": parent_id},
        )
        assert r.status_code == 200, r.text
        order_no = r.json()["order_no"]
        paid = client.post(f"/api/v1/dev/orders/{order_no}/simulate-paid", headers=world.headers)
        assert paid.status_code == 200, paid.text
        return order_no

    addon = buy_addon(main_app["entitlement_id"])
    addon_app = create_app(client, world)
    nested_addon = buy_addon(addon_app["entitlement_id"])
    completed = create_app(client, world)
    assert simulate(client, world.headers, main_app["app_no"], "rejected").json()["status"] == "rejected"
    assert simulate(client, world.headers, completed["app_no"], "completed").json()["status"] == "completed"

    csrf = admin_login(client, db, "fin", "finance")
    refunded = client.post(f"{API}/orders/{main_order}/refunds", json=_refund_body(3990), headers=csrf)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["order_status"] == "refunded"
    for order_no in (main_order, addon, nested_addon):
        assert entitlement_statuses(db, order_no) == ["revoked"]
    for application in (main_app, addon_app):
        assert get_application(db, application["app_no"]).status == "cancelled"
        assert quota_used(db, application["entitlement_id"]) == 0
    assert get_application(db, completed["app_no"]).status == "completed"
    assert quota_used(db, completed["entitlement_id"]) == 1
    late_result = simulate(client, world.headers, addon_app["app_no"], "completed")
    assert late_result.json()["status"] == "cancelled"


def test_refund_request_id_replays_full_refund_and_rejects_mismatches(client: TestClient, db: Session):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    _, other_order, _ = user_buys(client, db, code="dev:bob")
    csrf = admin_login(client, db, "fin", "finance")
    body = _refund_body(3990)
    url = f"{API}/orders/{order_no}/refunds"

    first = client.post(url, json=body, headers=csrf)
    assert first.status_code == 200, first.text
    replay = client.post(url, json={**body, "reason": "重试"}, headers=csrf)
    assert replay.json() == first.json()
    assert first.json()["out_refund_no"] == f"RA{body['request_id'].replace('-', '')}"

    for path, payload in (
        (url, {**body, "amount_fen": 1000}),
        (f"{API}/orders/{other_order}/refunds", body),
    ):
        conflict = client.post(path, json=payload, headers=csrf)
        assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_CONFLICT")
    assert len(client.get(f"{API}/orders/{order_no}").json()["refunds"]) == 1
    assert client.get(f"{API}/orders/{other_order}").json()["refunds"] == []
    assert len(_audit(client, action="refund.create")) == 1


def test_pending_refund_replays_without_resubmission_and_reserves_balance(client, db, monkeypatch):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    csrf = admin_login(client, db, "fin", "finance")
    submissions = []

    def refund_pending(self, **kwargs):
        submissions.append(kwargs["out_refund_no"])
        return "pending"

    monkeypatch.setattr(FakePay, "refund", refund_pending)
    url = f"{API}/orders/{order_no}/refunds"
    body = _refund_body(3000)
    first = client.post(url, json=body, headers=csrf)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending" and first.json()["finished_at"] is None
    assert first.json()["order_status"] == "paid" and first.json()["order_refunded_fen"] == 0
    assert client.post(url, json=body, headers=csrf).json() == first.json()
    assert client.post(url, json=_refund_body(1000), headers=csrf).json()["code"] == "REFUND_NOT_ALLOWED"
    assert submissions == [first.json()["out_refund_no"]]
    assert entitlement_statuses(db, order_no) == ["active"]


def test_refund_rejected_for_unpaid_missing_and_invalid(client: TestClient, db: Session):
    make_standard_plans(db)
    h = login(client, "dev:alice")
    photo = make_photo(db, latest_user_id(db))
    pending = client.post(
        "/api/v1/orders", headers=h, json={"plan_code": "photo_year_39_9", "photo_id": photo.id}
    ).json()["order_no"]
    csrf = admin_login(client, db, "fin", "finance")

    r = client.post(f"{API}/orders/{pending}/refunds", json=_refund_body(100), headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "REFUND_NOT_ALLOWED"
    r = client.post(f"{API}/orders/NOPE/refunds", json=_refund_body(100), headers=csrf)
    assert r.status_code == 404 and r.json()["code"] == "ORDER_NOT_FOUND"
    r = client.post(f"{API}/orders/{pending}/refunds", json=_refund_body(0), headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    for body in ({"amount_fen": 100, "reason": "x"}, {**_refund_body(100), "request_id": "invalid"}):
        r = client.post(f"{API}/orders/{pending}/refunds", json=body, headers=csrf)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "body.request_id"
    assert _audit(client, action="refund.create") == []


def test_operator_cannot_refund(client: TestClient, db: Session):
    make_standard_plans(db)
    _, order_no, _ = user_buys(client, db)
    csrf = admin_login(client, db, "op", "operator")
    r = client.post(f"{API}/orders/{order_no}/refunds", json=_refund_body(100), headers=csrf)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_DENIED"


# ---------- 订单、用户 ----------


def test_orders_list_filters_and_pagination(client: TestClient, db: Session):
    make_standard_plans(db)
    uid_a, order_a, _ = user_buys(client, db, code="dev:alice")
    uid_b, order_b, _ = user_buys(client, db, code="dev:bob")
    admin_login(client, db, "fin", "finance")

    r = client.get(f"{API}/orders", params={"user_id": uid_a})
    assert [o["order_no"] for o in r.json()["items"]] == [order_a]
    assert client.get(f"{API}/orders", params={"order_no": order_b}).json()["items"][0]["user_id"] == uid_b
    assert len(client.get(f"{API}/orders", params={"status": "paid"}).json()["items"]) == 2
    assert client.get(f"{API}/orders", params={"status": "refunded"}).json()["items"] == []
    future = client.get(f"{API}/orders", params={"created_from": "2999-01-01T00:00:00Z"})
    assert future.json()["items"] == []

    first = client.get(f"{API}/orders", params={"limit": 1}).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = client.get(f"{API}/orders", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert second["next_cursor"] is None
    assert {first["items"][0]["order_no"], second["items"][0]["order_no"]} == {order_a, order_b}
    assert client.get(f"{API}/orders/NOPE").json()["code"] == "ORDER_NOT_FOUND"


def test_users_search_by_phone_masked(client: TestClient, db: Session):
    make_standard_plans(db)
    uid, _, h = user_buys(client, db)
    r = client.post("/api/v1/me/phone", headers=h, json={"code": "phone:13800001234"})
    assert r.status_code == 200, r.text
    other = login(client, "dev:bob")
    assert other  # 另一个没有手机号的用户
    url = f"{API}/users/search"
    assert client.post(url, json={}).status_code == 401
    csrf = admin_login(client, db, "op", "operator")
    assert client.post(url, json={}).status_code == 403

    r = client.post(url, json={"phone": "13800001234", "status": "active", "user_id": uid}, headers=csrf)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["id"] == uid
    assert items[0]["phone_masked"] == "138****1234"
    assert "13800001234" not in r.text
    assert items[0]["identities"] == ["wx_mini"]
    assert items[0]["orders_count"] == 1 and items[0]["paid_fen_total"] == 3990

    assert client.post(url, json={"phone": "13900009999"}, headers=csrf).json()["items"] == []
    assert (
        client.post(url, json={"phone": "13800001234", "status": "disabled"}, headers=csrf).json()["items"]
        == []
    )
    first = client.post(url, json={"limit": 1, "status": "active"}, headers=csrf).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = client.post(url, json={"cursor": first["next_cursor"], "limit": 1}, headers=csrf).json()
    assert [u["id"] for u in second["items"]] == [uid] and second["next_cursor"] is None
    assert len(client.get(f"{API}/users", params={"user_id": uid}).json()["items"]) == 1
    assert len(client.get(f"{API}/users", params={"status": "active"}).json()["items"]) == 2

    detail = client.get(f"{API}/users/{uid}").json()
    assert detail["phone_masked"] == "138****1234" and detail["applications_count"] == 0
    assert client.get(f"{API}/users/999999999").json()["code"] == "NOT_FOUND"


# ---------- 回执申请 ----------


def test_applications_list_detail_and_cancel(client: TestClient, db: Session):
    w = make_world(client, db)
    created = create_app(client, w)
    app_no = created["app_no"]
    uid = get_application(db, app_no).user_id
    csrf = admin_login(client, db, "op", "operator")

    items = client.get(f"{API}/receipt-applications", params={"user_id": uid}).json()["items"]
    assert [a["app_no"] for a in items] == [app_no]
    assert items[0]["status"] == "processing" and items[0]["spec_code"] == w.spec.code
    assert client.get(f"{API}/receipt-applications", params={"status": "rejected"}).json()["items"] == []
    assert (
        len(client.get(f"{API}/receipt-applications", params={"spec_code": w.spec.code}).json()["items"]) == 1
    )
    assert len(client.get(f"{API}/receipt-applications", params={"app_no": app_no}).json()["items"]) == 1

    r = client.get(f"{API}/receipt-applications/{app_no}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["attempts"][0]["provider_code"] == PROVIDER_CODE
    assert detail["attempts"][0]["seq"] == 1 and detail["attempts"][0]["is_current"] is True
    assert detail["form_masked"]["name"] == "张*"
    assert "110101199001010019" not in r.text

    # 办理中的不能取消
    r = client.post(f"{API}/receipt-applications/{app_no}/cancel", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "APPLICATION_NOT_RESUBMITTABLE"
    assert _audit(client, action="application.cancel") == []

    assert simulate(client, w.headers, app_no, "rejected", "背景不均匀").status_code == 200
    used_before = quota_used(db, created["entitlement_id"])
    r = client.post(f"{API}/receipt-applications/{app_no}/cancel", headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert quota_used(db, created["entitlement_id"]) == used_before - 1
    assert (
        db.scalar(select(ReceiptApplication.status).where(ReceiptApplication.app_no == app_no)) == "cancelled"
    )
    logs = _audit(client, action="application.cancel")
    assert len(logs) == 1 and logs[0]["before"] == {"status": "rejected"}

    assert client.get(f"{API}/receipt-applications/NOPE").json()["code"] == "APPLICATION_NOT_FOUND"
    r = client.post(f"{API}/receipt-applications/NOPE/cancel", headers=csrf)
    assert r.json()["code"] == "APPLICATION_NOT_FOUND"


# ---------- 规格、服务商、审计 ----------

SPEC_BODY = {
    "code": "adm_spec",
    "name": "后台规格",
    "category": "normal",
    "cert_type": "visa",
    "width_px": 295,
    "height_px": 413,
    "bg_colors": ["#FFFFFF"],
    "form_schema": [{"key": "name", "label": "姓名", "required": True}],
}


def test_specs_create_update_list(client: TestClient, db: Session):
    csrf = admin_login(client, db, "op", "operator")
    r = client.post(f"{API}/specs", json=SPEC_BODY, headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and r.json()["dpi"] == 300

    child = {**SPEC_BODY, "code": "adm_child", "parent_code": "adm_spec"}
    assert client.post(f"{API}/specs", json=child, headers=csrf).json()["parent_code"] == "adm_spec"
    duplicate = client.post(f"{API}/specs", json=SPEC_BODY, headers=csrf)
    assert (duplicate.status_code, duplicate.json()) == (409, {"code": "CONFLICT", "message": "数据已存在"})
    bad = {**SPEC_BODY, "code": "adm_bad", "bg_colors": ["white"]}
    assert client.post(f"{API}/specs", json=bad, headers=csrf).status_code == 422

    r = client.patch(f"{API}/specs/adm_spec", json={"name": "改名", "status": "inactive"}, headers=csrf)
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    codes = {s["code"]: s for s in client.get(f"{API}/specs").json()["items"]}
    assert codes["adm_spec"]["name"] == "改名" and codes["adm_child"]["parent_code"] == "adm_spec"
    assert client.patch(f"{API}/specs/nope", json={"name": "x"}, headers=csrf).status_code == 404
    log = _audit(client, action="spec.update")[0]
    assert log["before"] == {"name": "后台规格", "status": "active"}


def test_finance_cannot_write_specs(client: TestClient, db: Session):
    csrf = admin_login(client, db, "fin", "finance")
    assert client.get(f"{API}/specs").status_code == 403  # finance 没有 spec:read
    r = client.post(f"{API}/specs", json=SPEC_BODY, headers=csrf)
    assert r.json()["code"] == "PERMISSION_DENIED"


def test_providers_list_and_update(client: TestClient, db: Session):
    spec = make_spec(db, "prov_spec")
    make_provider_for(db, spec, "prov_a")
    csrf = admin_login(client, db, "op", "operator")

    providers = {p["code"]: p for p in client.get(f"{API}/providers").json()}
    p = providers["prov_a"]
    assert p["provider_specs"][0]["spec_code"] == "prov_spec" and p["provider_specs"][0]["cost_fen"] == 300
    assert p["route_rules"][0]["priority"] == 10
    assert "config" not in str(p).lower()

    r = client.patch(f"{API}/providers/prov_a", json={"status": "disabled"}, headers=csrf)
    assert r.json()["code"] == "PERMISSION_DENIED"  # 只有 owner

    client.post(f"{API}/auth/logout")
    csrf = admin_login(client, db, "boss", "owner")
    r = client.patch(f"{API}/providers/prov_a", json={"status": "circuit_open"}, headers=csrf)
    assert r.status_code == 200 and r.json()["status"] == "circuit_open"
    assert client.patch(f"{API}/providers/nope", json={"status": "enabled"}, headers=csrf).status_code == 404
    log = _audit(client, action="provider.update")[0]
    assert log["before"] == {"status": "enabled"} and log["after"] == {"status": "circuit_open"}


def test_audit_logs_filters(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    client.post(f"{API}/plans", json=NEW_PLAN, headers=csrf)
    me = client.get(f"{API}/me").json()
    mine = _audit(client, admin_id=me["id"])
    assert {lg["action"] for lg in mine} >= {"auth.login", "plan.create"}
    assert [lg["action"] for lg in _audit(client, target_type="plan")] == ["plan.create"]
    assert _audit(client, admin_id=me["id"] + 1000) == []


def test_admin_api_docs_complete():
    spec = app.openapi()
    assert find_problems(spec) == []
    ids = [
        op["operationId"]
        for path, ops in spec["paths"].items()
        if path.startswith("/api/v1/admin")
        for op in ops.values()
    ]
    assert len(ids) == 21 and all(i.startswith("admin_") for i in ids)
    users_list = spec["paths"][f"{API}/users"]["get"]
    assert "phone" not in {p["name"] for p in users_list["parameters"]}
    users_search = spec["paths"][f"{API}/users/search"]["post"]
    assert users_search["operationId"] == "admin_users_search"
    assert "422" in users_search["responses"]
    assert set(spec["components"]["schemas"]["AdminUserSearchIn"]["properties"]) == {
        "phone",
        "user_id",
        "status",
        "cursor",
        "limit",
    }
