"""后台测试共用的小工具。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AdminUser, Entitlement, Order, OrderItem
from tests.conftest import login
from tests.orders.helpers import latest_user_id, make_photo

API = "/api/v1/admin"
PASSWORD = "test-password-123"  # 测试用假密码


def make_admin(
    db: Session,
    username: str = "boss",
    role: str = "owner",
    *,
    password: str = PASSWORD,
    status: str = "active",
) -> AdminUser:
    admin = AdminUser(username=username, password_hash=hash_password(password), role=role, status=status)
    db.add(admin)
    db.flush()
    return admin


def admin_login(
    client: TestClient, db: Session, username: str = "boss", role: str = "owner"
) -> dict[str, str]:
    """建后台账号并登录。cookie 由 TestClient 自动保存，返回修改类请求要带的 CSRF 头。"""
    make_admin(db, username, role)
    r = client.post(f"{API}/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def user_buys(client: TestClient, db: Session, plan_code: str = "photo_year_39_9", code: str = "dev:alice"):
    """让一个小程序用户买套餐并模拟支付成功，返回 (user_id, order_no, 用户请求头)。需要先建好标准套餐。"""
    h = login(client, code)
    uid = latest_user_id(db)
    photo = make_photo(db, uid)
    r = client.post("/api/v1/orders", headers=h, json={"plan_code": plan_code, "photo_id": photo.id})
    assert r.status_code == 200, r.text
    order_no = r.json()["order_no"]
    r = client.post(f"/api/v1/dev/orders/{order_no}/simulate-paid", headers=h)
    assert r.status_code == 200, r.text
    return uid, order_no, h


def entitlement_statuses(db: Session, order_no: str) -> list[str]:
    """查订单对应权益的状态（直接查列，避免读到会话里的旧对象）。"""
    return list(
        db.scalars(
            select(Entitlement.status)
            .join(OrderItem, OrderItem.id == Entitlement.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.order_no == order_no)
        )
    )
