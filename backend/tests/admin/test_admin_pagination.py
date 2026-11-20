"""后台所有分页列表的页码、固定排序和筛选后总数。"""

from sqlalchemy import select

from app.core.utils import utcnow
from app.models import (
    AdminUser,
    AuditLog,
    ClientApp,
    NotifyTask,
    Order,
    ProviderSpec,
    ReceiptApplication,
    RouteRule,
    User,
)
from tests.admin.helpers import API, admin_login
from tests.factories import make_plan, make_provider_for, make_spec
from tests.orders.helpers import grant_plan, make_photo


def test_admin_lists_return_second_page_and_total(client, db):
    csrf = admin_login(client, db)
    owner = db.scalars(select(AdminUser).where(AdminUser.username == "boss")).one()
    specs = [make_spec(db, f"pg_admin_{i}") for i in range(11)]
    provider = make_provider_for(db, specs[0], "pg_provider")
    apps = [ClientApp(platform="wx_mini", app_id=f"pg_app_{i}", name=f"应用 {i}") for i in range(11)]
    db.add_all(apps)
    db.flush()
    users = [User(source_app_id=apps[0].id) for _ in range(11)]
    db.add_all(users)
    db.flush()

    user_id = users[0].id
    photos = [make_photo(db, user_id) for _ in range(11)]
    plan = make_plan(db, "pg_admin_plan", 100, {"storage_days": 7, "photo_scope": 0})
    entitlement = grant_plan(db, user_id, plan)
    now = utcnow()
    for i, (spec, photo) in enumerate(zip(specs, photos, strict=True)):
        application = ReceiptApplication(
            app_no=f"pg_receipt_{i}",
            user_id=user_id,
            photo_id=photo.id,
            spec_id=specs[0].id,
            entitlement_id=entitlement.id,
        )
        db.add(application)
        db.flush()
        db.add_all(
            [
                Order(
                    order_no=f"pg_order_{i}", user_id=user_id, total_fen=100, expire_at=now, client="wx_mini"
                ),
                NotifyTask(
                    user_id=user_id,
                    application_id=application.id,
                    event="receipt_expiring",
                    channel="mini_subscribe",
                    status="failed",
                    scheduled_at=now,
                ),
                AuditLog(
                    admin_id=owner.id, action="pagination.test", target_type="user", target_id=users[i].id
                ),
            ]
        )
        if i > 0:
            db.add_all(
                [
                    AdminUser(username=f"pg_admin_{i}", role="operator", password_hash=owner.password_hash),
                    ProviderSpec(
                        provider_id=provider.id, spec_id=spec.id, provider_item_id=str(i), cost_fen=100
                    ),
                    RouteRule(provider_id=provider.id, spec_id=spec.id, priority=10),
                ]
            )
    db.flush()
    first_task = db.scalar(select(NotifyTask.id).order_by(NotifyTask.id).limit(1))

    cases = [
        ("/users", {"source_app_id": apps[0].id}, "id", users[0].id),
        ("/users/search", {"source_app_id": apps[0].id}, "id", users[0].id),
        ("/client-apps", {}, "id", apps[0].id),
        ("/photos", {"user_id": user_id, "status": "active"}, "id", photos[0].id),
        ("/orders", {"user_id": user_id, "status": "pending"}, "order_no", "pg_order_0"),
        (
            "/receipt-applications",
            {"spec_code": specs[0].code, "manual_review": False},
            "app_no",
            "pg_receipt_0",
        ),
        ("/specs", {"keyword": "pg_admin"}, "code", specs[0].code),
        ("/provider-specs", {"provider_code": provider.code}, "spec_code", specs[0].code),
        ("/route-rules", {"provider_code": provider.code}, "spec_code", specs[0].code),
        ("/notify-tasks", {"status": "failed"}, "id", first_task),
        ("/admin-users", {}, "username", owner.username),
        ("/audit-logs", {"action": "pagination.test"}, "target_id", users[0].id),
    ]
    for path, filters, key, oldest in cases:
        for page, size in [(1, 10), (2, 1), (3, 0)]:
            data = {**filters, "page": page, "page_size": 10}
            if path == "/users/search":
                response = client.post(API + path, json=data, headers=csrf)
            else:
                response = client.get(API + path, params=data)
            assert response.status_code == 200, (path, response.text)
            result = response.json()
            assert set(result) == {"items", "total", "page", "page_size"}, path
            assert (result["total"], result["page"], result["page_size"]) == (11, page, 10), path
            assert len(result["items"]) == size, path
            if page == 2:
                assert result["items"][0][key] == oldest, path
