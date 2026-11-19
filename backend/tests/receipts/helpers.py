"""回执、通知测试共用的准备数据函数：登录 → 上传 → 建照片 → 买套餐 → 办理。"""

import io
from dataclasses import dataclass

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EntitlementQuota, ReceiptApplication, ReceiptAttempt, Spec
from tests.conftest import login
from tests.factories import make_provider_for, make_spec, make_standard_plans

# 假身份证号，仅用于测试
FAKE_IDCARD = "110101199001010019"
SPEC_CODE = "rcp_idcard"
PROVIDER_CODE = "fake_zheying"


@dataclass
class World:
    headers: dict[str, str]
    photo_id: int
    spec: Spec


def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 800), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def new_photo(client: TestClient, headers: dict[str, str]) -> int:
    r = client.post("/api/v1/uploads", headers=headers, files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/photos", headers=headers, json={"file_id": r.json()["file_id"], "source": "upload"}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def buy_plan(client: TestClient, headers: dict[str, str], plan_code: str, photo_id: int | None) -> None:
    r = client.post("/api/v1/orders", headers=headers, json={"plan_code": plan_code, "photo_id": photo_id})
    assert r.status_code == 200, r.text
    order_no = r.json()["order_no"]
    r = client.post(f"/api/v1/dev/orders/{order_no}/simulate-paid", headers=headers)
    assert r.status_code == 200, r.text


def join_user(client: TestClient, spec: Spec, *, user: str, plan_code: str = "photo_year_39_9") -> World:
    """登录一个用户，上传照片并购买套餐（规格、服务商、套餐要先建好）。"""
    headers = login(client, user)
    photo_id = new_photo(client, headers)
    buy_plan(client, headers, plan_code, photo_id)
    return World(headers=headers, photo_id=photo_id, spec=spec)


def make_world(
    client: TestClient, db: Session, *, user: str = "dev:alice", plan_code: str = "photo_year_39_9"
) -> World:
    """建规格、服务商、标准套餐，并让 user 买好套餐。"""
    spec = make_spec(db, SPEC_CODE)
    make_provider_for(db, spec, PROVIDER_CODE)
    make_standard_plans(db)
    return join_user(client, spec, user=user, plan_code=plan_code)


def create_body(world: World, **override) -> dict:
    body = {
        "photo_id": world.photo_id,
        "spec_code": world.spec.code,
        "form": {"name": "张三", "idcard": FAKE_IDCARD},
    }
    body.update(override)
    return body


def create_app(client: TestClient, world: World, **override) -> dict:
    r = client.post(
        "/api/v1/receipt-applications", headers=world.headers, json=create_body(world, **override)
    )
    assert r.status_code == 200, r.text
    return r.json()


def simulate(
    client: TestClient, headers: dict[str, str], app_no: str, result: str, reason: str | None = None
):
    body = {"result": result}
    if reason:
        body["reject_reason"] = reason
    return client.post(f"/api/v1/dev/receipt-applications/{app_no}/simulate", headers=headers, json=body)


def get_application(db: Session, app_no: str) -> ReceiptApplication:
    return db.scalars(select(ReceiptApplication).where(ReceiptApplication.app_no == app_no)).one()


def current_attempt(db: Session, app_no: str) -> ReceiptAttempt:
    app = get_application(db, app_no)
    return db.scalars(
        select(ReceiptAttempt).where(
            ReceiptAttempt.application_id == app.id, ReceiptAttempt.is_current.is_(True)
        )
    ).one()


def quota_used(db: Session, entitlement_id: int) -> int:
    q = db.scalars(
        select(EntitlementQuota).where(
            EntitlementQuota.entitlement_id == entitlement_id,
            EntitlementQuota.benefit_type == "receipt_quota",
        )
    ).one()
    db.refresh(q)
    return q.used
