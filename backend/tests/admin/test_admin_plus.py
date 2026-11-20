"""看板、通知、路由配置与管理员账号的接口回归测试。"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentAdmin, current_admin
from app.core.security import verify_password
from app.core.utils import utcnow
from app.main import app
from app.models import AdminUser, NotifyTask, Order
from tests.admin.helpers import API, PASSWORD, admin_login, make_admin
from tests.factories import make_provider_for, make_spec
from tests.receipts.helpers import create_app, get_application, make_world

PROVIDER_CODES = {"provider_code": "routing_provider", "spec_code": "routing_spec"}
PROVIDER_BODY = {**PROVIDER_CODES, "provider_item_id": "713", "cost_fen": 300}
ACCOUNT_BODY = {"username": "new_operator", "role": "operator", "password": PASSWORD}


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    "method,path,body,role",
    [
        ("GET", "/stats/overview", None, "finance"),
        ("GET", "/notify-tasks", None, "finance"),
        ("POST", "/provider-specs", PROVIDER_BODY, "operator"),
        ("PATCH", "/provider-specs/1", {"cost_fen": 400}, "operator"),
        ("DELETE", "/provider-specs/1", None, "operator"),
        ("POST", "/route-rules", PROVIDER_CODES, "operator"),
        ("PATCH", "/route-rules/1", {"priority": 20}, "operator"),
        ("DELETE", "/route-rules/1", None, "operator"),
        ("GET", "/admin-users", None, "operator"),
        ("POST", "/admin-users", ACCOUNT_BODY, "operator"),
        ("POST", "/admin-users/1/disable", None, "operator"),
        ("PATCH", "/admin-users/1/role", {"role": "finance"}, "operator"),
        ("POST", "/admin-users/1/reset-password", None, "operator"),
    ],
)
def test_admin_plus_permissions(method, path, body, role):
    with TestClient(app) as client:
        assert_error(client.request(method, API + path, json=body), 401, "AUTH_REQUIRED")
        app.dependency_overrides[current_admin] = lambda: CurrentAdmin(1, "restricted", role, 1)
        try:
            assert_error(client.request(method, API + path, json=body), 403, "PERMISSION_DENIED")
        finally:
            app.dependency_overrides.pop(current_admin)


def test_stats_overview(client: TestClient, db: Session):
    admin_login(client, db, role="operator")
    url = f"{API}/stats/overview"
    response = client.get(url)
    assert response.status_code == 200
    before = response.json()
    world = make_world(client, db)
    receipt = get_application(db, create_app(client, world)["app_no"])
    paid_order = db.scalars(select(Order).where(Order.user_id == receipt.user_id)).one()
    paid_order.status = "part_refunded"
    paid_order.refunded_fen = 100
    db.add(
        Order(
            order_no="unpaid_overview",
            user_id=receipt.user_id,
            total_fen=1000,
            expire_at=utcnow(),
            client="mini",
        )
    )
    db.flush()

    response = client.get(url)
    assert response.status_code == 200
    after = response.json()
    assert after["user_count"] == before["user_count"] + 1
    assert after["order_count"] == before["order_count"] + 2
    assert after["paid_order_count"] == before["paid_order_count"] + 1
    assert after["paid_total_fen"] == before["paid_total_fen"] + 3990
    assert after["receipt_count"] == before["receipt_count"] + 1
    assert after["receipt_counts_by_status"] == {
        **before["receipt_counts_by_status"],
        "processing": before["receipt_counts_by_status"]["processing"] + 1,
    }
    assert set(after["receipt_counts_by_status"]) == {
        "pending",
        "processing",
        "rejected",
        "completed",
        "failed",
        "cancelled",
    }


def test_notify_tasks_filter(client: TestClient, db: Session):
    world = make_world(client, db)
    receipt = get_application(db, create_app(client, world)["app_no"])
    tasks = [
        NotifyTask(
            user_id=receipt.user_id,
            application_id=receipt.id,
            event="receipt_expiring",
            step=step,
            channel="mini_subscribe",
            status=status,
            scheduled_at=utcnow(),
            result={"opaque_payload": "private-test-value"},
        )
        for step, status in [(1, "failed"), (7, "failed"), (2, "sent")]
    ]
    db.add_all(tasks)
    db.flush()
    admin_login(client, db, role="operator")
    url = f"{API}/notify-tasks"
    response = client.get(url, params={"status": "failed", "page_size": 10})
    assert response.status_code == 200
    first = response.json()
    assert first["total"] == 2
    assert [item["id"] for item in first["items"]] == [tasks[1].id, tasks[0].id]
    assert first["items"][0]["application_id"] == receipt.id
    assert "result" not in first["items"][0]
    assert "private-test-value" not in response.text
    assert_error(client.get(url, params={"status": "unknown"}), 422, "VALIDATION_ERROR")


def test_provider_spec_writes_and_audits(client: TestClient, db: Session):
    fallback = make_spec(db, "fallback_spec")
    make_provider_for(db, fallback, PROVIDER_CODES["provider_code"])
    make_spec(db, PROVIDER_CODES["spec_code"])
    csrf = admin_login(client, db)
    url = f"{API}/provider-specs"

    assert_error(client.post(url, json=PROVIDER_BODY), 403, "PERMISSION_DENIED")
    assert_error(
        client.post(url, headers=csrf, json={**PROVIDER_BODY, "spec_code": "missing"}),
        404,
        "SPEC_NOT_FOUND",
    )
    response = client.post(url, headers=csrf, json=PROVIDER_BODY)
    assert response.status_code == 200
    entry_id = response.json()["id"]
    entry_url = f"{url}/{entry_id}"
    assert_error(client.post(url, headers=csrf, json=PROVIDER_BODY), 409, "CONFLICT")
    assert_error(client.patch(entry_url, headers=csrf, json={"spec_code": fallback.code}), 409, "CONFLICT")
    assert_error(client.patch(entry_url, headers=csrf, json={"cost_fen": None}), 422, "VALIDATION_ERROR")

    response = client.patch(
        entry_url,
        headers=csrf,
        json={"cost_fen": 450, "is_enabled": False, "param_mapping": {"name": "text_name"}},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["cost_fen"] == 450 and updated["is_enabled"] is False
    assert updated["param_mapping"] == {"name": "text_name"}
    listed = client.get(f"{API}/provider-specs", params={"provider_code": PROVIDER_CODES["provider_code"]})
    assert updated in listed.json()["items"]

    assert client.delete(entry_url, headers=csrf).json() == {"ok": True}
    assert_error(client.delete(entry_url, headers=csrf), 404, "NOT_FOUND")
    logs = client.get(f"{API}/audit-logs", params={"target_type": "provider_spec"}).json()["items"]
    assert [(log["action"], log["target_id"]) for log in logs] == [
        ("provider_spec.delete", entry_id),
        ("provider_spec.update", entry_id),
        ("provider_spec.create", entry_id),
    ]
    assert logs[1]["before"]["cost_fen"] == 300
    assert logs[1]["after"]["cost_fen"] == 450
    assert logs[1]["after"]["param_mapping_changed"] is True
    assert "text_name" not in json.dumps(logs)


def test_route_rule_writes_and_audits(client: TestClient, db: Session):
    spec = make_spec(db, PROVIDER_CODES["spec_code"])
    make_provider_for(db, spec, PROVIDER_CODES["provider_code"])
    csrf = admin_login(client, db)
    url = f"{API}/route-rules"
    assert_error(client.post(url, headers=csrf, json=PROVIDER_CODES), 409, "CONFLICT")
    assert_error(
        client.post(url, headers=csrf, json={**PROVIDER_CODES, "provider_code": "missing"}),
        404,
        "NOT_FOUND",
    )
    response = client.post(url, headers=csrf, json={**PROVIDER_CODES, "region_code": "440300", "priority": 5})
    assert response.status_code == 200
    rule_id = response.json()["id"]
    rule_url = f"{url}/{rule_id}"
    assert_error(client.patch(rule_url, headers=csrf, json={"region_code": None}), 409, "CONFLICT")
    assert_error(client.patch(rule_url, headers=csrf, json={"priority": None}), 422, "VALIDATION_ERROR")

    response = client.patch(rule_url, headers=csrf, json={"priority": 20})
    assert response.status_code == 200
    assert response.json()["region_code"] == "440300"
    assert response.json()["priority"] == 20
    assert client.delete(rule_url, headers=csrf).json() == {"ok": True}
    assert_error(client.delete(rule_url, headers=csrf), 404, "NOT_FOUND")

    logs = client.get(f"{API}/audit-logs", params={"target_type": "route_rule"}).json()["items"]
    assert [(log["action"], log["target_id"]) for log in logs] == [
        ("route_rule.delete", rule_id),
        ("route_rule.update", rule_id),
        ("route_rule.create", rule_id),
    ]
    assert logs[1]["before"]["priority"] == 5 and logs[1]["after"]["priority"] == 20


def test_admin_account_lifecycle(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    url = f"{API}/admin-users"
    response = client.post(url, headers=csrf, json=ACCOUNT_BODY)
    assert response.status_code == 200
    account = response.json()
    account_url = f"{url}/{account['id']}"
    assert account["role"] == "operator" and account["status"] == "active"
    stored = db.get(AdminUser, account["id"])
    assert stored.password_hash != PASSWORD and verify_password(stored.password_hash, PASSWORD)
    assert_error(client.post(url, headers=csrf, json=ACCOUNT_BODY), 409, "CONFLICT")
    assert_error(client.get(url, params={"page_size": 0}), 422, "VALIDATION_ERROR")
    first_page = client.get(url, params={"page_size": 10}).json()
    assert first_page["total"] == 2 and first_page["items"][0] == account
    assert first_page["items"][1]["username"] == "boss"

    with TestClient(app) as target:
        assert (
            target.post(
                f"{API}/auth/login", json={"username": account["username"], "password": PASSWORD}
            ).status_code
            == 200
        )
        assert "notify:read" in target.get(f"{API}/me").json()["permissions"]
        assert_error(
            client.patch(f"{url}/999999/role", headers=csrf, json={"role": "finance"}), 404, "NOT_FOUND"
        )
        updated = client.patch(f"{account_url}/role", headers=csrf, json={"role": "finance"})
        assert updated.status_code == 200 and updated.json()["role"] == "finance"
        assert "notify:read" not in target.get(f"{API}/me").json()["permissions"]
        assert_error(client.post(f"{url}/999999/disable", headers=csrf), 404, "NOT_FOUND")
        disabled = client.post(f"{account_url}/disable", headers=csrf)
        assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
        assert_error(target.get(f"{API}/me"), 401, "AUTH_INVALID")
        assert client.post(f"{account_url}/disable", headers=csrf).status_code == 200
        assert_error(client.post(f"{account_url}/reset-password", headers=csrf), 403, "ACCOUNT_DISABLED")

    logs = client.get(f"{API}/audit-logs", params={"target_type": "admin_user"}).json()["items"]
    assert [log["action"] for log in logs] == [
        "admin_user.disable",
        "admin_user.update_role",
        "admin_user.create",
    ]
    assert all(log["target_id"] == account["id"] for log in logs)
    assert PASSWORD not in json.dumps(logs)


def test_last_owner_and_self_protection(client: TestClient, db: Session):
    csrf = admin_login(client, db)
    actor_id = client.get(f"{API}/me").json()["id"]
    account_url = f"{API}/admin-users/{actor_id}"
    make_admin(db, "disabled_owner", "owner", status="disabled")
    assert_error(client.post(f"{account_url}/disable", headers=csrf), 409, "CONFLICT")
    assert_error(
        client.patch(f"{account_url}/role", headers=csrf, json={"role": "operator"}), 409, "CONFLICT"
    )
    other = make_admin(db, "other_owner", "owner")
    assert_error(client.post(f"{account_url}/disable", headers=csrf), 403, "PERMISSION_DENIED")
    assert_error(
        client.patch(f"{account_url}/role", headers=csrf, json={"role": "finance"}), 403, "PERMISSION_DENIED"
    )
    changed = client.patch(f"{API}/admin-users/{other.id}/role", headers=csrf, json={"role": "operator"})
    assert changed.status_code == 200
    assert_error(client.post(f"{account_url}/disable", headers=csrf), 409, "CONFLICT")


def test_admin_reset_password_is_single_use(client: TestClient, db: Session, caplog):
    csrf = admin_login(client, db)
    account = make_admin(db, "reset_target", "operator")
    url = f"{API}/admin-users/{account.id}/reset-password"
    login_url = f"{API}/auth/login"
    new_password = "new-permanent-password"
    assert_error(client.post(f"{API}/admin-users/999999/reset-password", headers=csrf), 404, "NOT_FOUND")
    with TestClient(app) as target:
        login_body = {"username": account.username, "password": PASSWORD}
        assert target.post(login_url, json=login_body).status_code == 200
        response = client.post(url, headers=csrf)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert set(response.json()) == {"temporary_password"}
        temporary_password = response.json()["temporary_password"]
        assert response.text.count(temporary_password) == 1
        assert temporary_password not in account.password_hash
        assert_error(target.get(f"{API}/me"), 401, "AUTH_INVALID")
        assert_error(target.post(login_url, json=login_body), 401, "ADMIN_LOGIN_FAILED")
        login_body["password"] = temporary_password
        assert_error(target.post(login_url, json=login_body), 422, "VALIDATION_ERROR")
        assert target.post(login_url, json={**login_body, "new_password": new_password}).status_code == 200
        assert_error(
            target.post(login_url, json={**login_body, "new_password": new_password}),
            401,
            "ADMIN_LOGIN_FAILED",
        )
        assert target.post(login_url, json={**login_body, "password": new_password}).status_code == 200

    logs = client.get(f"{API}/audit-logs", params={"action": "admin_user.reset_password"}).json()["items"]
    assert len(logs) == 1 and logs[0]["target_id"] == account.id
    assert logs[0]["before"] is None and logs[0]["after"] is None
    assert temporary_password not in json.dumps(logs)
    assert temporary_password not in caplog.text
